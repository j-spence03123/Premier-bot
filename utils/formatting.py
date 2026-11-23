"""Formatting helpers shared by bot commands and renderers."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

UK_ZONE = ZoneInfo("Europe/London")


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_range(start, end):
    first = datetime.fromisoformat(start)
    last = datetime.fromisoformat(end)
    if first == last:
        return f"{first:%b} {first.day}"
    if first.month == last.month:
        return f"{first:%b} {first.day}\u2013{last.day}"
    return f"{first:%b} {first.day} \u2013 {last:%b} {last.day}"


def uk_time(moment):
    """A datetime in UK time (GMT or BST); naive datetimes are treated as UTC."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(UK_ZONE)
