"""Saved routines (schema v15): CRUD, order, the routine a session was started from, and exercise changes."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from support import act_as, create_user, fresh_owner
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.database import Base
from app.main import app
from app.migrations import SCHEMA_VERSION, migrate


class RoutineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        self.user = fresh_owner()
        self.squat = self.exercise("스쿼트")
        self.press = self.exercise("레그프레스")

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def exercise(self, name: str) -> int:
        response = self.client.post("/api/exercises", json={"name": name, "body_part": "하체"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def routine(self, name: str, *ids: int) -> dict:
        response = self.client.post("/api/routines", json={"name": name, "items": [{"exercise_id": i, "sets": 4} for i in ids]})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_routines_keep_their_order_and_can_be_reordered(self) -> None:
        legs = self.routine("하체", self.squat, self.press)
        back = self.routine("등", self.press)
        self.assertEqual([(r["name"], r["position"]) for r in self.client.get("/api/routines").json()], [("하체", 1), ("등", 2)])
        self.assertEqual(legs["items"], [{"exercise_id": self.squat, "sets": 4}, {"exercise_id": self.press, "sets": 4}])
        ordered = self.client.put("/api/routines/order", json={"ids": [back["id"], legs["id"]]}).json()
        self.assertEqual([r["name"] for r in ordered], ["등", "하체"])
        self.assertEqual(self.client.put("/api/routines/order", json={"ids": [back["id"]]}).status_code, 422)
        renamed = self.client.put(f"/api/routines/{legs['id']}", json={"name": "하체 A", "items": [{"exercise_id": self.squat, "sets": 5}]}).json()
        self.assertEqual((renamed["name"], renamed["items"]), ("하체 A", [{"exercise_id": self.squat, "sets": 5}]))

    def test_only_the_users_own_exercises_once_each(self) -> None:
        bad = self.client.post("/api/routines", json={"name": "하체", "items": [{"exercise_id": self.squat}, {"exercise_id": self.squat}]})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(self.client.post("/api/routines", json={"name": "하체", "items": []}).status_code, 422)
        mine = self.routine("하체", self.squat)
        other = create_user("friend@example.com", "member")
        act_as(other)
        self.assertEqual(self.client.post("/api/routines", json={"name": "남의 것", "items": [{"exercise_id": self.squat}]}).status_code, 422)
        self.assertEqual(self.client.get("/api/routines").json(), [])
        self.assertEqual(self.client.delete(f"/api/routines/{mine['id']}").status_code, 404)

    def test_a_session_remembers_its_routine_until_told_otherwise(self) -> None:
        legs = self.routine("하체", self.squat)
        body = {"workout_date": "2026-10-28", "title": "하체", "routine_id": legs["id"]}
        workout = self.client.post("/api/workouts", json=body).json()
        self.assertEqual(workout["routine_id"], legs["id"])
        # Finishing (or editing) sends no routine_id: it stays.
        kept = self.client.put(f"/api/workouts/{workout['id']}", json={"workout_date": "2026-10-28", "title": "하체 끝"}).json()
        self.assertEqual(kept["routine_id"], legs["id"])
        self.assertEqual(self.client.post("/api/workouts", json={**body, "routine_id": 999}).status_code, 404)
        self.client.delete(f"/api/routines/{legs['id']}")
        self.assertIsNone(self.client.get(f"/api/workouts/{workout['id']}").json()["routine_id"])

    def test_deleted_and_merged_exercises_leave_routines(self) -> None:
        legs = self.routine("하체", self.squat, self.press)
        only = self.routine("프레스만", self.press)
        self.assertEqual(self.client.delete(f"/api/exercises/{self.press}").status_code, 200)
        routines = {r["name"]: r["items"] for r in self.client.get("/api/routines").json()}
        self.assertEqual(routines, {"하체": [{"exercise_id": self.squat, "sets": 4}]})
        self.assertNotIn(only["id"], [r["id"] for r in self.client.get("/api/routines").json()])
        # 스쿼트 merged into the built-in preset: the routine follows it to the preset's exercise.
        merged = self.client.post(f"/api/exercises/{self.squat}/merge", json={"preset_id": "back_squat"})
        self.assertEqual(merged.status_code, 200, merged.text)
        target = merged.json()["target"]["id"]
        self.assertEqual(self.client.get("/api/routines").json()[0]["items"], [{"exercise_id": target, "sets": 4}])
        self.assertEqual(legs["name"], "하체")


class MigrationV15Tests(unittest.TestCase):
    def test_routines_table_and_column_after_a_backup(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fitlog.db"
            engine = create_engine("sqlite:///" + path.as_posix())
            try:
                Base.metadata.create_all(engine)
                with engine.begin() as c:
                    c.exec_driver_sql("DROP TABLE routines")
                    c.exec_driver_sql("ALTER TABLE workouts DROP COLUMN routine_id")
                    c.exec_driver_sql("INSERT INTO users (email, role, status, created_at, google_sub) VALUES ('a@example.com', 'member', 'active', '2026-10-01', 'sub-a')")
                    c.exec_driver_sql("INSERT INTO workouts (user_id, workout_date, title, source, created_at, updated_at) VALUES (1, '2026-10-01', '하체', 'local', '2026-10-01', '2026-10-01')")
                    c.exec_driver_sql("PRAGMA user_version=14")
                migrate(engine, path)
            finally:
                engine.dispose()
            self.assertGreaterEqual(SCHEMA_VERSION, 15)
            with closing(sqlite3.connect(path)) as c:
                self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
                self.assertEqual(c.execute("SELECT title, routine_id FROM workouts").fetchall(), [("하체", None)])
                self.assertEqual(c.execute("SELECT count(*) FROM routines").fetchone()[0], 0)
            self.assertEqual(len(list((Path(folder) / "backups").glob(f"before-v{SCHEMA_VERSION}-*.db"))), 1)


if __name__ == "__main__":
    unittest.main()
