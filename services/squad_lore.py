"""Track shared match history and pick contextual callbacks for recaps."""

from datetime import timezone
from itertools import takewhile
import json
import re


TRIGGERS = {
    "win": "Match win",
    "loss": "Match loss",
    "ace": "Ace",
    "rough_game": "Rough game",
    "clutch_win": "Clutch round won",
    "thrifty_win": "Thrifty round won",
}
MAX_ENTRIES = 12
BETWEEN_CALLBACKS = 3
BETWEEN_SAME_CALLBACK = 6
MAP_RESULT_LIMIT = 6


def _outcome(facts):
    score = facts.get("rounds") or {}
    won, lost = score.get("won"), score.get("lost")
    if type(won) is int and type(lost) is int and min(won, lost) >= 0 and won + lost:
        return "win" if won > lost else "loss" if won < lost else "draw"
    return None


def _trigger_detail(entry, player, outcome, facts):
    trigger = entry["trigger"]
    if trigger == outcome and trigger in ("win", "loss"):
        return f"The team recorded a {outcome}."
    if trigger == "ace":
        for item in facts["round_highlights"]:
            for play in item.get("multikills", []):
                if play.get("ace") and (player is None or play["player"] == player):
                    return f"{play['player']} aced in round {item['round']}."
    if trigger == "rough_game":
        for teammate in facts["teammates"]:
            if ((player is None or teammate["name"] == player) and teammate.get("deaths", 0) >= 10
                    and teammate.get("match_kd", 1) <= 0.60):
                return f"{teammate['name']} finished with {teammate['kills']} kills and {teammate['deaths']} deaths."
    if trigger in ("clutch_win", "thrifty_win") and player is None:
        kind = trigger.removesuffix("_win")
        for item in facts.get("special_round_wins", []):
            if item["team_win_type"] == kind:
                return f"Round {item['round']} was a {kind} win for the team."
    return None


def _pick_entry(entries, memory, members, outcome, facts):
    post = memory["posts"]
    last_callback = memory.get("last_callback")
    if last_callback is not None and post - last_callback <= BETWEEN_CALLBACKS:
        return None
    usage = memory.get("used", {})
    eligible = []
    for key, entry in entries.items():
        last_use = usage.get(key)
        if last_use is not None and post - last_use <= BETWEEN_SAME_CALLBACK:
            continue
        if entry.get("map") and entry["map"].casefold() != (facts.get("map") or "").casefold():
            continue
        member_id = entry.get("member_id")
        player = members.get(member_id)
        if member_id and (not player or list(members.values()).count(player) != 1):
            continue
        evidence = _trigger_detail(entry, player, outcome, facts)
        if evidence:
            eligible.append((key, {"label": entry["label"], "kind": entry["kind"], "player": player,
                                   "match_evidence": evidence}))
    if eligible:
        return eligible[(post - 1) % len(eligible)]
    return None


def _record_lineup(lineups, members, match_id, started, outcome, map_name):
    key = json.dumps(sorted(members))
    previous = lineups.get(key, {})
    games = previous.get("games", 0) + 1
    maps = dict(previous.get("maps", {}))
    losses = 0
    newest = True
    if map_name:
        map_key = map_name.casefold()
        results = maps.get(map_key, [])
        result = [started.astimezone(timezone.utc).isoformat(), str(match_id), outcome]
        results = sorted([row for row in results if row[1] != result[1]] + [result], reverse=True)[:MAP_RESULT_LIMIT]
        maps[map_key] = results
        newest = results[0] == result
        losses = sum(1 for _ in takewhile(lambda row: row[2] == "loss", results[1:]))
    lineups[key] = {"games": games, "maps": maps}
    if newest and map_name:
        if outcome == "win" and losses >= 3:
            prefix = "at least " if losses == MAP_RESULT_LIMIT - 1 else ""
            return f"This lineup broke a run of {prefix}{losses} recorded losses on {map_name}."
        if outcome == "loss" and losses + 1 in (3, 5):
            ordinal = "third" if losses == 2 else "fifth"
            return f"This was the lineup's {ordinal} recorded loss in a row on {map_name}."
    if games in (5, 10, 25) or games % 50 == 0:
        return f"This was the {games}th match recorded for this lineup."
    return None


def prepare_squad_context(feed, members, match_id, started, facts):
    """Calculate the state for a posted card without mutating the persisted feed."""
    previous = (feed.get("match_counts") or {}).get("squad_memory") or {}
    entries = feed.get("squad_lore") or {}
    memory = {
        "posts": previous.get("posts", 0) + 1,
        "last_callback": previous.get("last_callback"),
        "used": {key: at for key, at in (previous.get("used") or {}).items() if key in entries},
        "lineups": dict(previous.get("lineups") or {}),
    }
    outcome = _outcome(facts)
    together = {}
    if len(members) >= 2 and outcome:
        history = _record_lineup(memory["lineups"], members, match_id, started, outcome, facts.get("map"))
        together = {"games_together": memory["lineups"][json.dumps(sorted(members))]["games"]}
        if history:
            return memory, {"history": history, **together}, None
    choice = _pick_entry(entries, memory, members, outcome, facts)
    if choice:
        key, callback = choice
        return memory, {"callback": callback, **together}, key
    return memory, together, None


def remember_squad_callback(memory, key):
    memory["used"][key] = memory["posts"]
    memory["last_callback"] = memory["posts"]


def squad_callback_used(squad_context, story):
    callback = (squad_context or {}).get("callback")
    return bool(callback and re.search(r"(?<!\w)" + re.escape(callback["label"]) + r"(?!\w)", story, re.IGNORECASE))
