import unittest
from unittest.mock import patch

from support import TEMP
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import WorkoutSet


class WorkoutAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())
        self.exercise = self.client.post("/api/exercises", json={"name": "Squat", "body_part": "하체"}).json()
        self.workout = self.client.post("/api/workouts", json={"workout_date": "2026-09-25", "title": "하체"}).json()
        self.path = f"/api/workouts/{self.workout['id']}"
        self.set_data = {"exercise_id": self.exercise["id"], "set_number": 1, "weight": 60, "reps": 8}

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def test_complete_workout_set_lifecycle(self) -> None:
        response = self.client.post(self.path + "/sets", json=self.set_data)
        self.assertEqual(response.status_code, 201, response.text)
        item = response.json()
        path = self.path + f"/sets/{item['id']}"
        self.assertEqual(item["exercise"]["name"], "Squat")
        self.assertFalse(item["completed"])
        response = self.client.put(path, json={**self.set_data, "completed": True, "memo": "good"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["completed"])
        engine.dispose()
        self.assertEqual(self.client.get(path).json()["memo"], "good")
        detail = self.client.get(self.path).json()
        self.assertEqual(len(detail["sets"]), 1)
        self.assertEqual(self.client.get(self.path + "/sets").json()[0]["id"], item["id"])
        response = self.client.put(self.path, json={"title": "수정한 운동", "workout_date": "2026-09-24", "memo": "메모"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["sets"]), 1)
        self.assertEqual(self.client.delete(path).json(), {"status": "deleted"})
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.delete(self.path).status_code, 200)
        self.assertEqual(self.client.get(self.path).status_code, 404)

    def test_exercise_crud_and_duplicate_rollback(self) -> None:
        path = f"/api/exercises/{self.exercise['id']}"
        self.assertEqual(self.client.post("/api/exercises", json={"name": " Squat "}).status_code, 409)
        self.assertEqual(self.client.get(path).json()["name"], "Squat")
        updated = self.client.put(path, json={"name": "Back squat", "category": "근력"})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["category"], "근력")
        self.assertEqual(self.client.get("/api/exercises").json()[0]["name"], "Back squat")
        self.assertEqual(self.client.delete(path).status_code, 200)
        self.assertEqual(self.client.get(path).status_code, 404)

    def test_duplicate_set_and_wrong_parent(self) -> None:
        item = self.client.post(self.path + "/sets", json=self.set_data).json()
        self.assertEqual(self.client.post(self.path + "/sets", json=self.set_data).status_code, 409)
        other = self.client.post("/api/workouts", json={"title": "Other", "workout_date": "2026-09-25"}).json()
        path = f"/api/workouts/{other['id']}/sets/{item['id']}"
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.put(path, json=self.set_data).status_code, 404)
        self.assertEqual(self.client.delete(path).status_code, 404)
        self.assertEqual(len(self.client.get(self.path).json()["sets"]), 1)

    def test_set_order_and_update_conflict(self) -> None:
        second = self.client.post(self.path + "/sets", json={**self.set_data, "set_number": 2}).json()
        self.client.post(self.path + "/sets", json=self.set_data)
        response = self.client.put(self.path + f"/sets/{second['id']}", json=self.set_data)
        self.assertEqual(response.status_code, 409)
        self.assertEqual([s["set_number"] for s in self.client.get(self.path).json()["sets"]], [1, 2])

    def test_in_use_exercise_and_cascade(self) -> None:
        item = self.client.post(self.path + "/sets", json=self.set_data).json()
        self.assertEqual(self.client.delete(f"/api/exercises/{self.exercise['id']}").status_code, 409)
        self.assertEqual(self.client.delete(self.path).status_code, 200)
        with SessionLocal() as session:
            self.assertIsNone(session.scalar(select(WorkoutSet).where(WorkoutSet.id == item["id"])))
        self.assertEqual(self.client.delete(f"/api/exercises/{self.exercise['id']}").status_code, 200)

    def test_timezone_and_time_validation(self) -> None:
        data = {"workout_date": "2026-09-25", "title": "Timezone",
                "started_at": "2026-09-25T18:00:00+09:00", "ended_at": "2026-09-25T19:00:00+09:00"}
        result = self.client.put(self.path, json=data)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["started_at"], "2026-09-25T09:00:00+00:00")
        self.assertEqual(self.client.put(self.path, json={**data, "started_at": None}).status_code, 422)
        self.assertEqual(self.client.put(self.path, json={**data, "ended_at": "2026-09-25T17:00:00+09:00"}).status_code, 422)
        self.assertEqual(self.client.put(self.path, json={**data, "started_at": "2026-09-25T18:00:00"}).status_code, 422)

    def test_validation_and_missing_records(self) -> None:
        for data in [{**self.set_data, "weight": -1}, {**self.set_data, "set_number": 0},
                     {**self.set_data, "reps": 1.5}, {**self.set_data, "weight": "NaN"},
                     {**self.set_data, "exercise_id": True}, {**self.set_data, "unknown": 1}]:
            with self.subTest(data=data):
                self.assertEqual(self.client.post(self.path + "/sets", json=data).status_code, 422)
        self.assertEqual(self.client.post("/api/workouts", json={"title": " ", "workout_date": "2026-09-25"}).status_code, 422)
        self.assertEqual(self.client.post("/api/exercises", json={"name": "x" * 201}).status_code, 422)
        self.assertEqual(self.client.post(self.path + "/sets", json={**self.set_data, "exercise_id": 99999}).status_code, 404)
        self.assertEqual(self.client.get("/api/workouts/99999/sets").status_code, 404)

    def test_pagination_date_filter_and_api_cache(self) -> None:
        self.client.post("/api/workouts", json={"workout_date": "2026-09-24", "title": "이전"})
        result = self.client.get("/api/workouts?limit=1&offset=1")
        self.assertEqual(result.json()[0]["title"], "이전")
        self.assertEqual(result.headers["cache-control"], "no-store")
        result = self.client.get("/api/workouts?date_from=2026-09-25&date_to=2026-09-25")
        self.assertEqual(len(result.json()), 1)
        for query in ["limit=101", "offset=-1", "date_from=2026-09-26&date_to=2026-09-24"]:
            self.assertEqual(self.client.get("/api/workouts?" + query).status_code, 422)

    def test_db_failure_and_workout_assets(self) -> None:
        with patch("app.services.workouts.list_workouts", side_effect=OperationalError("private", {}, Exception("private"))):
            response = self.client.get("/api/workouts")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private", response.text)
        for path in ["/workouts", "/static/js/workouts.js", "/static/css/workouts.css", "/static/js/home.js"]:
            self.assertEqual(self.client.get(path).status_code, 200)

    def test_unknown_numbers_and_zero_weight_roundtrip(self) -> None:
        result = self.client.post(self.path + "/sets", json={"exercise_id": self.exercise["id"], "set_number": 1})
        self.assertIsNone(result.json()["weight"])
        result = self.client.put(self.path + "/sets/" + str(result.json()["id"]), json={**self.set_data, "weight": 0, "reps": 0})
        self.assertEqual(result.json()["weight"], 0)
        self.assertEqual(result.json()["reps"], 0)
