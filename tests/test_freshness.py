"""Coming back to the app reloads only when records changed outside this session (app/services/freshness.py)."""
import unittest

from support import fresh_owner
from fastapi.testclient import TestClient

from app.main import app
from test_auth import MEAL, login


class FreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.phone, self.laptop = TestClient(app), TestClient(app)
        self.phone.__enter__(); self.laptop.__enter__()
        self.user = fresh_owner()
        app.dependency_overrides.clear()  # the real cookie session: each client is its own device
        login(self.phone, self.user); login(self.laptop, self.user)

    def tearDown(self) -> None:
        self.phone.__exit__(None, None, None); self.laptop.__exit__(None, None, None)

    def changed(self, client: TestClient) -> bool:
        return client.get("/api/me/changed").json()["changed"]

    def test_only_edits_from_elsewhere_count(self) -> None:
        self.assertTrue(self.changed(self.phone))  # a session never asked before loads once
        self.assertFalse(self.changed(self.phone))  # nothing happened since: no reload
        self.assertEqual(self.phone.post("/api/meals", json=MEAL).status_code, 201)
        self.assertFalse(self.changed(self.phone))  # its own edit
        self.assertTrue(self.changed(self.laptop))
        self.assertEqual(self.laptop.post("/api/meals", json=MEAL).status_code, 201)
        self.assertTrue(self.changed(self.phone))  # the laptop's edit
        self.assertFalse(self.changed(self.phone))

    def test_failed_writes_and_speed_reports_do_not_count(self) -> None:
        self.changed(self.phone)
        self.assertEqual(self.laptop.post("/api/meals", json={"name": ""}).status_code, 422)
        self.assertEqual(self.laptop.post("/api/metrics", json=[]).status_code, 202)
        self.assertFalse(self.changed(self.phone))

    def test_signed_out_gets_an_error(self) -> None:
        self.assertEqual(TestClient(app).get("/api/me/changed").status_code, 401)


if __name__ == "__main__":
    unittest.main()
