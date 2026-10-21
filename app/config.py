import math
import os
from urllib.parse import urlsplit

# Single source of truth for the app version (FastAPI metadata, /api/health, settings footer).
APP_VERSION = "1.0.0"

# A configurable example target; a settings UI is deferred.
PROTEIN_GOAL_GRAMS = float(os.environ.get("FITLOG_PROTEIN_GOAL_G", "150"))
if not math.isfinite(PROTEIN_GOAL_GRAMS) or not 0 < PROTEIN_GOAL_GRAMS <= 1000:
    raise ValueError("FITLOG_PROTEIN_GOAL_G must be greater than 0 and at most 1000.")


def public_origin(value: str) -> str | None:
    """`https://host[:port]` the app is served at, or None when unset."""
    if not value:
        return None
    parts = urlsplit(value.strip())
    local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    if parts.scheme not in {"https", "http"} or not parts.netloc or (parts.scheme == "http" and not local):
        raise ValueError("FITLOG_PUBLIC_URL must be an https:// URL (http:// only for localhost).")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise ValueError("FITLOG_PUBLIC_URL must not contain a path, query or fragment.")
    return f"{parts.scheme}://{parts.netloc}".lower()


# Unsafe requests must come from this origin; also the OAuth redirect base.
PUBLIC_ORIGIN = public_origin(os.environ.get("FITLOG_PUBLIC_URL", ""))
# Plain-HTTP local development only: drops Secure and the __Host- cookie prefix.
INSECURE_COOKIES = os.environ.get("FITLOG_INSECURE_COOKIES") == "1"


def secret_key() -> str:
    """Server secret for encrypting stored API keys (FITLOG_SECRET_KEY or FITLOG_SECRET_KEY_FILE)."""
    value = os.environ.get("FITLOG_SECRET_KEY", "")
    path = os.environ.get("FITLOG_SECRET_KEY_FILE", "")
    if not value and path:
        try:
            with open(path, encoding="utf-8") as handle:
                value = handle.read()
        except OSError:
            value = ""
    return value.strip()


# Natural-language record assistant. Each user registers their own Anthropic API key.
AI_MODEL = os.environ.get("FITLOG_AI_MODEL", "claude-opus-5-5").strip()
AI_DAILY_LIMIT = int(os.environ.get("FITLOG_AI_DAILY_LIMIT", "50"))
if not 1 <= AI_DAILY_LIMIT <= 1000:
    raise ValueError("FITLOG_AI_DAILY_LIMIT must be between 1 and 1000.")
