"""Google sign-in, invites, owner binding, consent records and the admin CLI. Google is always mocked."""
import contextlib
import io
import json
import os
import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from support import TEMP, create_user, reset_database
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import admin, config
from app.api import auth as auth_api
from app.api.auth import safe_next
from app.auth import google
from app.auth.google import GoogleLoginError, GoogleSettings, Identity, challenge
from app.database import SessionLocal, engine
from app.main import app
from app.models import AuthSession, Consent, Invite, Meal, OAuthAttempt, User, utc_now
from app.services import accounts

ENV = {"GOOGLE_OAUTH_CLIENT_ID": "client-123", "GOOGLE_OAUTH_CLIENT_SECRET": "secret-xyz"}
OWNER = Identity("g-owner", "owner@example.com", "Owner")
FRIEND = Identity("g-friend", "friend@example.com", "Friend")


def count(model, *where) -> int:
    with SessionLocal() as session:
        return session.scalar(select(func.count()).select_from(model).where(*where))


def attempt_for(state: str) -> OAuthAttempt:
    with SessionLocal() as session:
        return session.get(OAuthAttempt, accounts.token_hash(state))


class OAuthFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_database()
        auth_api._hits.clear()
        self.env = patch.dict(os.environ, ENV)
        self.origin = patch.object(config, "PUBLIC_ORIGIN", "https://testserver")
        self.env.start()
        self.origin.start()
        self.client = self.browser()

    def tearDown(self) -> None:
        self.origin.stop()
        self.env.stop()
        engine.dispose()

    def browser(self) -> TestClient:
        # https so Secure cookies round-trip like in a real browser.
        return TestClient(app, base_url="https://testserver")

    def owner_row(self, bound: bool = False) -> int:
        with SessionLocal() as session:
            user = User(email="owner@example.com", role="admin", google_sub="g-owner" if bound else None)
            session.add(user)
            session.commit()
            return user.id

    def invite(self, ttl: timedelta = accounts.INVITE_TTL) -> str:
        if not count(User, User.role == "admin"):
            self.owner_row(bound=True)
        with SessionLocal() as session:
            admin_id = session.scalar(select(User.id).where(User.role == "admin"))
            return accounts.create_invite(session, admin_id, "friend", ttl)

    def start(self, client: TestClient | None = None, **params):
        return (client or self.client).get("/auth/google/start", params=params, follow_redirects=False)

    def state(self, response) -> str:
        self.assertEqual(response.status_code, 303, response.text)
        location = urlsplit(response.headers["location"])
        self.assertEqual(location.netloc, "accounts.google.com", response.headers["location"])
        return parse_qs(location.query)["state"][0]

    def callback(self, state: str, identity: Identity | Exception, client: TestClient | None = None, **params):
        mock = patch.object(google, "fetch_identity", side_effect=identity if isinstance(identity, Exception) else None,
                            return_value=None if isinstance(identity, Exception) else identity)
        with mock as fetch:
            response = (client or self.client).get("/auth/google/callback", params={"state": state, "code": "code-1", **params},
                                                   follow_redirects=False)
        self.fetch = fetch
        return response

    def login_error(self, response) -> str | None:
        self.assertEqual(response.status_code, 303, response.text)
        location = urlsplit(response.headers["location"])
        if location.path != "/login":
            return None
        return parse_qs(location.query)["error"][0]

    def sign_in(self, identity: Identity, client: TestClient | None = None, **start_params):
        response = self.callback(self.state(self.start(client, **start_params)), identity, client)
        self.assertIsNone(self.login_error(response), response.headers["location"])
        return response

    def test_authorization_request_uses_pkce_state_and_nonce(self) -> None:
        response = self.start()
        query = {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}
        record = attempt_for(query["state"])
        self.assertEqual(query["response_type"], "code")
        self.assertEqual(query["client_id"], "client-123")
        self.assertEqual(query["redirect_uri"], "https://testserver/auth/google/callback")
        self.assertEqual(query["scope"], "openid email profile")
        self.assertEqual(query["code_challenge_method"], "S256")
        self.assertEqual(query["code_challenge"], challenge(record.code_verifier))
        self.assertEqual(query["nonce"], record.nonce)
        self.assertNotIn("secret", response.headers["location"])
        self.assertEqual(count(OAuthAttempt, OAuthAttempt.state_hash == query["state"]), 0)
        cookie = response.headers["set-cookie"]
        for part in ["__Host-fitlog_oauth=" + query["state"], "HttpOnly", "Secure", "SameSite=lax", "Max-Age=600"]:
            self.assertIn(part, cookie)

    def test_owner_first_login_binds_google_account_once(self) -> None:
        owner_id = self.owner_row()
        state = self.state(self.start())
        record = attempt_for(state)
        response = self.callback(state, OWNER)
        self.assertEqual(response.headers["location"], "/")
        # Google gets back exactly the PKCE verifier and nonce issued for this attempt.
        self.assertEqual(self.fetch.call_args.args[1:], ("code-1", record.code_verifier, record.nonce))
        self.assertIn("__Host-fitlog_session=", response.headers.get_list("set-cookie")[-1])
        me = self.client.get("/api/me").json()
        self.assertEqual((me["id"], me["role"], me["display_name"]), (owner_id, "admin", "Owner"))
        # A different Google account using the owner's email cannot claim the row again.
        other = self.browser()
        self.assertEqual(self.login_error(self.callback(self.state(self.start(other)), Identity("g-other", "owner@example.com", None), other)), "not_invited")
        self.assertEqual(count(User), 1)
        # The bound sub keeps working after an email change at Google.
        self.sign_in(Identity("g-owner", "renamed@example.com", None), self.browser())
        with SessionLocal() as session:
            self.assertEqual(session.get(User, owner_id).email, "renamed@example.com")

    def test_invite_creates_member_and_records_consents(self) -> None:
        token = self.invite()
        self.sign_in(FRIEND, invite=token, consent_service="true", consent_ai="true")
        me = self.client.get("/api/me").json()
        self.assertEqual((me["email"], me["role"]), ("friend@example.com", "member"))
        with SessionLocal() as session:
            consents = session.execute(select(Consent.kind, Consent.version, Consent.withdrawn_at).where(Consent.user_id == me["id"])).all()
            invite = session.scalar(select(Invite))
        self.assertCountEqual(consents, [("service", accounts.CONSENT_VERSIONS["service"], None), ("ai_transfer", accounts.CONSENT_VERSIONS["ai_transfer"], None)])
        self.assertEqual(invite.used_by, me["id"])
        self.assertIsNotNone(invite.used_at)
        second = self.invite()
        other = self.browser()
        self.sign_in(Identity("g-2", "two@example.com", None), other, invite=second, consent_service="true")
        user_id = other.get("/api/me").json()["id"]
        self.assertEqual(count(Consent, Consent.user_id == user_id, Consent.kind == "ai_transfer"), 0)
        self.assertEqual(count(Consent, Consent.user_id == user_id, Consent.kind == "service"), 1)

    def test_invite_is_single_use_and_expires(self) -> None:
        token = self.invite()
        first, second = self.browser(), self.browser()
        state_one = self.state(self.start(first, invite=token, consent_service="true"))
        state_two = self.state(self.start(second, invite=token, consent_service="true"))
        self.assertIsNone(self.login_error(self.callback(state_one, FRIEND, first)))
        self.assertEqual(self.login_error(self.callback(state_two, Identity("g-3", "three@example.com", None), second)), "invalid_invite")
        self.assertEqual(count(User, User.role == "member"), 1)
        self.assertEqual(self.login_error(self.start(invite=token, consent_service="true")), "invalid_invite")
        expired = self.invite()
        with SessionLocal() as session:
            row = session.scalar(select(Invite).where(Invite.token_hash == accounts.token_hash(expired)))
            row.created_at, row.expires_at = utc_now() - timedelta(days=8), utc_now() - timedelta(seconds=1)
            session.commit()
        self.assertEqual(self.login_error(self.start(invite=expired, consent_service="true")), "invalid_invite")
        self.assertEqual(self.login_error(self.start(invite="not-a-token", consent_service="true")), "invalid_invite")

    def test_invite_requires_service_consent(self) -> None:
        token = self.invite()
        self.assertEqual(self.login_error(self.start(invite=token, consent_ai="true")), "consent_required")
        self.assertEqual(count(OAuthAttempt), 0)

    def test_state_is_bound_to_browser_single_use_and_short_lived(self) -> None:
        self.owner_row()
        state = self.state(self.start())
        # Another browser holding the callback URL has no matching cookie.
        self.assertEqual(self.login_error(self.callback(state, OWNER, self.browser())), "state")
        self.assertIsNone(self.login_error(self.callback(state, OWNER)))
        # Replaying a used state fails even with the cookie restored.
        self.client.cookies.set("__Host-fitlog_oauth", state)
        self.assertEqual(self.login_error(self.callback(state, OWNER)), "state")
        self.state(self.start())
        self.assertEqual(self.login_error(self.callback("wrong-state", OWNER)), "state")
        late = self.state(self.start())
        with SessionLocal() as session:
            session.get(OAuthAttempt, accounts.token_hash(late)).created_at -= accounts.ATTEMPT_TTL
            session.commit()
        self.assertEqual(self.login_error(self.callback(late, OWNER)), "state")
        self.assertEqual(count(AuthSession), 1)

    def test_uninvited_and_disabled_accounts_are_refused(self) -> None:
        self.owner_row(bound=True)
        self.assertEqual(self.login_error(self.callback(self.state(self.start()), FRIEND)), "not_invited")
        self.assertEqual(count(User), 1)
        member = create_user("friend@example.com", "member")
        with SessionLocal() as session:
            user = session.get(User, member.id)
            user.google_sub, user.status = "g-friend", "disabled"
            session.commit()
        self.assertEqual(self.login_error(self.callback(self.state(self.start()), FRIEND)), "disabled")
        self.assertEqual(count(AuthSession), 0)

    def test_existing_member_following_an_invite_keeps_it_unused(self) -> None:
        member = create_user("friend@example.com", "member")
        with SessionLocal() as session:
            session.get(User, member.id).google_sub = "g-friend"
            session.commit()
        token = self.invite()
        self.sign_in(FRIEND, invite=token, consent_service="true")
        self.assertEqual(self.client.get("/api/me").json()["id"], member.id)
        self.assertEqual(count(Invite, Invite.used_at.is_(None)), 1)

    def test_google_failures_are_reported_generically(self) -> None:
        self.owner_row()
        state = self.state(self.start())
        self.assertEqual(self.login_error(self.callback(state, OWNER, error="access_denied")), "cancelled")
        response = self.callback(self.state(self.start()), GoogleLoginError("nonce_mismatch"))
        self.assertEqual(self.login_error(response), "google")
        self.assertNotIn("nonce", response.headers["location"])
        self.assertEqual(count(AuthSession), 0)

    def test_missing_configuration_redirects_to_login(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_OAUTH_CLIENT_SECRET": ""}):
            self.assertEqual(self.login_error(self.start()), "not_configured")
        with patch.object(config, "PUBLIC_ORIGIN", None):
            self.assertEqual(self.login_error(self.start()), "not_configured")
        self.assertEqual(count(OAuthAttempt), 0)

    def test_return_path_is_same_origin_only(self) -> None:
        self.owner_row()
        self.assertEqual(self.sign_in(OWNER, next="/workouts").headers["location"], "/workouts")
        self.assertEqual(self.sign_in(OWNER, self.browser(), next="//evil.example/x").headers["location"], "/")
        for value in ["/workouts?x=1", "/meals"]:
            self.assertEqual(safe_next(value), value)
        for value in [None, "", "https://evil.example", "//evil.example", "/\\evil.example", "/x\r\nSet-Cookie:a", "javascript:alert(1)", "/a:b", "/" + "a" * 300]:
            self.assertIsNone(safe_next(value), value)

    def test_login_endpoints_are_rate_limited(self) -> None:
        for _ in range(auth_api.RATE_LIMIT):
            self.assertNotEqual(self.login_error(self.start()), "rate_limited")
        self.assertEqual(self.login_error(self.start()), "rate_limited")

    def test_login_and_invite_pages(self) -> None:
        for path in ["/login", "/invite/" + "a" * 43]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertIn("default-src 'self'", response.headers["content-security-policy"])
        page = self.client.get("/invite/x").text
        for version in accounts.CONSENT_VERSIONS.values():
            self.assertIn(version, page)
        self.assertIn('name="consent_service" value="true" required', page)
        self.assertNotIn("consent_ai\" value=\"true\" required", page)


class GoogleClientTests(unittest.TestCase):
    settings = GoogleSettings("client-123", "secret-xyz", "https://fitlog.example.com")

    def run_fetch(self, status=200, body=None, claims=None, verify_error=None, transport_error=None):
        from google.auth import exceptions
        transport = MagicMock()
        if transport_error:
            transport.side_effect = exceptions.TransportError("secret detail")
        transport.return_value.status = status
        transport.return_value.data = json.dumps(body if body is not None else {"id_token": "jwt"}).encode()
        claims = claims if claims is not None else {"sub": "g-1", "email": "Friend@Example.com", "email_verified": True, "nonce": "n-1", "name": "F"}
        with patch("google.auth.transport.requests.Request", return_value=transport), \
             patch("google.oauth2.id_token.verify_oauth2_token", side_effect=verify_error, return_value=claims) as verify:
            result = google.fetch_identity(self.settings, "code-1", "verifier-1", "n-1")
        self.transport, self.verify = transport, verify
        return result

    def failure(self, **kwargs) -> str:
        with self.assertRaises(GoogleLoginError) as raised:
            self.run_fetch(**kwargs)
        self.assertNotIn("secret", str(raised.exception))
        return str(raised.exception)

    def test_successful_exchange_verifies_audience_and_sends_pkce(self) -> None:
        self.assertEqual(self.run_fetch(), Identity("g-1", "friend@example.com", "F"))
        self.assertEqual(self.verify.call_args.kwargs["audience"], "client-123")
        body = parse_qs(self.transport.call_args.kwargs["body"])
        self.assertEqual(body["code_verifier"], ["verifier-1"])
        self.assertEqual(body["redirect_uri"], ["https://fitlog.example.com/auth/google/callback"])
        self.assertEqual(self.transport.call_args.args[0], google.TOKEN_URL)
        self.assertEqual(self.transport.call_args.kwargs["timeout"], 10)

    def test_rejections(self) -> None:
        self.assertEqual(self.failure(transport_error=True), "token_unreachable")
        self.assertEqual(self.failure(status=400, body={"error": "invalid_grant"}), "token_rejected")
        self.assertEqual(self.failure(body={}), "id_token_invalid")
        self.assertEqual(self.failure(verify_error=ValueError("Wrong audience")), "id_token_invalid")
        base = {"sub": "g-1", "email": "a@example.com", "email_verified": True, "nonce": "n-1"}
        self.assertEqual(self.failure(claims={**base, "nonce": "other"}), "nonce_mismatch")
        self.assertEqual(self.failure(claims={**base, "nonce": ""}), "nonce_mismatch")
        self.assertEqual(self.failure(claims={**base, "email_verified": "true"}), "email_unverified")
        self.assertEqual(self.failure(claims={**base, "email_verified": False}), "email_unverified")
        self.assertEqual(self.failure(claims={**base, "sub": ""}), "email_unverified")

    def test_settings_from_environment(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            secret = os.path.join(tmp, "secret.txt")
            with open(secret, "w", encoding="utf-8") as f:
                f.write("from-file\n")
            env = {"GOOGLE_OAUTH_CLIENT_ID": " id ", "GOOGLE_OAUTH_CLIENT_SECRET": "", "GOOGLE_OAUTH_CLIENT_SECRET_FILE": secret}
            with patch.dict(os.environ, env), patch.object(config, "PUBLIC_ORIGIN", "https://fitlog.example.com"):
                settings = GoogleSettings.from_env()
        self.assertEqual((settings.client_id, settings.client_secret), ("id", "from-file"))
        self.assertTrue(settings.configured())
        self.assertFalse(GoogleSettings("id", "secret", None).configured())


class OwnerAndAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_database()

    def tearDown(self) -> None:
        engine.dispose()

    def run_admin(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = admin.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_owner_row_is_created_only_without_an_admin(self) -> None:
        with SessionLocal() as session:
            accounts.ensure_owner(session, "")
            self.assertEqual(count(User), 0)
            accounts.ensure_owner(session, " Owner@Example.com ")
            accounts.ensure_owner(session, "someone@example.com")
        with SessionLocal() as session:
            self.assertEqual(session.execute(select(User.email, User.role, User.google_sub)).all(), [("owner@example.com", "admin", None)])

    def test_invite_command_prints_a_working_single_use_link(self) -> None:
        create_user()
        with patch.object(config, "PUBLIC_ORIGIN", "https://fitlog.example.com"):
            code, out, err = self.run_admin("invite", "--note", "민수", "--days", "3")
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("https://fitlog.example.com/invite/"))
        token = out.strip().rsplit("/", 1)[1]
        with SessionLocal() as session:
            invite = accounts.usable_invite(session, token)
            self.assertIsNotNone(invite)
            self.assertEqual(invite.note, "민수")
            self.assertAlmostEqual((invite.expires_at - invite.created_at).total_seconds(), 3 * 86400, delta=1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Invite).where(Invite.token_hash == token)), 0)

    def test_invite_needs_exactly_one_admin_or_by(self) -> None:
        self.assertEqual(self.run_admin("invite")[0], 2)
        create_user("a@example.com")
        create_user("b@example.com")
        self.assertEqual(self.run_admin("invite")[0], 2)
        self.assertEqual(self.run_admin("invite", "--by", "b@example.com")[0], 0)

    def test_users_disable_enable(self) -> None:
        create_user()
        member = create_user("friend@example.com", "member")
        with SessionLocal() as session:
            accounts.create_session(session, member.id)
        code, out, _ = self.run_admin("users")
        self.assertEqual(code, 0)
        self.assertIn("friend@example.com\tmember\tactive\tlinked", out)
        self.assertEqual(self.run_admin("disable", "friend@example.com")[0], 0)
        self.assertEqual(count(AuthSession), 0)
        self.assertEqual(count(User, User.status == "disabled"), 1)
        self.assertEqual(self.run_admin("enable", "Friend@Example.com")[0], 0)
        self.assertEqual(self.run_admin("disable", "owner@example.com")[0], 2)
        self.assertEqual(self.run_admin("disable", "nobody@example.com")[0], 1)

    def test_delete_user_removes_everything_they_own(self) -> None:
        from app.schemas import MealInput
        from app.services.records import save_meal
        owner = create_user()
        member = create_user("friend@example.com", "member")
        with SessionLocal() as session:
            for user in (owner, member):
                save_meal(session, user.id, MealInput(name="점심", eaten_at="2026-09-25T12:00:00+09:00", meal_type="lunch"))
            accounts.create_session(session, member.id)
            session.add(Consent(user_id=member.id, kind="service", version="1"))
            session.commit()
        self.assertEqual(self.run_admin("delete-user", "friend@example.com")[0], 2)
        self.assertEqual(count(User), 2)
        code, out, _ = self.run_admin("delete-user", "friend@example.com", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("meals 1", out)
        self.assertEqual(count(User), 1)
        self.assertEqual(count(Meal), 1)
        self.assertEqual((count(AuthSession), count(Consent)), (0, 0))
        self.assertEqual(self.run_admin("delete-user", "owner@example.com", "--yes")[0], 1)
        self.assertEqual(count(Meal, Meal.user_id == owner.id), 1)


if __name__ == "__main__":
    unittest.main()
