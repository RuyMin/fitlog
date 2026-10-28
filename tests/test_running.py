import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from support import fresh_owner
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app.database import SessionLocal
from app.main import app
from app.migrations import fill_imported_runs, link_run_exercises, migrate
from app.models import Exercise, WorkoutSet
from app.services import excel_import
from app.services.legacy_xlsx import run_set, seconds_of
from test_excel_import import content, workbook

SCHEMA_V2 = (Path(__file__).parent / "fixtures" / "schema_v2.sql").read_text(encoding="utf-8")
# The watch summary from the request: 8.14 km in 43:03, 163/186 bpm, 172/194 spm, 7,448 steps, +6 m, best 4'31"/km.
RUN = {"distance_m": 8140, "duration_seconds": 2583, "calories": 623, "heart_rate": 163, "max_heart_rate": 186,
       "cadence": 172, "max_cadence": 194, "steps": 7448, "elevation_gain_m": 6, "best_pace_seconds": 271}
DETAILS = ("max_heart_rate", "cadence", "max_cadence", "steps", "elevation_gain_m", "best_pace_seconds")


class RunApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        fresh_owner()
        self.workout = self.client.post("/api/workouts", json={"workout_date": "2026-10-28", "title": "러닝"}).json()
        self.exercise = self.client.post("/api/exercises", json={"name": "러닝", "preset_id": "running"}).json()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def post(self, **fields):
        return self.client.post(f"/api/workouts/{self.workout['id']}/sets", json={"exercise_id": self.exercise["id"], "set_number": 1, **fields})

    def test_a_run_keeps_every_detail(self) -> None:
        created = self.post(completed=True, **RUN)
        self.assertEqual(created.status_code, 201, created.text)
        stored = self.client.get(f"/api/workouts/{self.workout['id']}").json()["sets"][0]
        self.assertEqual({key: stored[key] for key in RUN}, RUN)

    def test_out_of_range_details_are_rejected(self) -> None:
        for fields in [{"max_heart_rate": 300}, {"cadence": 400}, {"steps": -1}, {"elevation_gain_m": -2}, {"best_pace_seconds": 30}, {"cadence": 170.5}]:
            with self.subTest(fields=fields):
                self.assertEqual(self.post(**fields).status_code, 422)


class LegacyRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        self.user = fresh_owner()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def test_duration_cells_in_any_form(self) -> None:
        for value in ["43:03", "0:43:03", "43분 3초", "1899-12-30T00:43:03", 2583 / 86400]:
            with self.subTest(value=value):
                self.assertEqual(seconds_of(value), 2583)
        self.assertEqual(seconds_of(43), 2580)  # a plain number is minutes
        self.assertIsNone(seconds_of("빠르게"))

    def test_values_that_do_not_fit_are_left_to_the_memo(self) -> None:
        self.assertEqual(run_set({"거리(km)": "8.14", "운동시간": "43:03", "평균심박": "측정 안 함", "최대심박": 999}),
                         {"distance_m": 8140, "duration_seconds": 2583})

    def test_a_workbook_run_becomes_a_running_set(self) -> None:
        book = workbook()
        row = [datetime(2026, 9, 26), "이지런", 8.14, "43:03", "5:17", 163, 186, 172, 194, 6, 623, 48, 6, 7, 70, "가볍게", 1]
        for column, value in enumerate(row, 1):
            book["러닝 기록"].cell(4, column, value)
        preview = excel_import.create_preview(self.user.id, content(book), "records.xlsx")
        selected = [e["key"] for e in preview["entries"] if e["status"] in {"new", "updated"}]
        response = self.client.post("/api/import/" + preview["token"] + "/commit", json={"selected": selected})
        self.assertEqual(response.status_code, 200, response.text)
        with SessionLocal() as session:
            run = session.scalar(select(WorkoutSet).join(Exercise, Exercise.id == WorkoutSet.exercise_id).where(Exercise.name == "러닝"))
            self.assertEqual((run.distance_m, run.duration_seconds, run.heart_rate, run.max_heart_rate, run.cadence, run.max_cadence,
                              run.elevation_gain_m, run.calories), (8140, 2583, 163, 186, 172, 194, 6, 623))
            # Linked to the 러닝 preset, so the app shows distance, time and the run details for it.
            self.assertEqual(run.exercise.preset_id, "running")
            self.assertIn("VO2max: 48", run.workout.memo)


class MigrationV9Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "fitlog.db"
        with closing(sqlite3.connect(self.path)) as c:
            c.executescript(SCHEMA_V2)
        self.engine = create_engine("sqlite:///" + self.path.as_posix())
        with patch.dict(os.environ, {**os.environ, "FITLOG_OWNER_EMAIL": "owner@example.com"}, clear=True):
            migrate(self.engine, self.path)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.tmp.cleanup()

    def test_imported_runs_get_a_set_and_named_exercises_link(self) -> None:
        memo = "원본: 러닝 기록 5행\n날짜: 2026-09-26T00:00:00\n세션: 이지런\n거리(km): 8.14\n운동시간: 00:43:03\n평균심박: 163\n최대심박: 186\n평균케이던스: 172\nVO2max: 48"
        walk = "원본: 러닝 기록 6행\n날짜: 2026-09-27T00:00:00\n세션: 걷기\n거리(km): 3.2\n운동시간: 40:00"
        with closing(sqlite3.connect(self.path)) as c:
            user = c.execute("SELECT id FROM users").fetchone()[0]
            c.executemany("INSERT INTO workouts (user_id, workout_date, title, memo, source, external_id, created_at, updated_at) "
                          "VALUES (?, ?, ?, ?, 'excel', ?, '2026-09-26 00:00:00', '2026-09-26 00:00:00')",
                          [(user, "2026-09-26", "러닝 · 이지런", memo, "legacy_20260926_run_5"), (user, "2026-09-27", "걷기", walk, "legacy_20260926_run_6"),
                           (user, "2026-09-28", "하체", "원본: 웨이트 기록 4행", None)])
            # A custom 달리기 from an import, before this version linked names to presets.
            c.execute("INSERT INTO exercises (user_id, name, created_at) VALUES (?, '달리기', '2026-09-01 00:00:00')", (user,))
            c.commit()
        with self.engine.begin() as c:
            link_run_exercises(c)
            fill_imported_runs(c)
            fill_imported_runs(c)  # a run that already has its set is left alone
        with closing(sqlite3.connect(self.path)) as c:
            rows = c.execute("SELECT w.title, e.name, e.preset_id, s.distance_m, s.duration_seconds, s.heart_rate, s.max_heart_rate, s.cadence, s.external_id "
                             "FROM workout_sets s JOIN workouts w ON w.id = s.workout_id JOIN exercises e ON e.id = s.exercise_id ORDER BY w.id").fetchall()
        self.assertEqual(rows, [("러닝 · 이지런", "달리기", "running", 8140, 2583, 163, 186, 172, "legacy_20260926_run_set_5"),
                                ("걷기", "걷기", "walking", 3200, 2400, None, None, None, "legacy_20260926_run_set_6")])


if __name__ == "__main__":
    unittest.main()
