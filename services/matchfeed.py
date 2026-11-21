"""Pure matchfeed helpers shared by polling and notification tests."""

from datetime import datetime, timedelta
from copy import deepcopy
from hashlib import sha256
import json
from zoneinfo import ZoneInfo

MATCHFEED_DAY_ZONE = ZoneInfo("Europe/London")
SESSION_IDLE_LIMIT = timedelta(hours=1)
ORDINAL_WORDS = ("First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth")


def format_match_footer(session_count, roster_size):
    if session_count <= len(ORDINAL_WORDS):
        ordinal = ORDINAL_WORDS[session_count - 1]
    else:
        suffix = "th" if 11 <= session_count % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(session_count % 10, "th")
        ordinal = f"{session_count}{suffix}"
    kind = "group" if roster_size > 1 else "solo"
    return f"{ordinal} {kind} game of this session"


def next_matchfeed_counts(feed, players, match_id, started, finished, recap_match=None):
    """Calculate the footer and the state to save after the post succeeds."""
    roster = set()
    for player in players:
        riot_key = f"{player.get('name', '')}#{player.get('tag', '')}".casefold()
        roster.add(player.get("puuid") or riot_key)
    roster_key = json.dumps(sorted(roster))
    counts = feed.get("match_counts") or {}
    sessions = deepcopy(counts.get("sessions", {}))
    pending = deepcopy(counts.get("pending_recaps", {}))
    previous = sessions.get(roster_key)
    last_finished = datetime.fromisoformat(previous["last_finished"]) if previous else None
    session_count = 1
    continuing = (previous and not previous.get("recap_message_id")
                  and started < last_finished + SESSION_IDLE_LIMIT
                  and (recap_match is None or previous.get("matches")))
    if continuing:
        session_count += previous["count"]
    elif previous and previous.get("matches") and not previous.get("recap_message_id"):
        pending[previous["recap_id"]] = previous
    sessions[roster_key] = {
        "last_finished": max(finished, last_finished or finished).isoformat(),
        "count": session_count,
    }
    if recap_match is not None:
        matches = list(previous["matches"]) if continuing else []
        matches = [match for match in matches if match["id"] != str(match_id)]
        matches.append(recap_match)
        matches.sort(key=lambda match: match["started"])
        sessions[roster_key].update(
            count=len(matches), matches=matches,
            recap_id=sha256((roster_key + matches[0]["id"]).encode()).hexdigest()[:24],
            players=[p.get("name") or "Player" for p in players],
        )
        session_count = len(matches)
    return {"sessions": sessions, "pending_recaps": pending}, format_match_footer(session_count, len(roster))


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


def match_result_word(team_record):
    """Return "won", "drew" or "lost" for a team's record from match detail."""
    if team_record.get("won"):
        return "won"
    rounds = team_record.get("rounds") or {}
    if "won" in rounds and rounds.get("won") == rounds.get("lost"):
        return "drew"
    return "lost"


def format_match_notification(user_ids, result_word, score, map_name):
    """Format a matchfeed notification while keeping mentions explicit."""
    mentions = " ".join(f"<@{user_id}>" for user_id in dict.fromkeys(user_ids))
    return f"{mentions} {result_word} {score} on {map_name}!"
