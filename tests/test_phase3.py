import unittest
from concurrent.futures import ThreadPoolExecutor

from support import TEMP
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Meal, SleepRecord
from app.schemas import SleepInput
from app.services.records import save_sleep
from app.services.persistence import RecordConflict


class DailyRecordAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())
        self.meal = {"name": "점심", "eaten_at": "2026-09-25T12:00:00+09:00", "meal_type": "lunch"}
        self.body = {"measured_at": "2026-09-25T08:00:00+09:00", "weight": 78.4}
        self.sleep = {"sleep_start": "2026-09-24T23:30:00+09:00", "sleep_end": "2026-09-25T06:12:00+09:00", "sleep_type": "main"}

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def create(self, path: str, body: dict) -> dict:
        response = self.client.post("/api/" + path, json=body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def summary(self, query: str = "date=2026-09-25&timezone=Asia/Seoul") -> dict:
        response = self.client.get("/api/dashboard?" + query)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_meal_crud_unknown_zero_and_persistence(self) -> None:
        item = self.create("meals", self.meal)
        self.assertIsNone(item["protein"])
        self.assertIsNone(item["image_path"])
        path = f"/api/meals/{item['id']}"
        updated = self.client.put(path, json={**self.meal, "protein": 0, "calories": 400, "memo": "<script>text</script>"})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["protein"], 0)
        engine.dispose()
        self.assertEqual(self.client.get(path).json()["calories"], 400)
        self.assertEqual(self.client.get(path).json()["memo"], "<script>text</script>")
        self.assertEqual(self.client.get("/api/meals").json()[0]["id"], item["id"])
        self.assertEqual(self.client.delete(path).json(), {"status": "deleted"})
        self.assertEqual(self.client.get(path).status_code, 404)

    def test_body_crud_requires_at_least_one_measurement(self) -> None:
        item = self.create("body-metrics", self.body)
        path = f"/api/body-metrics/{item['id']}"
        response = self.client.put(path, json={"measured_at": self.body["measured_at"], "body_fat": 0})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["weight"])
        self.assertEqual(response.json()["body_fat"], 0)
        self.assertEqual(self.client.put(path, json={"measured_at": self.body["measured_at"]}).status_code, 422)
        self.assertEqual(self.client.get(path).json()["body_fat"], 0)
        self.assertEqual(self.client.delete(path).status_code, 200)
        self.assertEqual(self.client.delete(path).status_code, 404)

    def test_sleep_duration_update_split_and_delete(self) -> None:
        first = self.create("sleep", self.sleep)
        self.assertEqual(first["duration_minutes"], 402)
        path = f"/api/sleep/{first['id']}"
        response = self.client.put(path, json={**self.sleep, "sleep_end": "2026-09-25T06:30:00+09:00"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["duration_minutes"], 420)
        self.create("sleep", {"sleep_start": "2026-09-25T13:00:00+09:00", "sleep_end": "2026-09-25T13:30:00+09:00", "sleep_type": "nap"})
        self.assertEqual(self.summary()["sleep_minutes"], 450)
        self.assertEqual(self.summary()["sleep_records_count"], 2)
        self.assertEqual(self.client.delete(path).status_code, 200)
        self.assertEqual(self.summary()["sleep_minutes"], 30)

    def test_sleep_overlap_rejected_adjacency_allowed_and_rollback(self) -> None:
        first = self.create("sleep", self.sleep)
        for body in [self.sleep, {**self.sleep, "sleep_start": "2026-09-25T02:00:00+09:00"},
                     {**self.sleep, "sleep_start": "2026-09-24T20:00:00+09:00", "sleep_end": "2026-09-25T08:00:00+09:00"}]:
            self.assertEqual(self.client.post("/api/sleep", json=body).status_code, 409)
        adjacent = {"sleep_start": self.sleep["sleep_end"], "sleep_end": "2026-09-25T07:00:00+09:00", "sleep_type": "nap"}
        second = self.create("sleep", adjacent)
        self.assertEqual(self.client.put(f"/api/sleep/{second['id']}", json=self.sleep).status_code, 409)
        self.assertEqual(self.client.get(f"/api/sleep/{second['id']}").json()["duration_minutes"], 48)
        self.assertEqual(self.client.put(f"/api/sleep/{first['id']}", json=self.sleep).status_code, 200)

    def test_concurrent_sleep_requests_cannot_double_book(self) -> None:
        data = SleepInput.model_validate(self.sleep)
        def write(_: int) -> str:
            with SessionLocal() as session:
                try:
                    save_sleep(session, data)
                    return "created"
                except RecordConflict:
                    return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, [1, 2]))
        self.assertCountEqual(results, ["created", "conflict"])
        self.assertEqual(len(self.client.get("/api/sleep").json()), 1)

    def test_validation(self) -> None:
        bad_cases = [
            ("meals", {**self.meal, "name": " "}),
            ("meals", {**self.meal, "protein": -1}),
            ("meals", {**self.meal, "calories": "Infinity"}),
            ("meals", {**self.meal, "meal_type": "invalid"}),
            ("meals", {**self.meal, "image_path": "../../secret"}),
            ("meals", {**self.meal, "eaten_at": "2026-09-25T12:00:00"}),
            ("body-metrics", {**self.body, "weight": 0}),
            ("body-metrics", {**self.body, "body_fat": 101}),
            ("body-metrics", {**self.body, "skeletal_muscle": -1}),
            ("body-metrics", {**self.body, "weight": "NaN"}),
            ("sleep", {**self.sleep, "duration_minutes": 100}),
            ("sleep", {**self.sleep, "sleep_end": self.sleep["sleep_start"]}),
            ("sleep", {**self.sleep, "sleep_end": "2026-09-24T23:30:59+09:00"}),
            ("sleep", {**self.sleep, "sleep_type": "invalid"}),
            ("sleep", {**self.sleep, "sleep_start": "2026-09-26T01:00:00+09:00"}),
        ]
        for path, body in bad_cases:
            with self.subTest(path=path, body=body):
                self.assertEqual(self.client.post("/api/" + path, json=body).status_code, 422)

    def test_timezone_storage_and_sleep_dst_elapsed_time(self) -> None:
        meal = self.create("meals", self.meal)
        self.assertEqual(meal["eaten_at"], "2026-09-25T03:00:00+00:00")
        with SessionLocal() as session:
            stored = session.get(Meal, meal["id"])
            self.assertIsNone(stored.eaten_at.tzinfo)
            self.assertEqual(stored.eaten_at.hour, 3)
        spring = self.create("sleep", {"sleep_start": "2026-03-08T01:30:00-05:00", "sleep_end": "2026-03-08T03:30:00-04:00"})
        self.assertEqual(spring["duration_minutes"], 60)
        fall = self.create("sleep", {"sleep_start": "2026-11-01T01:30:00-04:00", "sleep_end": "2026-11-01T01:30:00-05:00"})
        self.assertEqual(fall["duration_minutes"], 60)

    def test_timestamp_filters_pagination_and_sleep_end_semantics(self) -> None:
        for path, body, field in [("meals", self.meal, "eaten_at"), ("body-metrics", self.body, "measured_at")]:
            self.create(path, {**body, field: "2026-09-25T00:00:00+09:00"})
            newest = self.create(path, {**body, field: "2026-09-26T00:00:00+09:00"})
            query = "?from_at=2026-09-24T15:00:00Z&to_at=2026-09-25T15:00:00Z"
            result = self.client.get("/api/" + path + query)
            self.assertEqual(len(result.json()), 1)
            self.assertEqual(self.client.get("/api/" + path + "?limit=1").json()[0]["id"], newest["id"])
            self.assertEqual(len(self.client.get("/api/" + path + "?limit=1&offset=1").json()), 1)
            for bad in ["limit=0","limit=101","offset=-1","from_at=2026-09-25T00:00:00","from_at=2026-09-26T00:00:00Z&to_at=2026-09-25T00:00:00Z"]:
                self.assertEqual(self.client.get("/api/" + path + "?" + bad).status_code, 422)
        self.create("sleep", self.sleep)
        result = self.client.get("/api/sleep?from_at=2026-09-24T15:00:00Z&to_at=2026-09-25T15:00:00Z")
        self.assertEqual(len(result.json()), 1)
        self.assertEqual(result.json()[0]["duration_minutes"], 402)

    def test_dashboard_empty_unknown_and_partial_nutrition(self) -> None:
        result = self.summary()
        self.assertEqual(result["total_sets"], 0)
        self.assertIsNone(result["latest_weight"])
        self.assertIsNone(result["sleep_minutes"])
        self.assertIsNone(result["protein_grams"])
        self.assertEqual(result["protein_goal_grams"], 150)
        self.create("meals", self.meal)
        self.assertIsNone(self.summary()["protein_grams"])
        self.create("meals", {**self.meal, "protein": 0})
        self.assertEqual(self.summary()["protein_grams"], 0)
        self.create("meals", {**self.meal, "protein": 35.5})
        result = self.summary()
        self.assertEqual(result["meals_count"], 3)
        self.assertEqual(result["protein_known_count"], 2)
        self.assertEqual(result["protein_grams"], 35.5)

    def test_dashboard_local_day_latest_weight_and_workouts(self) -> None:
        self.create("meals", {**self.meal, "eaten_at": "2026-09-25T00:00:00+09:00", "protein": 10})
        self.create("meals", {**self.meal, "eaten_at": "2026-09-26T00:00:00+09:00", "protein": 99})
        past = self.create("body-metrics", {**self.body, "measured_at": "2026-09-20T08:00:00+09:00"})
        self.create("body-metrics", {"measured_at": "2026-09-25T08:00:00+09:00", "body_fat": 15})
        self.create("body-metrics", {**self.body, "measured_at": "2026-09-26T08:00:00+09:00", "weight": 79})
        workout = self.create("workouts", {"workout_date":"2026-09-25","title":"하체"})
        exercise = self.create("exercises", {"name":"Squat"})
        self.create(f"workouts/{workout['id']}/sets", {"exercise_id":exercise["id"],"set_number":1,"completed":True})
        self.create(f"workouts/{workout['id']}/sets", {"exercise_id":exercise["id"],"set_number":2})
        self.create("sleep", self.sleep)
        result = self.summary()
        self.assertEqual(result["protein_grams"], 10)
        self.assertEqual(result["latest_weight"]["id"], past["id"])
        self.assertEqual(result["workouts_count"], 1)
        self.assertEqual(result["total_sets"], 2)
        self.assertEqual(result["completed_sets"], 1)
        self.assertEqual(result["sleep_minutes"], 402)

    def test_dashboard_dst_day_and_invalid_timezone(self) -> None:
        for stamp, protein in [("2026-03-08T00:00:00-05:00", 10), ("2026-03-08T23:59:00-04:00", 20), ("2026-03-09T00:00:00-04:00", 99)]:
            self.create("meals", {**self.meal, "eaten_at":stamp, "protein":protein})
        self.assertEqual(self.summary("date=2026-03-08&timezone=America/New_York")["protein_grams"], 30)
        for query in ["timezone=Invalid/Zone", "timezone=../UTC", "date=9999-12-31"]:
            self.assertEqual(self.client.get("/api/dashboard?" + query).status_code, 422)

    def test_not_found_api_cache_and_assets(self) -> None:
        for path, body in [("meals",self.meal), ("body-metrics",self.body), ("sleep",self.sleep)]:
            response = self.client.get("/api/" + path)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(self.client.get("/api/" + path + "/99999").status_code, 404)
            self.assertEqual(self.client.put("/api/" + path + "/99999", json=body).status_code, 404)
            self.assertEqual(self.client.delete("/api/" + path + "/99999").status_code, 404)
        for path in ["/meals","/body-metrics","/sleep","/static/js/records.js","/static/css/records.css"]:
            self.assertEqual(self.client.get(path).status_code, 200)
