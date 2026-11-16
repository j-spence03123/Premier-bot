"""Pure matchfeed helpers shared by polling and notification tests."""

from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo

from utils.formatting import parse_time


MATCHFEED_DAY_ZONE = ZoneInfo("Europe/London")
SESSION_IDLE_LIMIT = timedelta(hours=2)
ORDINAL_WORDS = ("First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth")


def format_match_footer(session_count, player_totals):
    if session_count <= len(ORDINAL_WORDS):
        ordinal = ORDINAL_WORDS[session_count - 1]
    else:
        suffix = "th" if 11 <= session_count % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(session_count % 10, "th")
        ordinal = f"{session_count}{suffix}"
    if len(player_totals) == 1:
        right_lines = (f"Games played today: {player_totals[0][1]}",)
    else:
        right_lines = ("Games played today", *(f"{name}: {total}" for name, total in player_totals))
    kind = "group" if len(player_totals) > 1 else "solo"
    return f"{ordinal} {kind} game of this session", right_lines


def next_matchfeed_counts(feed, players, match_id, started, finished, histories):
    """Calculate the footer and the state to save after the post succeeds."""
    roster = {}
    for player in players:
        riot_key = f"{player.get('name', '')}#{player.get('tag', '')}".casefold()
        player_id = player.get("puuid") or riot_key
        roster[player_id] = (player.get("name") or "Player", riot_key)
    roster_key = json.dumps(sorted(roster))
    counts = feed.get("match_counts") or {}
    sessions = dict(counts.get("sessions", {}))
    player_days = dict(counts.get("player_days", {}))
    previous = sessions.get(roster_key)
    last_finished = datetime.fromisoformat(previous["last_finished"]) if previous else None
    session_count = 1
    if previous and started <= last_finished + SESSION_IDLE_LIMIT:
        session_count += previous["count"]
    sessions[roster_key] = {
        "last_finished": max(finished, last_finished or finished).isoformat(),
        "count": session_count,
    }
    day = finished.astimezone(MATCHFEED_DAY_ZONE).date()
    day_key = day.isoformat()
    day_players = dict(player_days.get(day_key, {}))
    totals = []
    for player_id, (name, riot_key) in roster.items():
        match_ids = set(day_players.get(player_id, []))
        for row in histories.get(riot_key, []):
            meta = row.get("meta") or {}
            previous_id = meta.get("id")
            previous_start = parse_time(meta.get("started_at"))
            if previous_id and previous_start and previous_start.tzinfo and previous_start < started:
                if previous_start.astimezone(MATCHFEED_DAY_ZONE).date() == day:
                    match_ids.add(str(previous_id))
        match_ids.add(str(match_id))
        day_players[player_id] = sorted(match_ids)
        totals.append((name, len(match_ids)))
    player_days[day_key] = day_players
    # Keep the previous day available for reports that arrive around midnight.
    player_days = {key: player_days[key] for key in sorted(player_days)[-2:]}
    return {"sessions": sessions, "player_days": player_days}, format_match_footer(session_count, totals)


def group_registered_players(players, linked_accounts):
    """Group linked players found in a match by team ID.

    ``linked_accounts`` maps case-folded Riot IDs to account entries containing
    a set of Discord ``user_ids``.
    """
    groups = {}
    for player in players or []:
        riot_key = f"{player.get('name', '')}#{player.get('tag', '')}".casefold()
        if riot_key not in linked_accounts or not player.get("team_id"):
            continue
        group = groups.setdefault(str(player["team_id"]), {
            "account_keys": set(), "user_ids": set(), "players": [],
        })
        group["account_keys"].add(riot_key)
        group["user_ids"].update(linked_accounts[riot_key].get("user_ids", set()))
        group["players"].append(player)
    return groups


def format_match_notification(user_ids, result_word, score, map_name):
    """Format a matchfeed notification while keeping mentions explicit."""
    mentions = " ".join(f"<@{user_id}>" for user_id in dict.fromkeys(user_ids))
    return f"{mentions} {result_word} {score} on {map_name}!"
