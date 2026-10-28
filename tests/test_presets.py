import os
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from support import TEMP, fresh_owner  # noqa: F401 — isolate FITLOG_DATA_DIR before app imports
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.main import app
from app.migrations import SCHEMA_VERSION, migrate
from app.services import exercise_presets

SCHEMA_V2 = (Path(__file__).parent / "fixtures" / "schema_v2.sql").read_text(encoding="utf-8")


class PresetCatalogTests(unittest.TestCase):
    def test_catalog_is_consistent(self) -> None:
        data = exercise_presets.catalog()
        presets = data["presets"]
        self.assertGreaterEqual(len(presets), 100)
        self.assertEqual(len({p["id"] for p in presets}), len(presets))
        self.assertEqual(len({p["name"] for p in presets}), len(presets))
        for preset in presets:
            self.assertIn(preset["body_part"], data["parts"], preset["id"])
            self.assertIn(preset["equipment"], data["equipment"], preset["id"])
            self.assertIn(preset["tracking"], data["tracking"], preset["id"])
            self.assertTrue(preset["muscles"], preset["id"])
            variants = preset.get("variants", [])
            self.assertEqual(len({v["id"] for v in variants}), len(variants), preset["id"])
            for variant in variants:
                self.assertTrue(variant["muscles"] and variant["label"] and variant["group"], (preset["id"], variant["id"]))
                self.assertLessEqual(len(variant["id"]), 40)

    def test_name_matching(self) -> None:
        self.assertEqual(exercise_presets.match_name("바벨 벤치프레스"), "bench_press")
        self.assertEqual(exercise_presets.match_name(" 사레레 "), "lateral_raise")
        self.assertEqual(exercise_presets.match_name("barbell bench press"), "bench_press")
        self.assertIsNone(exercise_presets.match_name("나만의 운동"))


class PresetApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        fresh_owner()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def test_presets_endpoint_and_exercise_link(self) -> None:
        catalog = self.client.get("/api/exercise-presets").json()
        self.assertEqual(len(catalog["presets"]), len(exercise_presets.catalog()["presets"]))
        created = self.client.post("/api/exercises", json={"name": "사이드 레터럴 레이즈", "body_part": "어깨", "category": "덤벨", "preset_id": "lateral_raise"})
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["preset_id"], "lateral_raise")
        again = self.client.post("/api/exercises", json={"name": "사레레 두번째", "preset_id": "lateral_raise"})
        self.assertEqual(again.status_code, 409)
        unknown = self.client.post("/api/exercises", json={"name": "모르는 운동", "preset_id": "nope"})
        self.assertEqual(unknown.status_code, 422)
        custom = self.client.post("/api/exercises", json={"name": "내 운동"})
        self.assertEqual(custom.status_code, 201)
        self.assertIsNone(custom.json()["preset_id"])

    def test_workout_page_links_catalog_by_version(self) -> None:
        page = self.client.get("/workouts").text
        match = re.search(r'id="preset-catalog" href="(/api/exercise-presets\?v=([0-9a-f]{12}))"', page)
        self.assertIsNotNone(match, "workouts page must preload the catalog by its version")
        response = self.client.get(match[1])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "private, max-age=31536000, immutable")
        self.assertEqual(self.client.get("/api/exercise-presets?v=old").headers["cache-control"], "no-store")
        self.assertEqual(response.json(), self.client.get("/api/exercise-presets").json())


class CardioSetApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        fresh_owner()
        self.workout = self.client.post("/api/workouts", json={"workout_date": "2026-10-22", "title": "유산소"}).json()
        self.exercise = self.client.post("/api/exercises", json={"name": "트레드밀", "preset_id": "treadmill"}).json()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def post(self, **fields):
        return self.client.post(f"/api/workouts/{self.workout['id']}/sets", json={"exercise_id": self.exercise["id"], **fields})

    def test_intervals_store_cardio_fields(self) -> None:
        first = self.post(set_number=1, duration_seconds=300, speed_kmh=5.5, incline_pct=0, completed=True)
        second = self.post(set_number=2, duration_seconds=1200, speed_kmh=9, incline_pct=2, calories=310, heart_rate=152)
        self.assertEqual((first.status_code, second.status_code), (201, 201), second.text)
        sets = self.client.get(f"/api/workouts/{self.workout['id']}").json()["sets"]
        self.assertEqual([(s["duration_seconds"], s["speed_kmh"], s["incline_pct"]) for s in sets], [(300, 5.5, 0), (1200, 9, 2)])
        self.assertEqual((sets[1]["calories"], sets[1]["heart_rate"], sets[1]["weight"]), (310, 152, None))

    def test_ai_excel_mapping_keeps_cardio_fields(self) -> None:
        from app.services.excel_import import mapped_rows
        rows, dropped = mapped_rows({"workouts": [{"workout_date": "2026-10-01", "title": "유산소", "sets": [
            {"exercise": "트레드밀", "set_number": 1, "duration_seconds": 1800, "speed_kmh": 8.5, "incline_pct": 2, "completed": True}]}]},
            "2026-10-22T00:00:00+00:00", "t")
        self.assertEqual(dropped, [])
        row = rows["workout_sets"][0]
        self.assertEqual((row["duration_seconds"], row["speed_kmh"], row["incline_pct"], row["distance_m"]), (1800, 8.5, 2, None))

    def test_out_of_range_values_are_rejected(self) -> None:
        for fields in [{"incline_pct": 80}, {"heart_rate": 300}, {"duration_seconds": -1}, {"distance_m": -5}, {"duration_seconds": 1.5}]:
            with self.subTest(fields=fields):
                self.assertEqual(self.post(set_number=1, **fields).status_code, 422)


class VariantSetApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        fresh_owner()
        self.workout = self.client.post("/api/workouts", json={"workout_date": "2026-10-23", "title": "등"}).json()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def add(self, exercise, **fields):
        return self.client.post(f"/api/workouts/{self.workout['id']}/sets", json={"exercise_id": exercise["id"], "set_number": 1, **fields})

    def test_variant_must_belong_to_the_exercise_preset(self) -> None:
        pulldown = self.client.post("/api/exercises", json={"name": "랫풀다운", "preset_id": "lat_pulldown"}).json()
        custom = self.client.post("/api/exercises", json={"name": "내 운동"}).json()
        created = self.add(pulldown, variant="parallel", weight=50, reps=10)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["variant"], "parallel")
        self.assertEqual(self.add(pulldown, set_number=2).json()["variant"], None)
        self.assertEqual(self.add(pulldown, set_number=3, variant="feet_high").status_code, 422)
        self.assertEqual(self.add(custom, variant="wide").status_code, 422)
        updated = self.client.put(f"/api/workouts/{self.workout['id']}/sets/{created.json()['id']}",
                                  json={"exercise_id": pulldown["id"], "set_number": 1, "variant": None})
        self.assertIsNone(updated.json()["variant"])


class MigrationV4Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "fitlog.db"
        with closing(sqlite3.connect(self.path)) as c:
            c.executescript(SCHEMA_V2)
            c.executescript("""
INSERT INTO exercises VALUES (1, '스쿼트', NULL, '하체', '2026-09-01 00:00:00');
INSERT INTO exercises VALUES (2, 'Barbell Back Squat', NULL, NULL, '2026-09-01 00:00:00');
INSERT INTO exercises VALUES (3, '사레레', NULL, NULL, '2026-09-01 00:00:00');
INSERT INTO exercises VALUES (4, '내 맘대로 운동', NULL, NULL, '2026-09-01 00:00:00');
INSERT INTO workouts (id, workout_date, title, created_at, updated_at) VALUES (1, '2026-09-01', '하체', '2026-09-01 00:00:00', '2026-09-01 00:00:00');
INSERT INTO workout_sets (id, workout_id, exercise_id, set_number, weight, reps, completed) VALUES (1, 1, 1, 1, 60, 8, 1);
""")
        self.engine = create_engine("sqlite:///" + self.path.as_posix())

    def tearDown(self) -> None:
        self.engine.dispose()
        self.tmp.cleanup()

    def test_v3_to_current_links_presets_and_adds_cardio_columns(self) -> None:
        env = {**os.environ, "FITLOG_OWNER_EMAIL": "owner@example.com"}
        with patch("app.migrations.SCHEMA_VERSION", 3), patch.dict(os.environ, env, clear=True):
            migrate(self.engine, self.path)
        with patch.dict(os.environ, env, clear=True):
            migrate(self.engine, self.path)
        with closing(sqlite3.connect(self.path)) as c:
            self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            linked = dict(c.execute("SELECT id, preset_id FROM exercises ORDER BY id").fetchall())
            # v5: the strength set keeps its values and gains empty cardio columns.
            self.assertEqual(c.execute("SELECT weight, reps, duration_seconds, distance_m, heart_rate, variant FROM workout_sets").fetchone(), (60.0, 8, None, None, None, None))
        # 스쿼트 is an alias of the back squat; the second back-squat row stays unlinked (one per user and preset).
        self.assertEqual(linked, {1: "back_squat", 2: None, 3: "lateral_raise", 4: None})


if __name__ == "__main__":
    unittest.main()
