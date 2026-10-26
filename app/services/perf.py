"""Speed statistics for the operator: how long API requests take on the server and on the phone.

Only technical facts are stored (time, route template, status, durations). Paths keep their shape
with numbers replaced by {id}; query strings, bodies and record contents are never stored.
Rows older than RETENTION are removed.
"""
import random
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import PerfEvent, User

RETENTION = timedelta(days=14)
NUMBER = re.compile(r"/\d+(?=/|$)")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def template(path: str) -> str:
    """/api/workouts/12/sets/40 -> /api/workouts/{id}/sets/{id} (no query string)."""
    return NUMBER.sub("/{id}", path.split("?", 1)[0])[:160]


def purge(session: Session) -> None:
    session.execute(delete(PerfEvent).where(PerfEvent.at < utc_now() - RETENTION))


def record_server(user_id: int | None, method: str, route: str, status: int, server_ms: float, size: int | None) -> None:
    """One handled API request. Runs in a worker thread after the response is ready."""
    with SessionLocal() as session:
        session.add(PerfEvent(at=utc_now(), user_id=user_id, source="server", route=route[:160], method=method[:8],
                              status=status, total_ms=round(server_ms, 2), server_ms=round(server_ms, 2), bytes=size))
        if random.random() < 0.01:
            purge(session)
        session.commit()


def record_client(session: Session, user_id: int, events: list) -> int:
    """Timings the phone measured: each API request it waited for, and each screen it opened."""
    oldest = utc_now() - RETENTION
    for event in events:
        at = event.at.astimezone(timezone.utc).replace(tzinfo=None)
        if at < oldest or at > utc_now() + timedelta(minutes=5):
            continue  # a wrong phone clock must not keep rows forever or put them in the future
        session.add(PerfEvent(at=at, user_id=user_id, source=event.kind, page=event.page, route=template(event.route),
                              method=event.method, status=event.status, total_ms=event.total_ms, server_ms=event.server_ms,
                              html_ms=event.html_ms, cached=event.cached))
    purge(session)
    session.commit()
    return len(events)


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(share * (len(ordered) - 1))))]


def summary(session: Session, days: int) -> dict:
    """Aggregates for the settings card and the admin CLI."""
    since = utc_now() - timedelta(days=days)
    rows = session.scalars(select(PerfEvent).where(PerfEvent.at >= since)).all()
    emails = dict(session.execute(select(User.id, User.email)).all())

    def stats(values):
        return {"count": len(values), "p50": round(median(values)), "p90": round(percentile(values, 0.9))} if values else {"count": 0}

    requests = defaultdict(lambda: {"client": [], "server": [], "errors": 0})
    for row in rows:
        if row.source in ("client", "server"):
            entry = requests[(row.method or "GET", row.route)]
            entry[row.source].append(row.total_ms)
            if row.source == "client" and row.status is not None and (row.status == 0 or row.status >= 400):
                entry["errors"] += 1
    by_route = []
    for (method, route), entry in requests.items():
        client, server = stats(entry["client"]), stats(entry["server"])
        network = round(client["p50"] - server["p50"]) if client["count"] and server["count"] else None
        by_route.append({"method": method, "route": route, "client": client, "server": server, "network_p50": network, "errors": entry["errors"]})
    by_route.sort(key=lambda item: (item["client"].get("count", 0), item["server"].get("count", 0)), reverse=True)

    pages = defaultdict(lambda: {"ready": [], "html": [], "cached": 0})
    for row in rows:
        if row.source == "page":
            entry = pages[row.page or "?"]
            entry["ready"].append(row.total_ms)
            if row.html_ms is not None:
                entry["html"].append(row.html_ms)
            entry["cached"] += bool(row.cached)
    by_page = [{"page": page, "data": stats(entry["ready"]), "html": stats(entry["html"]),
                "cached_share": round(entry["cached"] / len(entry["ready"]), 2)} for page, entry in pages.items()]
    by_page.sort(key=lambda item: item["data"]["count"], reverse=True)

    hours = defaultdict(list)
    for row in rows:
        if row.source == "client":
            hours[row.at.replace(minute=0, second=0, microsecond=0)].append(row.total_ms)
    by_hour = [{"hour": hour.replace(tzinfo=timezone.utc).isoformat(), **stats(values)} for hour, values in sorted(hours.items())]

    users = defaultdict(lambda: {"client": 0, "server": 0, "page": 0})
    for row in rows:
        users[emails.get(row.user_id, "-")][row.source] += 1
    client_all = [row.total_ms for row in rows if row.source == "client"]
    server_all = [row.total_ms for row in rows if row.source == "server"]
    return {"days": days, "since": since.replace(tzinfo=timezone.utc).isoformat(),
            "overall": {"client": stats(client_all), "server": stats(server_all)},
            "routes": by_route[:40], "pages": by_page, "hours": by_hour[-48:],
            "users": [{"email": email, **counts} for email, counts in sorted(users.items())]}
