"""첫 실행: 무엇을 기록할까요? (users.tracking) and the first-record checklist's data."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from support import act_as, create_user, fresh_owner
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.database import Base
from app.main import app
from app.migrations import SCHEMA_VERSION, migrate

NOW = datetime.now(timezone.utc).isoformat()


class TrackingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        self.user = fresh_owner()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def me(self) -> dict:
        return self.client.get("/api/me").json()

    def test_a_new_account_is_sent_to_the_first_run_screen(self) -> None:
        me = self.me()
        self.assertIsNone(me["tracking"])
        self.assertTrue(me["needs_setup"])

    def test_an_account_with_records_skips_it(self) -> None:
        # Accounts from before this screen existed keep their home as it was.
        self.assertEqual(self.client.post("/api/body-metrics", json={"measured_at": NOW, "weight": 70}).status_code, 201)
        me = self.me()
        self.assertIsNone(me["tracking"])
        self.assertFalse(me["needs_setup"])

    def test_choice_is_saved_in_a_fixed_order_without_repeats(self) -> None:
        response = self.client.put("/api/me/tracking", json={"tracking": ["sleep", "work", "sleep"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["tracking"], ["work", "sleep"])
        self.assertEqual(self.me()["tracking"], ["work", "sleep"])
        self.assertFalse(self.me()["needs_setup"])

    def test_at_least_one_known_kind(self) -> None:
        for body in ({"tracking": []}, {"tracking": ["steps"]}, {}, {"tracking": ["work"], "extra": 1}):
            self.assertEqual(self.client.put("/api/me/tracking", json=body).status_code, 422, body)
        self.assertIsNone(self.me()["tracking"])

    def test_choice_is_per_account(self) -> None:
        self.client.put("/api/me/tracking", json={"tracking": ["meal"]})
        act_as(create_user("other@example.com", "member"))
        self.assertIsNone(self.me()["tracking"])
        act_as(self.user)
        self.assertEqual(self.me()["tracking"], ["meal"])

    def test_dashboard_tells_an_empty_home(self) -> None:
        dashboard = lambda: self.client.get("/api/dashboard?timezone=UTC").json()
        self.assertFalse(dashboard()["has_records"])
        self.assertEqual(dashboard()["goal_source"], "default")  # the checklist's 목표 정하기 is still open
        sleep = {"sleep_start": "2026-10-01T14:00:00Z", "sleep_end": "2026-10-01T21:00:00Z"}
        self.assertEqual(self.client.post("/api/sleep", json=sleep).status_code, 201)
        # A record on any day, not only today, ends the checklist.
        self.assertTrue(dashboard()["has_records"])

    def test_first_run_page_is_served(self) -> None:
        response = self.client.get("/welcome")
        self.assertEqual(response.status_code, 200)
        self.assertIn("무엇을<br>기록할까요?", response.text)
        self.assertIn('href="/settings#excel-heading"', response.text)
        home = self.client.get("/").text
        for piece in ('id="first-day"', "기록할 것 고르기", "오늘 한 운동 적기", "목표 정하기", 'class="first-chips"'):
            self.assertIn(piece, home)


class MigrationV14Tests(unittest.TestCase):
    def test_existing_users_get_an_empty_choice_after_a_backup(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fitlog.db"
            engine = create_engine("sqlite:///" + path.as_posix())
            try:
                Base.metadata.create_all(engine)
                with engine.begin() as c:
                    c.exec_driver_sql("ALTER TABLE users DROP COLUMN tracking")
                    c.exec_driver_sql("INSERT INTO users (email, role, status, created_at, google_sub) VALUES ('a@example.com', 'member', 'active', '2026-10-01', 'sub-a')")
                    c.exec_driver_sql("PRAGMA user_version=13")
                migrate(engine, path)
            finally:
                engine.dispose()
            self.assertEqual(SCHEMA_VERSION, 14)
            with closing(sqlite3.connect(path)) as c:
                self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 14)
                self.assertEqual(c.execute("SELECT email, tracking FROM users").fetchall(), [("a@example.com", None)])
            backups = list((Path(folder) / "backups").glob("before-v14-*.db"))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as c:
                self.assertNotIn("tracking", {r[1] for r in c.execute("PRAGMA table_info(users)")})


if __name__ == "__main__":
    unittest.main()
