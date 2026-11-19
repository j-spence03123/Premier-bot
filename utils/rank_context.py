"""Small facts shown under a rank change: the game that caused it and how often a rank was reached this act."""

from datetime import datetime, timezone

ORDINALS = ("First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth")


def rank_group(tier_id):
    """Index of the rank (Iron, Bronze, ... Radiant) for a competitive tier, or None for unrated."""
    if not isinstance(tier_id, int) or tier_id < 3:
        return None
    return (tier_id - 3) // 3


def rank_group_name(tier_name):
    """'Platinum 2' -> 'Platinum'; 'Radiant' stays 'Radiant'."""
    words = str(tier_name or "").split()
    if len(words) > 1 and words[-1].isdigit():
        words = words[:-1]
    return " ".join(words) or "this rank"


def ordinal(count):
    if 1 <= count <= len(ORDINALS):
        return ORDINALS[count - 1]
    suffix = "th" if 11 <= count % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(count % 10, "th")
    return f"{count}{suffix}"


def _points(history):
    points = []
    for row in history or []:
        if not isinstance(row, dict):
            continue
        stamp, tier = row.get("date_raw"), row.get("currenttier")
        if not isinstance(stamp, (int, float)) or not isinstance(tier, int):
            continue
        try:
            when = datetime.fromtimestamp(stamp, timezone.utc)
        except (ValueError, OverflowError, OSError):
            continue
        points.append((when, tier, row.get("season_id"), str(row.get("match_id") or "")))
    return sorted(points)


def act_entries(history, season):
    """How many times each rank was reached in ``season`` (placement or ranking up into it).

    ``complete`` is True only when the history reaches back past the start of the act, so
    the counts include every game of it.
    """
    points = _points(history)
    in_season = [point for point in points if point[2] == season]
    if not in_season:
        return {}, False
    complete = any(point[2] != season and point[0] < in_season[0][0] for point in points)
    counts, previous = {}, None
    for _, tier, _, _ in in_season:
        group = rank_group(tier)
        if group is not None and (previous is None or group > previous):
            counts[str(group)] = counts.get(str(group), 0) + 1
        previous = group if group is not None else previous
    return counts, complete


def count_rank_entry(record, history, to_id, match_id=None):
    """Count a rank-up into a new rank for this act.

    Returns ``(count, record)``: ``count`` is None when it cannot be confirmed, and
    ``record`` is the per-act tally to save with the player's rank state.
    """
    group = rank_group(to_id)
    points = _points(history)
    if group is None or not points:
        return None, record
    latest = points[-1]
    season = latest[2]
    counts, complete = act_entries(history, season)
    included = bool(match_id) and any(point[3] == str(match_id) for point in points) or (
        rank_group(latest[1]) == group and latest[1] == to_id)
    if not included:
        counts[str(group)] = counts.get(str(group), 0) + 1
    if not complete and record and record.get("season") == season and record.get("complete"):
        saved = dict(record.get("groups") or {})
        saved[str(group)] = saved.get(str(group), 0) + 1
        counts, complete = saved, True
    updated = {"season": season, "complete": complete, "groups": counts}
    return (counts.get(str(group)) if complete else None), updated


def match_context(stored_rows, direction, now, parse_stored, parse_time, max_age_hours=3):
    """'After a 13–8 win on Bind' from the newest stored competitive match, if it is recent."""
    newest = None
    for row in stored_rows or []:
        if not isinstance(row, dict):
            continue
        started = parse_time((row.get("meta") or {}).get("started_at"))
        if started and started.tzinfo and (newest is None or started > newest[0]):
            newest = (started, row)
    if newest is None or (now - newest[0]).total_seconds() > max_age_hours * 3600:
        return None
    try:
        game = parse_stored(newest[1])
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        return None
    if not game["score"] or game["map"] in ("?", ""):
        return None
    first = game["score"].split("-")[0]
    article = "an" if first.startswith("8") or first in ("11", "18") else "a"
    outcome = {True: "win", False: "loss", None: "draw"}[game["won"]]
    return f"After {article} {game['score'].replace('-', '–')} {outcome} on {game['map']}"


def rank_card_context(match_text, count, to_name):
    parts = [match_text] if match_text else []
    if count:
        parts.append(f"{ordinal(count)} time in {rank_group_name(to_name)} this act")
    return "  ·  ".join(parts) or None
