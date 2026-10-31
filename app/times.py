"""Time conventions in one place: timestamps are stored as UTC without tzinfo, and a "day" is a local day in the
IANA zone the request names."""
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_naive(value: datetime) -> datetime:
    """An aware datetime as the stored form."""
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def local_day(value: datetime, zone: ZoneInfo) -> date:
    """The local day a stored timestamp falls on."""
    return value.replace(tzinfo=timezone.utc).astimezone(zone).date()


def day_start(day: date, zone: ZoneInfo) -> datetime:
    """Local midnight at the start of `day`, in the stored form. The day ends at the next day's start."""
    return utc_naive(datetime.combine(day, time.min, zone))
