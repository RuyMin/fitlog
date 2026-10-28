import math
import os
from urllib.parse import urlsplit

# Single source of truth for the app version (FastAPI metadata, /api/health, settings footer).
APP_VERSION = "1.3.2"

def goal(name: str, default: str, maximum: float) -> float:
    """A server-wide daily target for the home rings; per-user goals are deferred."""
    value = float(os.environ.get(name, default))
    if not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f"{name} must be greater than 0 and at most {maximum:g}.")
    return value


PROTEIN_GOAL_GRAMS = goal("FITLOG_PROTEIN_GOAL_G", "150", 1000)
CALORIE_GOAL_KCAL = goal("FITLOG_CALORIE_GOAL_KCAL", "2100", 10000)
SLEEP_GOAL_MINUTES = goal("FITLOG_SLEEP_GOAL_MINUTES", "420", 1440)
# Macro targets follow the calorie goal: half from carbohydrate (4 kcal/g), 30% from fat (9 kcal/g).
CARBOHYDRATE_GOAL_GRAMS = round(CALORIE_GOAL_KCAL * 0.5 / 4)
FAT_GOAL_GRAMS = round(CALORIE_GOAL_KCAL * 0.3 / 9)


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
