"""Build factual recap context from recent competitive and rank history."""

from datetime import datetime, timedelta, timezone
from itertools import groupby

from services.matchfeed import MATCHFEED_DAY_ZONE
from utils.formatting import parse_time
from utils.stored_matches import parse_stored


def _record(matches):
    return {
        "wins": sum(match["won"] is True for match in matches),
        "losses": sum(match["won"] is False for match in matches),
        "draws": sum(match["won"] is None for match in matches),
    }


def _prior_results(history, match_id, started):
    prior = {}
    for row in history:
        if not isinstance(row, dict):
            continue
        meta = row.get("meta") or {}
        mid = meta.get("id")
        when = parse_time(meta.get("started_at"))
        if not mid or mid == match_id or not when or when.tzinfo is None or when >= started:
            continue
        try:
            match = parse_stored(row)
        except (AttributeError, TypeError, ValueError):
            continue
        if match["score"]:
            prior[mid] = (when, match)
    return sorted(prior.values(), key=lambda item: item[0], reverse=True)


def _rank_changes(history, match_id, started, today, yesterday):
    points = {}
    for row in history:
        if not isinstance(row, dict):
            continue
        mid = row.get("match_id")
        timestamp = row.get("date_raw")
        tier = row.get("currenttier")
        name = row.get("currenttierpatched") or row.get("currenttier_patched")
        if not mid or not isinstance(timestamp, (int, float)) or not isinstance(tier, int) or not name:
            continue
        try:
            when = datetime.fromtimestamp(timestamp, timezone.utc)
        except (ValueError, OverflowError, OSError):
            continue
        if when < started or mid == match_id:
            points[mid] = (when, mid, row.get("season_id"), tier, name)

    ordered = sorted(points.values())
    changes = []
    for before, after in zip(ordered, ordered[1:]):
        when, mid, season, tier, name = after
        previous_tier = before[3]
        if season != before[2] or min(tier, previous_tier) < 3 or tier == previous_tier:
            continue
        day = when.astimezone(MATCHFEED_DAY_ZONE).date()
        if mid == match_id:
            timing = "this match"
        elif day == yesterday:
            timing = "yesterday"
        elif day == today:
            timing = "earlier today"
        else:
            continue
        changes.append({
            "when": timing,
            "direction": "up" if tier > previous_tier else "down",
            "from_rank": before[4],
            "to_rank": name,
        })
    return changes


def matchfeed_recap_context(players, match_id, started, finished, histories, rank_histories):
    """Include only players on the card and results known by this match."""
    today = finished.astimezone(MATCHFEED_DAY_ZONE).date()
    yesterday = today - timedelta(days=1)
    facts = []
    for player in players:
        key = f"{player.get('name', '')}#{player.get('tag', '')}".casefold()
        context = {"player": player["name"]}
        prior = _prior_results(histories.get(key, []), match_id, started)
        for label, day in (("yesterday", yesterday), ("earlier_today", today)):
            games = [game for when, game in prior if when.astimezone(MATCHFEED_DAY_ZONE).date() == day]
            if games:
                context[label] = _record(games)
        if prior:
            when, last = prior[0]
            context["previous_match"] = {
                "date": when.astimezone(MATCHFEED_DAY_ZONE).date().isoformat(),
                "map": last["map"],
                "score": last["score"],
                "outcome": {True: "win", False: "loss", None: "draw"}[last["won"]],
                "kda": [last["k"], last["d"], last["a"]],
            }
            outcome, games = next(groupby(prior, key=lambda item: item[1]["won"]))
            length = sum(1 for _ in games)
            if outcome is not None and length >= 2:
                context["streak_entering_match"] = {"outcome": "win" if outcome else "loss", "games": length}
        changes = _rank_changes(rank_histories.get(key, []), match_id, started, today, yesterday)
        if changes:
            context["rank_changes"] = changes
        if len(context) > 1:
            facts.append(context)
    return facts


def recap_context_text(context):
    """Add a short factual continuation when the local recap is used."""
    sentences = []
    for player in context or []:
        name = player["player"]
        changes = player.get("rank_changes", [])
        if changes:
            change = changes[-1]
            sentences.append(f"{name} ranked {change['direction']} to {change['to_rank']} {change['when']}.")
        record = player.get("yesterday")
        if record:
            result = f"{record['wins']}W–{record['losses']}L"
            if record["draws"]:
                result += f"–{record['draws']}D"
            sentences.append(f"{name}'s available results from yesterday were {result}.")
        if len(sentences) >= 2:
            break
    return " ".join(sentences[:2])
