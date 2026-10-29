"""One-side exercises (schema v16): left reps beside `reps` (the right side), and a per-exercise switch."""
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from support import fresh_owner
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.database import Base
from app.main import app
from app.migrations import SCHEMA_VERSION, migrate
from app.services import exercise_presets

DAY = "2026-09-22"


class OneSideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        fresh_owner()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def post(self, path: str, data: dict) -> dict:
        response = self.client.post("/api/" + path, json=data)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_left_reps_count_toward_volume(self) -> None:
        row = self.post("exercises", {"name": "원암 덤벨 로우", "preset_id": "db_row"})
        workout = self.post("workouts", {"workout_date": DAY, "title": "등"})
        saved = self.post(f"workouts/{workout['id']}/sets", {"exercise_id": row["id"], "set_number": 1, "weight": 20, "reps": 10, "left_reps": 8, "completed": True})
        self.assertEqual((saved["reps"], saved["left_reps"]), (10, 8))
        stats = self.client.get(f"/api/statistics?date_from={DAY}&date_to={DAY}&timezone=Asia/Seoul").json()
        self.assertEqual(stats["summary"]["volume_kg_reps"], 360)  # 20 kg × (10 + 8)
        self.assertEqual(self.client.get(f"/api/dashboard?date={DAY}&timezone=Asia/Seoul").json()["volume_kg"], 360)
        self.assertEqual(self.client.post(f"/api/workouts/{workout['id']}/sets", json={"exercise_id": row["id"], "set_number": 2, "left_reps": -1}).status_code, 422)

    def test_switch_is_kept_when_the_editor_saves_without_it(self) -> None:
        row = self.post("exercises", {"name": "내 런지", "one_side": True})
        self.assertTrue(row["one_side"])
        renamed = self.client.put(f"/api/exercises/{row['id']}", json={"name": "내 리버스 런지"}).json()
        self.assertEqual((renamed["name"], renamed["one_side"]), ("내 리버스 런지", True))
        self.assertFalse(self.client.put(f"/api/exercises/{row['id']}", json={"name": "내 리버스 런지", "one_side": False}).json()["one_side"])

    def test_presets_say_which_are_one_side_and_what_the_weight_means(self) -> None:
        presets = {preset["id"]: preset for preset in exercise_presets.base()["presets"]}
        self.assertEqual(presets["db_row"]["side"], "one")
        self.assertNotIn("side", presets["db_shoulder_press"])
        self.assertEqual((presets["db_shoulder_press"]["load"], presets["db_overhead_extension"]["load"]), ("per_hand", "single"))


class MigrationV16Tests(unittest.TestCase):
    def test_columns_added_after_a_backup(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fitlog.db"
            engine = create_engine("sqlite:///" + path.as_posix())
            try:
                Base.metadata.create_all(engine)
                with engine.begin() as c:
                    c.exec_driver_sql("ALTER TABLE exercises DROP COLUMN one_side")
                    # left_reps sits in a CHECK constraint, so the v15 table is rebuilt without it.
                    sql = c.exec_driver_sql("SELECT sql FROM sqlite_master WHERE name='workout_sets'").scalar_one()
                    sql = re.sub(r"\s*left_reps INTEGER,", "", sql)
                    sql = re.sub(r",\s*CONSTRAINT ck_set_left_reps CHECK \([^)]*\)", "", sql)
                    self.assertNotIn("left_reps", sql)
                    c.exec_driver_sql("DROP TABLE workout_sets")
                    c.exec_driver_sql(sql)
                    c.exec_driver_sql("PRAGMA user_version=15")
                migrate(engine, path)
            finally:
                engine.dispose()
            with closing(sqlite3.connect(path)) as c:
                self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
                self.assertIn("left_reps", [row[1] for row in c.execute("PRAGMA table_info(workout_sets)")])
                self.assertIn("one_side", [row[1] for row in c.execute("PRAGMA table_info(exercises)")])
            self.assertEqual(len(list((Path(folder) / "backups").glob(f"before-v{SCHEMA_VERSION}-*.db"))), 1)


if __name__ == "__main__":
    unittest.main()
