import unittest
from datetime import timedelta

from support import act_as, create_user, fresh_owner
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Invite, utc_now
from app.services import accounts


class InviteApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        self.admin = fresh_owner()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def test_admin_makes_a_working_single_use_link(self) -> None:
        response = self.client.post("/api/admin/invites", json={"note": "민수", "days": 3})
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        self.assertEqual((data["note"], data["status"], data["used_by"]), ("민수", "pending", None))
        token = data["url"].rsplit("/invite/", 1)[1]
        with SessionLocal() as session:
            invite = accounts.usable_invite(session, token)
            self.assertIsNotNone(invite)
            self.assertAlmostEqual((invite.expires_at - invite.created_at).total_seconds(), 3 * 86400, delta=1)
            # Only the hash is stored, so the list can never show the link again.
            self.assertNotIn(token, invite.token_hash)
        self.assertEqual(self.client.get("/invite/" + token).status_code, 200)
        listed = self.client.get("/api/admin/invites").json()
        self.assertEqual([(item["note"], item["status"]) for item in listed], [("민수", "pending")])
        self.assertNotIn("url", listed[0])

    def test_list_shows_used_and_expired(self) -> None:
        member = create_user("friend@example.com", "member")
        with SessionLocal() as session:
            now = utc_now()
            session.add_all([
                Invite(token_hash="a" * 64, created_by=self.admin.id, note="used", created_at=now - timedelta(days=2),
                       expires_at=now + timedelta(days=5), used_at=now - timedelta(days=1), used_by=member.id),
                Invite(token_hash="b" * 64, created_by=self.admin.id, note="old", created_at=now - timedelta(days=9),
                       expires_at=now - timedelta(days=2)),
            ])
            session.commit()
        listed = {item["note"]: item for item in self.client.get("/api/admin/invites").json()}
        self.assertEqual((listed["used"]["status"], listed["used"]["used_by"]), ("used", "friend@example.com"))
        self.assertEqual(listed["old"]["status"], "expired")
        self.assertTrue(listed["used"]["created_at"].endswith("+00:00"))

    def test_revoke_only_unused_links(self) -> None:
        pending = self.client.post("/api/admin/invites", json={}).json()
        token = pending["url"].rsplit("/invite/", 1)[1]
        self.assertEqual(self.client.delete(f"/api/admin/invites/{pending['id']}").status_code, 204)
        with SessionLocal() as session:
            self.assertIsNone(accounts.usable_invite(session, token))
        self.assertEqual(self.client.delete(f"/api/admin/invites/{pending['id']}").status_code, 404)
        member = create_user("friend@example.com", "member")
        with SessionLocal() as session:
            now = utc_now()
            used = Invite(token_hash="c" * 64, created_by=self.admin.id, created_at=now, expires_at=now + timedelta(days=1),
                          used_at=now, used_by=member.id)
            session.add(used)
            session.commit()
            used_id = used.id
        self.assertEqual(self.client.delete(f"/api/admin/invites/{used_id}").status_code, 409)
        with SessionLocal() as session:
            self.assertIsNotNone(session.scalar(select(Invite).where(Invite.id == used_id)))

    def test_input_is_checked(self) -> None:
        for body in [{"days": 0}, {"days": 31}, {"days": "7"}, {"note": ""}, {"note": "x" * 101}, {"extra": 1}]:
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/api/admin/invites", json=body).status_code, 422)

    def test_members_cannot_invite(self) -> None:
        act_as(create_user("friend@example.com", "member"))
        self.assertEqual(self.client.post("/api/admin/invites", json={}).status_code, 403)
        self.assertEqual(self.client.get("/api/admin/invites").status_code, 403)
        self.assertEqual(self.client.delete("/api/admin/invites/1").status_code, 403)


if __name__ == "__main__":
    unittest.main()
