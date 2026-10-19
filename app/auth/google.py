"""Google sign-in (OpenID Connect, authorization code + PKCE). No database access.

Only `openid email profile` is requested. Google access tokens are never stored:
the ID token is verified once and only its `sub`, email and name are used.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from app import config

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CALLBACK_PATH = "/auth/google/callback"


class GoogleLoginError(Exception):
    """Safe to log by code; never carries Google's raw response or tokens."""


@dataclass(frozen=True)
class GoogleSettings:
    client_id: str
    client_secret: str
    origin: str | None

    @classmethod
    def from_env(cls) -> "GoogleSettings":
        secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
        secret_file = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_FILE", "")
        if not secret and secret_file:
            try:
                secret = Path(secret_file).read_text(encoding="utf-8").strip()
            except OSError:
                secret = ""
        return cls(os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip(), secret.strip(), config.PUBLIC_ORIGIN)

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.origin)

    @property
    def redirect_uri(self) -> str:
        return f"{self.origin}{CALLBACK_PATH}"


@dataclass(frozen=True)
class Identity:
    sub: str
    email: str
    name: str | None


def new_verifier() -> str:
    # RFC 7636: 43-128 characters from the unreserved set; token_urlsafe(64) gives 86.
    return secrets.token_urlsafe(64)


def challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def authorization_url(settings: GoogleSettings, state: str, verifier: str, nonce: str) -> str:
    return AUTHORIZE_URL + "?" + urlencode({
        "response_type": "code", "client_id": settings.client_id, "redirect_uri": settings.redirect_uri,
        "scope": "openid email profile", "state": state, "nonce": nonce,
        "code_challenge": challenge(verifier), "code_challenge_method": "S256", "prompt": "select_account",
    })


def fetch_identity(settings: GoogleSettings, code: str, verifier: str, nonce: str) -> Identity:
    """Exchange the code, then verify signature, audience, issuer, expiry, nonce and email."""
    from google.auth import exceptions
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    transport = Request()
    try:
        response = transport(TOKEN_URL, method="POST", timeout=10, headers={"Content-Type": "application/x-www-form-urlencoded"},
                             body=urlencode({"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                                             "client_id": settings.client_id, "client_secret": settings.client_secret,
                                             "redirect_uri": settings.redirect_uri}))
    except exceptions.TransportError:
        raise GoogleLoginError("token_unreachable") from None
    if response.status != 200:
        raise GoogleLoginError("token_rejected")
    try:
        token = json.loads(response.data)["id_token"]
        claims = id_token.verify_oauth2_token(token, transport, audience=settings.client_id, clock_skew_in_seconds=10)
    except (KeyError, TypeError, ValueError, exceptions.GoogleAuthError):
        raise GoogleLoginError("id_token_invalid") from None
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise GoogleLoginError("nonce_mismatch")
    if claims.get("email_verified") is not True or not claims.get("email") or not claims.get("sub"):
        raise GoogleLoginError("email_unverified")
    return Identity(str(claims["sub"]), str(claims["email"]).strip().lower(), claims.get("name"))
