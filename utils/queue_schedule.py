"""Queue schedule calculations."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def next_queue_start(config, now_utc):
    zone = ZoneInfo(config["timezone"])
    local_now = now_utc.astimezone(zone)
    hour, minute = map(int, config["time"].split(":"))
    candidates = []
    for offset in range(8):
        day = local_now.date() + timedelta(days=offset)
        if day.weekday() not in config["days"]:
            continue
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
        if candidate > local_now:
            candidates.append(candidate)
    return min(candidates) if candidates else None
