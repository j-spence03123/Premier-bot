"""Pure matchfeed helpers shared by polling and notification tests."""

from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo


MATCHFEED_DAY_ZONE = ZoneInfo("Europe/London")
SESSION_IDLE_LIMIT = timedelta(hours=2)
ORDINAL_WORDS = ("First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth")


def format_match_footer(session_count, group_size, daily_count):
    if session_count <= len(ORDINAL_WORDS):
        ordinal = ORDINAL_WORDS[session_count - 1]
    else:
        suffix = "th" if 11 <= session_count % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(session_count % 10, "th")
        ordinal = f"{session_count}{suffix}"
    kind = "group" if group_size > 1 else "solo"
    return f"{ordinal} {kind} game of this session", f"Total games played today: {daily_count}"


def next_matchfeed_counts(feed, players, started, finished):
    """Calculate the footer and the state to save after the post succeeds."""
    roster = sorted({
        p.get("puuid") or f"{p.get('name', '')}#{p.get('tag', '')}".casefold()
        for p in players
    })
    roster_key = json.dumps(roster)
    counts = feed.get("match_counts") or {}
    sessions = dict(counts.get("sessions", {}))
    days = dict(counts.get("days", {}))
    previous = sessions.get(roster_key)
    last_finished = datetime.fromisoformat(previous["last_finished"]) if previous else None
    session_count = 1
    if previous and started <= last_finished + SESSION_IDLE_LIMIT:
        session_count += previous["count"]
    sessions[roster_key] = {
        "last_finished": max(finished, last_finished or finished).isoformat(),
        "count": session_count,
    }
    day = finished.astimezone(MATCHFEED_DAY_ZONE).date().isoformat()
    days[day] = days.get(day, 0) + 1
    return {"sessions": sessions, "days": days}, format_match_footer(session_count, len(roster), days[day])


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
