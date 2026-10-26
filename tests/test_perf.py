import unittest
from datetime import datetime, timedelta, timezone

from support import TEMP, act_as, create_user, fresh_owner  # noqa: F401 — isolate FITLOG_DATA_DIR before app imports
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import PerfEvent
from app.services import perf


def now_iso(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


class PerfStatsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        self.owner = fresh_owner()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def events(self, **where):
        with SessionLocal() as session:
            return session.scalars(select(PerfEvent).filter_by(**where).order_by(PerfEvent.id)).all()

    def test_api_requests_are_timed_with_route_templates(self) -> None:
        workout = self.client.post("/api/workouts", json={"workout_date": "2026-10-26", "title": "하체"}).json()
        response = self.client.get(f"/api/workouts/{workout['id']}?x=secret")
        self.assertRegex(response.headers["server-timing"], r"^app;dur=\d+(\.\d)?$")
        routes = [(e.method, e.route, e.status) for e in self.events(source="server")]
        self.assertIn(("GET", "/api/workouts/{workout_id}", 200), routes)
        self.assertFalse(any("secret" in route or str(workout["id"]) in route for _, route, _ in routes))
        self.assertEqual(self.client.get("/static/css/app.css").headers.get("server-timing"), None)

    def test_phone_reports_are_stored_but_not_timed_themselves(self) -> None:
        sent = self.client.post("/api/metrics", json=[
            {"kind": "client", "at": now_iso(), "page": "/workouts", "route": "/api/workouts/12/sets/40", "method": "PUT",
             "status": 200, "total_ms": 640, "server_ms": 4.2},
            {"kind": "page", "at": now_iso(), "page": "/", "route": "/", "total_ms": 700, "html_ms": 5, "cached": True},
            {"kind": "client", "at": now_iso(days=-30), "route": "/api/me", "total_ms": 10},
        ])
        self.assertEqual(sent.status_code, 202, sent.text)
        stored = self.events(source="client")
        self.assertEqual([(e.route, e.total_ms, e.server_ms, e.user_id) for e in stored], [("/api/workouts/{id}/sets/{id}", 640, 4.2, self.owner.id)])
        self.assertEqual(len(self.events(source="page")), 1)
        self.assertFalse(any(e.route == "/api/metrics" for e in self.events()))
        bad = self.client.post("/api/metrics", json=[{"kind": "server", "at": now_iso(), "route": "/api/x", "total_ms": 1}])
        self.assertEqual(bad.status_code, 422)

    def test_summary_splits_phone_server_and_network(self) -> None:
        self.client.post("/api/metrics", json=[
            {"kind": "client", "at": now_iso(), "route": "/api/dashboard", "method": "GET", "status": 200, "total_ms": ms, "server_ms": 5}
            for ms in (600, 650, 700)] + [{"kind": "client", "at": now_iso(), "route": "/api/dashboard", "method": "GET", "status": 0, "total_ms": 9000}])
        for _ in range(3):
            self.client.get("/api/dashboard")
        data = self.client.get("/api/admin/perf?days=1").json()
        dashboard = next(r for r in data["routes"] if r["route"] == "/api/dashboard")
        self.assertEqual(dashboard["client"]["count"], 4)
        self.assertEqual(dashboard["server"]["count"], 3)
        self.assertEqual(dashboard["errors"], 1)
        self.assertGreater(dashboard["network_p50"], 500)
        self.assertIn(self.owner.email, [u["email"] for u in data["users"]])

    def test_members_report_but_only_admins_read(self) -> None:
        act_as(create_user("friend@example.com", "member"))
        self.assertEqual(self.client.post("/api/metrics", json=[{"kind": "page", "at": now_iso(), "route": "/", "total_ms": 1}]).status_code, 202)
        self.assertEqual(self.client.get("/api/admin/perf").status_code, 403)

    def test_old_rows_are_purged(self) -> None:
        with SessionLocal() as session:
            session.add(PerfEvent(at=perf.utc_now() - timedelta(days=20), source="server", route="/api/old", total_ms=1))
            session.commit()
        self.client.post("/api/metrics", json=[{"kind": "page", "at": now_iso(), "route": "/", "total_ms": 1}])
        self.assertEqual([e.route for e in self.events() if e.route == "/api/old"], [])


if __name__ == "__main__":
    unittest.main()
