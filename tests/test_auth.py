"""Cookie sessions, the real current_user dependency and the request security policy."""
import hashlib
import re
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from support import TEMP, create_user, fresh_owner
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import config
from app.api.deps import cookie_name, set_session_cookie
from app.database import SessionLocal
from app.main import app
from app.models import AuthSession, Consent, Meal, User, utc_now
from app.services import accounts
from app.services.accounts import ABSOLUTE, IDLE, create_session, resolve_session

MEAL = {"name": "점심", "eaten_at": "2026-09-25T12:00:00+09:00", "meal_type": "lunch"}
SLEEP = {"sleep_start": "2026-09-24T23:00:00+09:00", "sleep_end": "2026-09-25T06:00:00+09:00"}


def login(client: TestClient, user: User) -> str:
    with SessionLocal() as session:
        token, _ = create_session(session, user.id)
    client.cookies.set(cookie_name(), token)
    return token


def stored(token: str) -> AuthSession | None:
    with SessionLocal() as session:
        return session.scalar(select(AuthSession).where(AuthSession.token_hash == hashlib.sha256(token.encode()).hexdigest()))


class SessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        self.user = fresh_owner()
        app.dependency_overrides.clear()  # exercise the real cookie lookup

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def test_cookie_session_authenticates_requests(self) -> None:
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        login(self.client, self.user)
        self.assertEqual(self.client.get("/api/me").json(),
                         {"id": self.user.id, "email": "owner@example.com", "display_name": None, "role": "admin"})
        # Sleep reserves the writer with BEGIN IMMEDIATE on the request session the lookup already used.
        self.assertEqual(self.client.post("/api/sleep", json=SLEEP).status_code, 201)
        self.assertEqual(self.client.post("/api/meals", json=MEAL).status_code, 201)
        self.assertEqual(len(self.client.get("/api/meals").json()), 1)

    def test_only_token_hash_is_stored(self) -> None:
        token = login(self.client, self.user)
        record = stored(token)
        self.assertIsNotNone(record)
        self.assertNotEqual(record.token_hash, token)
        with SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.token_hash == token)), 0)

    def test_unknown_expired_and_disabled_sessions_are_rejected(self) -> None:
        self.client.cookies.set(cookie_name(), "not-a-real-token")
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.client.cookies.set(cookie_name(), "x" * 500)
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        token = login(self.client, self.user)
        with SessionLocal() as session:
            record = session.scalar(select(AuthSession).where(AuthSession.user_id == self.user.id))
            record.created_at, record.expires_at = utc_now() - timedelta(days=31), utc_now() - timedelta(seconds=1)
            session.commit()
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        login(self.client, self.user)
        self.assertEqual(self.client.get("/api/me").status_code, 200)
        with SessionLocal() as session:
            session.get(User, self.user.id).status = "disabled"
            session.commit()
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.assertIsNone(stored(token))  # the expired session was purged by the second login

    def test_idle_renewal_never_passes_absolute_limit(self) -> None:
        token = login(self.client, self.user)
        now = utc_now()
        with SessionLocal() as session:
            record = session.scalar(select(AuthSession).where(AuthSession.token_hash == stored(token).token_hash))
            record.created_at, record.last_seen_at, record.expires_at = now - timedelta(days=10), now - timedelta(days=2), now + timedelta(days=28)
            session.commit()
            self.assertIsNotNone(resolve_session(session, token))
            session.refresh(record)
            self.assertAlmostEqual((record.expires_at - now).total_seconds(), IDLE.total_seconds(), delta=60)
            record.created_at, record.last_seen_at = now - timedelta(days=89), now - timedelta(days=2)
            session.commit()
            resolve_session(session, token)
            session.refresh(record)
            self.assertEqual(record.expires_at, record.created_at + ABSOLUTE)
            # Within a day of the last renewal the row is not rewritten.
            seen = record.last_seen_at
            resolve_session(session, token)
            session.refresh(record)
            self.assertEqual(record.last_seen_at, seen)

    def test_new_session_purges_expired_rows(self) -> None:
        token = login(self.client, self.user)
        with SessionLocal() as session:
            record = session.scalar(select(AuthSession).where(AuthSession.token_hash == stored(token).token_hash))
            record.created_at, record.expires_at = utc_now() - timedelta(days=31), utc_now() - timedelta(seconds=1)
            session.commit()
        login(self.client, self.user)
        self.assertIsNone(stored(token))

    def test_logout_ends_session_and_clears_cookie(self) -> None:
        token = login(self.client, self.user)
        other = TestClient(app)
        login(other, self.user)
        response = self.client.post("/auth/logout")
        self.assertEqual(response.json(), {"status": "logged_out"})
        cookie = response.headers["set-cookie"]
        self.assertIn(cookie_name() + "=", cookie)
        self.assertIn("Max-Age=0", cookie)
        self.assertIsNone(stored(token))
        self.client.cookies.set(cookie_name(), token)
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        # Another device keeps its own session.
        self.assertEqual(other.get("/api/me").status_code, 200)
        self.assertEqual(self.client.post("/auth/logout").status_code, 200)

    def test_cookie_attributes(self) -> None:
        response = Response()
        set_session_cookie(response, "token")
        cookie = response.headers["set-cookie"]
        for part in ["__Host-fitlog_session=token", "HttpOnly", "Secure", "SameSite=lax", "Path=/", f"Max-Age={int(ABSOLUTE.total_seconds())}"]:
            self.assertIn(part, cookie)
        self.assertNotIn("Domain", cookie)
        with patch.object(config, "INSECURE_COOKIES", True):
            response = Response()
            set_session_cookie(response, "token")
            self.assertTrue(response.headers["set-cookie"].startswith("fitlog_session=token"))
            self.assertNotIn("Secure", response.headers["set-cookie"])

    def test_consent_status_grant_and_withdraw(self) -> None:
        member = create_user("member@example.com", "member")
        with SessionLocal() as session:
            session.add(Consent(user_id=member.id, kind="service", version=accounts.CONSENT_VERSION))
            session.add(Consent(user_id=member.id, kind="ai_transfer", version="2025-01-01", granted_at=utc_now() - timedelta(days=1)))
            session.commit()
        login(self.client, member)
        data = self.client.get("/api/me/consents").json()
        self.assertEqual(data["current_version"], accounts.CONSENT_VERSION)
        self.assertTrue(data["service"]["active"])
        self.assertTrue(data["service"]["granted_at"].endswith("+00:00"))
        # Agreement to an older notice is not consent to the current one.
        self.assertFalse(data["ai_transfer"]["active"])
        granted = self.client.post("/api/me/consents/ai_transfer").json()["ai_transfer"]
        self.assertEqual((granted["version"], granted["active"]), (accounts.CONSENT_VERSION, True))
        self.client.post("/api/me/consents/ai_transfer")
        self.assertEqual(self.ai_rows(member.id), 2)
        withdrawn = self.client.delete("/api/me/consents/ai_transfer").json()["ai_transfer"]
        self.assertFalse(withdrawn["active"])
        self.assertIsNotNone(withdrawn["withdrawn_at"])
        with SessionLocal() as session:
            self.assertFalse(accounts.has_ai_consent(session, member.id))
            self.assertEqual(session.scalar(select(func.count()).select_from(Consent).where(
                Consent.user_id == member.id, Consent.withdrawn_at.is_(None))), 1)  # the service consent
        # Consents are per user.
        login(self.client, self.user)
        self.assertEqual(self.client.get("/api/me/consents").json()["ai_transfer"], None)

    def ai_rows(self, user_id: int) -> int:
        with SessionLocal() as session:
            return session.scalar(select(func.count()).select_from(Consent).where(Consent.user_id == user_id, Consent.kind == "ai_transfer"))

    def test_pages_wire_login_redirect_and_admin_only_sync(self) -> None:
        static = Path(__file__).resolve().parents[1] / "app" / "static"
        app_js = (static / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn('location.replace("/login?next="', app_js)
        for page in ["index.html", "records.html", "settings.html", "statistics.html", "workouts.html"]:
            scripts = re.findall(r'<script[^>]*src="([^"]+)"', (static / page).read_text(encoding="utf-8"))
            self.assertEqual(scripts[0], "/static/js/app.js", page)
        settings = (static / "settings.html").read_text(encoding="utf-8")
        self.assertIn('id="sync-card" hidden', settings)
        self.assertIn(accounts.CONSENT_VERSION, settings)

    def test_member_session_cannot_use_admin_routes(self) -> None:
        login(self.client, create_user("member@example.com", "member"))
        self.assertEqual(self.client.get("/api/me").json()["role"], "member")
        self.assertEqual(self.client.get("/api/sync/status").status_code, 403)


class SecurityPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        fresh_owner()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.__exit__(None, None, None)

    def meals(self) -> int:
        with SessionLocal() as session:
            return session.scalar(select(func.count()).select_from(Meal))

    def test_cross_origin_writes_are_rejected(self) -> None:
        for headers in [{"sec-fetch-site": "cross-site"}, {"sec-fetch-site": "same-site"},
                        {"origin": "https://evil.example"}, {"origin": "null"}, {"origin": "http://testserver.evil.example"}]:
            with self.subTest(headers=headers):
                response = self.client.post("/api/meals", json=MEAL, headers=headers)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(self.client.put("/api/meals/1", json=MEAL, headers={"origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.delete("/api/meals/1", headers={"sec-fetch-site": "cross-site"}).status_code, 403)
        self.assertEqual(self.client.post("/auth/logout", headers={"sec-fetch-site": "cross-site"}).status_code, 403)
        self.assertEqual(self.meals(), 0)

    def test_same_origin_writes_and_any_reads_are_allowed(self) -> None:
        for headers in [{}, {"origin": "http://testserver"}, {"sec-fetch-site": "same-origin", "origin": "http://TestServer"}, {"sec-fetch-site": "none"}]:
            with self.subTest(headers=headers):
                self.assertEqual(self.client.post("/api/meals", json=MEAL, headers=headers).status_code, 201)
        self.assertEqual(self.client.get("/api/meals", headers={"sec-fetch-site": "cross-site"}).status_code, 200)

    def test_configured_public_origin_wins_over_host_header(self) -> None:
        with patch.object(config, "PUBLIC_ORIGIN", "https://fitlog.example.com"):
            self.assertEqual(self.client.post("/api/meals", json=MEAL, headers={"origin": "http://testserver"}).status_code, 403)
            self.assertEqual(self.client.post("/api/meals", json=MEAL, headers={"origin": "https://fitlog.example.com"}).status_code, 201)

    def test_security_headers_on_pages_and_api(self) -> None:
        for path in ["/", "/workouts", "/api/health", "/static/js/app.js"]:
            with self.subTest(path=path):
                headers = self.client.get(path).headers
                self.assertIn("default-src 'self'", headers["content-security-policy"])
                self.assertIn("frame-ancestors 'none'", headers["content-security-policy"])
                self.assertEqual(headers["x-content-type-options"], "nosniff")
                self.assertEqual(headers["referrer-policy"], "same-origin")
        self.assertEqual(self.client.get("/api/health").headers["cache-control"], "no-store")

    def test_pages_have_no_inline_styles_or_scripts(self) -> None:
        """The CSP forbids them; keep markup and scripts compatible."""
        import re
        from pathlib import Path
        static = Path(app.routes[-1].app.directory)
        for file in [*static.glob("*.html"), *static.glob("js/*.js")]:
            text = file.read_text(encoding="utf-8")
            with self.subTest(file=file.name):
                self.assertNotRegex(text, r"style=|cssText|<script(?![^>]*\bsrc=)|\son[a-z]+=\"")
                self.assertIsNone(re.search(r"https?://(?!127\.0\.0\.1)", text) if file.suffix == ".html" else None)

    def test_public_url_validation(self) -> None:
        self.assertIsNone(config.public_origin(""))
        self.assertEqual(config.public_origin("https://FitLog.example.com/"), "https://fitlog.example.com")
        self.assertEqual(config.public_origin("http://localhost:51881"), "http://localhost:51881")
        for bad in ["http://fitlog.example.com", "https://fitlog.example.com/app", "ftp://x.example", "https://", "fitlog.example.com"]:
            with self.subTest(value=bad), self.assertRaises(ValueError):
                config.public_origin(bad)


if __name__ == "__main__":
    unittest.main()
