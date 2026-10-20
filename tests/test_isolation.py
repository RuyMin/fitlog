"""Two users on one database: neither can see, change or reference the other's data."""
import re
import unittest

from support import TEMP, act_as, create_user, fresh_owner
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import Meal, Workout
from app.services.sync_service import apply_rows, parse_tables
from test_excel_import import MIME, content, workbook
from test_phase5 import fixture

DAY = "2026-09-25"
MEAL = {"name": "점심", "eaten_at": "2026-09-25T12:00:00+09:00", "meal_type": "lunch", "protein": 30}
BODY = {"measured_at": "2026-09-25T08:00:00+09:00", "weight": 70}
SLEEP = {"sleep_start": "2026-09-24T23:00:00+09:00", "sleep_end": "2026-09-25T06:00:00+09:00", "sleep_type": "main"}
PUBLIC_API = {"/api/health"}


class IsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        self.owner = fresh_owner()
        self.member = create_user("member@example.com", "member")

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.__exit__(None, None, None)

    def create(self, path: str, body: dict) -> dict:
        response = self.client.post("/api/" + path, json=body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def seed_owner(self) -> dict:
        act_as(self.owner)
        items = {path: self.create(path, body) for path, body in
                 [("meals", MEAL), ("body-metrics", BODY), ("sleep", SLEEP), ("exercises", {"name": "Squat"}),
                  ("workouts", {"workout_date": DAY, "title": "하체"})]}
        items["set"] = self.create(f"workouts/{items['workouts']['id']}/sets",
                                   {"exercise_id": items["exercises"]["id"], "set_number": 1, "weight": 60, "reps": 8, "completed": True})
        items["workouts"] = self.client.get(f"/api/workouts/{items['workouts']['id']}").json()
        return items

    def test_other_users_records_are_invisible_and_immutable(self) -> None:
        items = self.seed_owner()
        bodies = {"meals": MEAL, "body-metrics": BODY, "sleep": SLEEP, "exercises": {"name": "Hack"},
                  "workouts": {"workout_date": DAY, "title": "탈취"}}
        act_as(self.member)
        for path, body in bodies.items():
            with self.subTest(path=path):
                self.assertEqual(self.client.get("/api/" + path).json(), [])
                item = f"/api/{path}/{items[path]['id']}"
                self.assertEqual(self.client.get(item).status_code, 404)
                self.assertEqual(self.client.put(item, json=body).status_code, 404)
                self.assertEqual(self.client.delete(item).status_code, 404)
        sets = f"/api/workouts/{items['workouts']['id']}/sets"
        set_body = {"exercise_id": items["exercises"]["id"], "set_number": 2}
        self.assertEqual(self.client.get(sets).status_code, 404)
        self.assertEqual(self.client.post(sets, json=set_body).status_code, 404)
        self.assertEqual(self.client.get(f"{sets}/{items['set']['id']}").status_code, 404)
        self.assertEqual(self.client.put(f"{sets}/{items['set']['id']}", json=set_body).status_code, 404)
        self.assertEqual(self.client.delete(f"{sets}/{items['set']['id']}").status_code, 404)
        act_as(self.owner)
        for path in bodies:
            self.assertEqual(self.client.get(f"/api/{path}/{items[path]['id']}").json(), items[path], path)
        self.assertEqual(len(self.client.get(sets).json()), 1)

    def test_own_workout_cannot_use_another_users_exercise(self) -> None:
        items = self.seed_owner()
        act_as(self.member)
        workout = self.create("workouts", {"workout_date": DAY, "title": "내 운동"})
        response = self.client.post(f"/api/workouts/{workout['id']}/sets", json={"exercise_id": items["exercises"]["id"], "set_number": 1})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(f"/api/workouts/{workout['id']}/sets").json(), [])

    def test_dashboard_and_statistics_exclude_other_users(self) -> None:
        self.seed_owner()
        act_as(self.member)
        dashboard = self.client.get(f"/api/dashboard?date={DAY}").json()
        self.assertEqual((dashboard["workouts_count"], dashboard["total_sets"], dashboard["meals_count"]), (0, 0, 0))
        self.assertIsNone(dashboard["latest_weight"])
        self.assertIsNone(dashboard["sleep_minutes"])
        summary = self.client.get(f"/api/statistics?date_from={DAY}&date_to={DAY}").json()["summary"]
        self.assertEqual((summary["workouts_count"], summary["sets_count"], summary["weight_days"], summary["sleep_days"]), (0, 0, 0, 0))
        act_as(self.owner)
        summary = self.client.get(f"/api/statistics?date_from={DAY}&date_to={DAY}").json()["summary"]
        self.assertEqual((summary["workouts_count"], summary["sets_count"], summary["weight_days"], summary["sleep_days"]), (1, 1, 1, 1))

    def test_names_and_sleep_times_are_per_user(self) -> None:
        self.seed_owner()
        act_as(self.member)
        self.create("exercises", {"name": "Squat"})
        self.create("sleep", SLEEP)
        self.assertEqual(self.client.post("/api/exercises", json={"name": "Squat"}).status_code, 409)
        self.assertEqual(self.client.post("/api/sleep", json=SLEEP).status_code, 409)

    def test_sync_rows_with_same_external_ids_stay_separate(self) -> None:
        rows = parse_tables(fixture())
        with SessionLocal() as session:
            first = apply_rows(session, self.owner.id, rows)
            second = apply_rows(session, self.member.id, rows)
            session.commit()
        self.assertTrue(all(first[k]["inserted"] == 1 and second[k]["inserted"] == 1 for k in first))
        with SessionLocal() as session:
            counts = dict(session.execute(select(Workout.user_id, func.count()).group_by(Workout.user_id)).all())
        self.assertEqual(counts, {self.owner.id: 1, self.member.id: 1})

    def test_excel_previews_and_archives_are_private(self) -> None:
        from app.models import ImportArchive
        original = content(workbook())

        def upload() -> dict:
            response = self.client.post("/api/sync/excel/preview?filename=records.xlsx", content=original, headers={"content-type": MIME})
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        def commit(preview: dict):
            selected = [e["key"] for e in preview["entries"] if e["status"] in {"new", "updated"}]
            return self.client.post(f"/api/sync/excel/{preview['token']}/commit", json={"selected": selected})

        act_as(self.owner)
        mine = upload()
        act_as(self.member)
        self.assertEqual(commit(mine).status_code, 404)
        self.client.delete("/api/sync/excel/" + mine["token"])
        theirs = upload()
        self.assertEqual(theirs["counts"], {"new": 4})
        self.assertEqual(commit(theirs).status_code, 200)
        act_as(self.owner)
        # Another user's commit neither consumed nor staled this preview.
        saved = commit(mine)
        self.assertEqual(saved.status_code, 200, saved.text)
        archive = saved.json()["archive_id"]
        self.assertEqual(len(self.client.get("/api/sync/excel/history").json()), 1)
        act_as(self.member)
        self.assertEqual(len(self.client.get("/api/sync/excel/history").json()), 1)
        with SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Meal)), 2)
            # The same file is archived once per user, each owned by its uploader.
            owners = session.scalars(select(ImportArchive.user_id).order_by(ImportArchive.id)).all()
            self.assertEqual(sorted(owners), sorted([self.owner.id, self.member.id]))
            self.assertEqual(session.get(ImportArchive, archive).user_id, self.owner.id)

    def test_google_sync_is_admin_only(self) -> None:
        act_as(self.member)
        self.assertEqual(self.client.get("/api/sync/status").status_code, 403)
        self.assertEqual(self.client.post("/api/sync/google", json={}).status_code, 403)

    def test_every_private_route_requires_a_user(self) -> None:
        """Guard: a new router without the user dependency fails here."""
        app.dependency_overrides.clear()
        checked = 0
        for route in app.routes:
            if not isinstance(route, APIRoute) or not route.path.startswith("/api/") or route.path in PUBLIC_API:
                continue
            path = re.sub(r"\{\w+\}", "1", route.path)
            for method in route.methods:
                with self.subTest(method=method, path=route.path):
                    self.assertEqual(self.client.request(method, path, json={}).status_code, 401)
                    checked += 1
        self.assertGreater(checked, 30)
        self.assertEqual(self.client.get("/api/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
