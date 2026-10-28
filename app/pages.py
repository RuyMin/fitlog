"""HTML pages with content-hashed asset links, so CSS/JS/images can be cached for good.

Every `/static/...?v=...` link in a page is rewritten to `?v=<hash of that file>`. A request
carrying the current hash gets a year-long immutable cache; any other `v` (a hand-written stamp
or an old hash) is revalidated as before. A changed file therefore always gets a new address,
whether or not someone remembered to bump the stamp in the HTML.
"""
import hashlib
import re
from pathlib import Path

from fastapi.responses import HTMLResponse

STATIC_DIR = Path(__file__).parent / "static"
ASSET_LINK = re.compile(r'(/static/[\w./-]+)\?v=[^"\s]*')
IMMUTABLE = "public, max-age=31536000, immutable"
_hashes: dict[Path, tuple[int, str]] = {}


def asset_hash(url_path: str) -> str | None:
    """Short content hash of a file under /static/, or None if it does not exist."""
    path = (STATIC_DIR / url_path.removeprefix("/static/")).resolve()
    if STATIC_DIR.resolve() not in path.parents or not path.is_file():
        return None
    stamp = path.stat().st_mtime_ns
    cached = _hashes.get(path)
    if cached is None or cached[0] != stamp:
        cached = (stamp, hashlib.sha256(path.read_bytes()).hexdigest()[:12])
        _hashes[path] = cached
    return cached[1]


CATALOG_LINK = re.compile(r'/api/exercise-presets\?v=[^"\s]*')


def render(name: str) -> str:
    text = (STATIC_DIR / name).read_text(encoding="utf-8")
    text = ASSET_LINK.sub(lambda m: f"{m[1]}?v={asset_hash(m[1]) or 'missing'}", text)
    if CATALOG_LINK.search(text):
        # The exercise list changes when an admin edits it, so it is linked by its own version.
        from app.services import exercise_presets
        text = CATALOG_LINK.sub(lambda m: f"/api/exercise-presets?v={exercise_presets.version()}", text)
    return text


def page(name: str, cache_control: str = "no-cache") -> HTMLResponse:
    return HTMLResponse(render(name), headers={"Cache-Control": cache_control})
