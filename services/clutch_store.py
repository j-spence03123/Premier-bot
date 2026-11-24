"""Per-match clutch counts and LVP flags for linked players, recorded by the match feed for the weekly recap awards.

The weekly recap only reads stored-match summaries, which have no round data. The match feed already fetches
full match details, so it saves each linked player's clutch rounds, and whether they were their team's lowest
scorer (the match feed's LVP), here as it scans. Entries older than
``RETENTION`` are dropped on every write, which keeps the file to roughly two weeks of games.

Store layout: ``{match_id: {"started": iso, "players": {riot_key: [won, lost, lvp]}}}``. Entries saved before LVPs
were tracked have only ``[won, lost]``; their LVP comes from cached match details when those are still around.
"""

from datetime import datetime, timedelta

from utils.formatting import parse_time
from utils.match_summary import _clutch_rounds

RETENTION = timedelta(days=14)


def _riot_key(player):
    return f"{player.get('name', '')}#{player.get('tag', '')}".casefold()


def _team_low_scores(players):
    """Lowest score per team, for teams with enough players for 'lowest' to mean something."""
    scores = {}
    for player in players:
        score = (player.get("stats") or {}).get("score")
        if player.get("team_id") and isinstance(score, (int, float)):
            scores.setdefault(player["team_id"], []).append(score)
    return {team: min(values) for team, values in scores.items() if len(values) >= 3}


def match_clutches(detail, riot_keys=None):
    """``{riot_key: [won, lost, lvp]}`` for players in ``detail``, limited to ``riot_keys`` when given.

    ``lvp`` is 1 when the player had the lowest score on their team (ties count), matching the match feed tag.
    """
    players = (detail or {}).get("players") or []
    won, lost = _clutch_rounds(detail or {}, players)
    lows = _team_low_scores(players)
    result = {}
    for player in players:
        key, puuid = _riot_key(player), player.get("puuid")
        if key == "#" or (riot_keys is not None and key not in riot_keys):
            continue
        low = lows.get(player.get("team_id"))
        lvp = int(low is not None and (player.get("stats") or {}).get("score") == low)
        result[key] = [won.get(puuid, 0), lost.get(puuid, 0), lvp]
    return result


def record_match(store, match_id, started, clutches, now):
    """Add one match to ``store`` in place and drop entries past retention. Returns ``store``."""
    if clutches:
        store[str(match_id)] = {"started": started.isoformat(), "players": clutches}
    cutoff = now - RETENTION
    for key in [key for key, entry in store.items()
                if not isinstance(entry, dict) or not _recent(entry.get("started"), cutoff)]:
        del store[key]
    return store


def _recent(started, cutoff):
    when = parse_time(started)
    return isinstance(when, datetime) and when.tzinfo is not None and when >= cutoff


def player_clutches(riot_key, match_ids, store, peek_detail=None):
    """Clutch and LVP totals over ``match_ids`` for one player.

    Falls back to ``peek_detail(match_id)`` (cached match details, no API call) for games missing from the
    store, or saved before LVPs were tracked. ``games`` and ``lvp_games`` count only games with that data.
    """
    won = lost = games = lvps = lvp_games = 0
    for match_id in match_ids:
        entry = (store.get(str(match_id)) or {}).get("players") or {}
        counts = entry.get(riot_key)
        if (not isinstance(counts, (list, tuple)) or len(counts) < 3) and peek_detail is not None:
            detail = peek_detail(str(match_id))
            fresh = match_clutches(detail, {riot_key}).get(riot_key) if isinstance(detail, dict) else None
            counts = fresh or counts
        if not isinstance(counts, (list, tuple)) or len(counts) < 2:
            continue
        won, lost, games = won + int(counts[0]), lost + int(counts[1]), games + 1
        if len(counts) >= 3:
            lvps, lvp_games = lvps + int(counts[2]), lvp_games + 1
    return {"won": won, "lost": lost, "games": games, "lvps": lvps, "lvp_games": lvp_games}
