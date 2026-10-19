import math
import os
from urllib.parse import urlsplit

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
