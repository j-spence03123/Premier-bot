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
            match["match_id"] = mid
            match["team"] = str(row["stats"].get("team", "")).casefold()
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
                "match_id": last["match_id"],
                "team": last["team"],
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


def recap_callbacks(context, facts):
    """Shortlist verified history with a connection to the current game."""
    teammates = {player["name"]: player for player in facts["teammates"]}
    players = [row for row in context or [] if row["player"] in teammates]
    score = facts.get("rounds") or {}
    won, lost = score.get("won"), score.get("lost")
    outcome = None
    if type(won) is int and type(lost) is int:
        outcome = "win" if won > lost else "loss" if won < lost else "draw"
    candidates = []
    prior_games = (player.get("previous_match") or {} for player in players)
    previous_sides = {(last.get("match_id"), last.get("team")) for last in prior_games}
    shared = (len(teammates) > 1 and {p["player"] for p in players} == teammates.keys()
              and len(previous_sides) == 1 and all(mid and side in ("red", "blue") for mid, side in previous_sides))
    for player in players:
        name = player["player"]
        changes = player.get("rank_changes") or []
        if changes:
            change = changes[-1]
            current = change["when"] == "this match"
            if current or (change["direction"], outcome) in (("up", "loss"), ("down", "win")):
                candidates.append((0 if current else 3,
                                   f"{name} ranked {change['direction']} to {change['to_rank']} {change['when']}."))
        streak = player.get("streak_entering_match")
        if streak and outcome and (streak["outcome"] != outcome or streak["games"] >= 3):
            results = "wins" if streak["outcome"] == "win" else "losses"
            priority = 1 if streak["outcome"] != outcome else 3
            candidates.append((priority, f"{name} came in on {streak['games']} straight {results}."))
        yesterday = player.get("yesterday") or {}
        if yesterday and outcome in ("win", "loss"):
            same, opposite = ("wins", "losses") if outcome == "win" else ("losses", "wins")
            if yesterday[same] == 0 and yesterday[opposite] >= 3 and not yesterday["draws"]:
                candidates.append((4, f"{name}'s available games yesterday were all {opposite}."))
        last = player.get("previous_match") or {}
        kd = teammates[name].get("match_kd")
        kda = last.get("kda")
        if (kd is not None and kda and len(kda) == 3 and all(type(n) is int for n in kda[:2])
                and last.get("map") and last["map"] != "?"):
            kills, deaths, _ = kda
            if (deaths >= 8 and kills >= 2 * deaths and kd <= 0.75
                    or kills >= 4 and deaths >= 2 * kills and kd >= 1.75):
                candidates.append((2, f"{name} went {kills}/{deaths} in their previous game on {last['map']}."))
        if (outcome and last.get("outcome") != outcome and last.get("map") == facts.get("map")
                and last.get("map") and last.get("score")):
            subject = "This lineup" if shared else name
            candidates.append((1 if shared else 2, f"{subject}'s previous game was a {last['score']} "
                               f"{last['outcome']} on {last['map']}."))
    return list(dict.fromkeys(sentence for _, sentence in sorted(candidates, key=lambda item: item[0])))[:3]
