import unittest

from support import TEMP
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import Base, engine, SessionLocal
from app.main import app
from app.models import Workout, WorkoutSet, BodyMetric, SleepRecord


class StatisticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def create(self, path: str, data: dict) -> dict:
        response = self.client.post("/api/" + path, json=data)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def stats(self, query: str = "") -> dict:
        response = self.client.get("/api/statistics?date_from=2026-09-20&date_to=2026-09-25&timezone=Asia/Seoul" + query)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def seed_workouts(self) -> tuple[dict, dict]:
        squat = self.create("exercises", {"name": "Squat"})
        body = self.create("exercises", {"name": "Push-up"})
        workouts = [self.create("workouts", {"workout_date": day, "title": "운동"}) for day in ["2026-09-20","2026-09-21","2026-09-23","2026-09-23","2026-09-26"]]
        for index, exercise, number, weight, reps, completed in [
            (0,squat,1,60,8,True),(0,squat,2,70,5,False),
            (1,squat,1,65,5,True),(1,squat,2,None,10,True),
            (3,body,1,0,10,True),(4,squat,1,200,10,True),
        ]:
            self.create(f"workouts/{workouts[index]['id']}/sets", {"exercise_id":exercise["id"],"set_number":number,"weight":weight,"reps":reps,"completed":completed})
        return workouts[0], squat

    def test_completed_only_volume_and_week_boundaries(self) -> None:
        self.seed_workouts()
        result = self.stats()
        summary = result["summary"]
        self.assertEqual(summary["workouts_count"], 4)
        self.assertEqual(summary["sets_count"], 4)
        self.assertEqual(summary["known_volume_sets"], 3)
        self.assertEqual(summary["volume_kg_reps"], 805)
        self.assertEqual([week["sets_count"] for week in result["weekly"]], [1,3])
        self.assertEqual([week["workouts_count"] for week in result["weekly"]], [1,3])
        self.assertEqual(result["weekly"][0]["week_start"], "2026-09-14")
        self.assertEqual(result["weekly"][0]["period_start"], "2026-09-20")
        self.assertEqual(result["weekly"][0]["period_end"], "2026-09-20")
        squat = result["exercises"][0]
        self.assertEqual(squat["name"], "Squat")
        self.assertEqual(squat["max_weight"], 65)
        self.assertEqual(squat["volume_kg_reps"], 805)
        self.assertEqual([point["volume_kg_reps"] for point in squat["daily_volume"]], [480,325])
        self.assertEqual(result["exercises"][1]["volume_kg_reps"], 0)
        self.assertIsNone(result["daily"][2]["volume_kg_reps"])

    def test_include_incomplete_and_live_edit_delete(self) -> None:
        workout, squat = self.seed_workouts()
        result = self.stats("&completed_only=false")
        self.assertEqual(result["summary"]["sets_count"], 5)
        self.assertEqual(result["summary"]["volume_kg_reps"], 1155)
        self.assertEqual(result["exercises"][0]["max_weight"], 70)
        sets = self.client.get(f"/api/workouts/{workout['id']}/sets").json()
        self.client.put(f"/api/workouts/{workout['id']}/sets/{sets[0]['id']}", json={"exercise_id":squat["id"],"set_number":1,"weight":50,"reps":8,"completed":True})
        self.assertEqual(self.stats()["summary"]["volume_kg_reps"], 725)
        self.client.delete(f"/api/workouts/{workout['id']}")
        self.assertEqual(self.stats()["summary"]["volume_kg_reps"], 325)
        self.assertEqual(self.stats()["summary"]["workouts_count"], 3)

    def test_unknown_and_zero_are_distinct(self) -> None:
        exercise = self.create("exercises", {"name":"Unknown"})
        workout = self.create("workouts", {"workout_date":"2026-09-20","title":"미입력"})
        item = self.create(f"workouts/{workout['id']}/sets", {"exercise_id":exercise["id"],"set_number":1,"completed":True})
        result = self.stats()
        self.assertIsNone(result["summary"]["volume_kg_reps"])
        self.assertIsNone(result["exercises"][0]["max_weight"])
        self.assertEqual(result["summary"]["sets_count"],1)
        self.client.put(f"/api/workouts/{workout['id']}/sets/{item['id']}",json={"exercise_id":exercise["id"],"set_number":1,"weight":0,"reps":0,"completed":True})
        result = self.stats()
        self.assertEqual(result["summary"]["volume_kg_reps"],0)
        self.assertEqual(result["exercises"][0]["max_weight"],0)
        self.assertEqual(result["daily"][0]["volume_kg_reps"],0)

    def test_daily_last_weight_and_missing_days(self) -> None:
        for stamp, weight in [
            ("2026-09-19T23:59:00+09:00",90),
            ("2026-09-20T08:00:00+09:00",80),
            ("2026-09-20T18:00:00+09:00",79.8),
            ("2026-09-20T18:00:00+09:00",79.5),
            ("2026-09-24T08:00:00+09:00",78.4),
            ("2026-09-26T00:00:00+09:00",77),
        ]:
            self.create("body-metrics",{"measured_at":stamp,"weight":weight})
        self.create("body-metrics",{"measured_at":"2026-09-20T20:00:00+09:00","body_fat":18})
        result = self.stats()
        self.assertEqual(result["daily"][0]["weight"],79.5)
        self.assertIsNone(result["daily"][1]["weight"])
        self.assertEqual(result["summary"]["weight_days"],2)
        self.assertEqual(result["summary"]["weight_change_kg"],-1.1)

    def test_sleep_ending_day_and_recorded_day_average(self) -> None:
        for start, end, kind in [
            ("2026-09-19T23:00:00+09:00","2026-09-20T05:00:00+09:00","main"),
            ("2026-09-20T14:00:00+09:00","2026-09-20T14:30:00+09:00","nap"),
            ("2026-09-21T23:00:00+09:00","2026-09-22T06:00:00+09:00","main"),
            ("2026-09-25T23:00:00+09:00","2026-09-26T00:00:00+09:00","main"),
        ]:
            self.create("sleep",{"sleep_start":start,"sleep_end":end,"sleep_type":kind})
        result=self.stats()
        self.assertEqual(result["daily"][0]["sleep_minutes"],390)
        self.assertEqual(result["daily"][0]["sleep_records_count"],2)
        self.assertIsNone(result["daily"][1]["sleep_minutes"])
        self.assertEqual(result["summary"]["average_sleep_minutes"],405)
        self.assertEqual(result["summary"]["sleep_days"],2)

    def test_timezone_day_boundaries_and_dst(self) -> None:
        self.create("body-metrics",{"measured_at":"2026-03-08T00:00:00-05:00","weight":80})
        self.create("body-metrics",{"measured_at":"2026-03-08T23:59:00-04:00","weight":79})
        self.create("body-metrics",{"measured_at":"2026-03-09T00:00:00-04:00","weight":78})
        self.create("sleep",{"sleep_start":"2026-03-08T01:30:00-05:00","sleep_end":"2026-03-08T03:30:00-04:00"})
        response=self.client.get("/api/statistics?date_from=2026-03-08&date_to=2026-03-08&timezone=America/New_York")
        self.assertEqual(response.status_code,200,response.text)
        result=response.json()
        self.assertEqual(result["daily"][0]["weight"],79)
        self.assertEqual(result["daily"][0]["sleep_minutes"],60)
        self.assertIsNone(result["summary"]["weight_change_kg"])

    def test_empty_default_period_and_leap_year(self) -> None:
        result=self.stats()
        self.assertEqual(len(result["daily"]),6)
        self.assertEqual(result["summary"]["workouts_count"],0)
        self.assertIsNone(result["summary"]["volume_kg_reps"])
        self.assertIsNone(result["summary"]["average_sleep_minutes"])
        self.assertEqual(result["exercises"],[])
        result=self.client.get("/api/statistics?date_to=2026-09-25").json()
        self.assertEqual(result["date_from"],"2026-08-27")
        self.assertEqual(len(result["daily"]),30)
        result=self.client.get("/api/statistics?date_from=2024-01-01&date_to=2024-12-31")
        self.assertEqual(result.status_code,200)
        self.assertEqual(len(result.json()["daily"]),366)

    def test_invalid_query(self) -> None:
        for query in [
            "date_from=2026-09-25&date_to=2026-09-20",
            "date_from=2024-01-01&date_to=2025-01-01",
            "timezone=Invalid/Zone", "timezone=../UTC", "completed_only=maybe",
            "date_from=bad", "date_to=9999-12-31", "date_to=0001-01-01",
        ]:
            with self.subTest(query=query):
                self.assertEqual(self.client.get("/api/statistics?"+query).status_code,422)

    def test_read_only_and_assets(self) -> None:
        self.seed_workouts()
        def counts() -> list[int]:
            with SessionLocal() as session:
                return [session.scalar(select(func.count()).select_from(model)) for model in [Workout,WorkoutSet,BodyMetric,SleepRecord]]
        before=counts()
        response=self.client.get("/api/statistics?date_from=2026-09-20&date_to=2026-09-25")
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.headers["cache-control"],"no-store")
        self.assertEqual(counts(),before)
        for path in ["/statistics","/static/js/statistics.js","/static/js/charts.js","/static/css/statistics.css"]:
            self.assertEqual(self.client.get(path).status_code,200)
