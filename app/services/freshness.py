"""Whether a phone coming back to the app needs to reload: only when records changed since it last loaded them.

Every successful write bumps the user's version. A session that was already up to date when it wrote stays up to
date, so its own edits never make it reload; an edit from another device, the AI helper on another tab, or a server
restart (versions live in memory) does. One Uvicorn worker serves the app, so a process-wide dict is enough.
"""
import hashlib
import threading

_lock = threading.Lock()
_version: dict[int, int] = {}
_seen: dict[tuple[int, str], int] = {}


def session_key(token: str | None) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()[:16]


def wrote(user_id: int, session: str) -> None:
    with _lock:
        current = _version.get(user_id, 0)
        if _seen.get((user_id, session)) == current:
            _seen[(user_id, session)] = current + 1
        _version[user_id] = current + 1


def check(user_id: int, session: str) -> bool:
    """True when this session has not seen the latest records; it is then counted as up to date (it reloads now)."""
    with _lock:
        current = _version.get(user_id, 0)
        changed = _seen.get((user_id, session)) != current
        _seen[(user_id, session)] = current
        return changed
