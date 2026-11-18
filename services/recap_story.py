"""Build the facts packet, story angle and output checks for AI match recaps.

Everything numeric is computed here so the language model never does arithmetic,
and every number it writes can be checked against the packet it was given.
"""

from collections import Counter
import re

HEADLINE_MAX_WORDS = 8
BODY_MIN_WORDS = 70
BODY_MAX_WORDS = 200
BODY_MAX_CHARS = 1500

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
         "ninety": 90}
_SPELLED = re.compile(
    r"\b(?:(" + "|".join(_TENS) + r")(?:[- ](" + "|".join(k for k in _UNITS if _UNITS[k] < 10) + r"))?|("
    + "|".join(_UNITS) + r"))\b",
    re.IGNORECASE,
)
_DIGITS = re.compile(r"\d+(?:\.\d+)?")
# "one" and "two" are ordinary prose ("one round", "two ranks below"); bigger spelled numbers are claims.
_SPELLED_MINIMUM = 3


def _kd(kills, deaths):
    return f"{kills / deaths:.2f}" if deaths else None


def _outcome(facts):
    score = facts.get("rounds") or {}
    won, lost = score.get("won"), score.get("lost")
    if type(won) is int and type(lost) is int and min(won, lost) >= 0 and won + lost:
        return ("win" if won > lost else "loss" if won < lost else "draw"), won, lost
    return None, won, lost


def _kill_weapon(event):
    weapon = event.get("weapon")
    if isinstance(weapon, dict) and str(weapon.get("type") or "Weapon").casefold() == "weapon":
        name = weapon.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _round_events(detail):
    """Kill events with 1-based round numbers, grouped by round in time order."""
    events = detail.get("kills") or []
    round_ids = [row.get("id", index) for index, row in enumerate(detail.get("rounds") or [])]
    zero_based = 0 in round_ids or any(event.get("round") == 0 for event in events)
    by_round = {}
    for event in events:
        number = event.get("round")
        if not isinstance(number, int):
            continue
        by_round.setdefault(number + 1 if zero_based else number, []).append(event)
    for rows in by_round.values():
        rows.sort(key=lambda event: event.get("time_in_round_in_ms") if isinstance(
            event.get("time_in_round_in_ms"), (int, float)) else float("inf"))
    return by_round


def _round_winners(detail):
    rounds = detail.get("rounds") or []
    round_ids = [row.get("id", index) for index, row in enumerate(rounds)]
    offset = int(0 in round_ids)
    return {rid + offset: str(row.get("winning_team")).casefold()
            for rid, row in zip(round_ids, rounds) if isinstance(rid, int) and row.get("winning_team")}


def player_round_stats(detail, teammates, team_id):
    """Per-player first bloods, weapon kills, per-round K/D and clutch record from kill events."""
    ids = {p.get("puuid") for p in teammates if p.get("puuid")}
    stats = {pid: {"first_bloods": 0, "weapons": Counter(), "round_kills": Counter(), "round_deaths": Counter(),
                   "clutches": [0, 0]} for pid in ids}
    side = str(team_id or "").casefold()
    rosters = {}
    for player in detail.get("players") or []:
        if player.get("puuid") and player.get("team_id"):
            rosters.setdefault(str(player["team_id"]).casefold(), set()).add(player["puuid"])
    full_rosters = side in rosters and len(rosters) == 2 and all(len(r) == 5 for r in rosters.values())
    enemy_side = next((team for team in rosters if team != side), None)
    winners = _round_winners(detail)
    for number, events in _round_events(detail).items():
        timed = all(isinstance(e.get("time_in_round_in_ms"), (int, float)) for e in events)
        if events and timed:
            first = (events[0].get("killer") or {}).get("puuid")
            if first in stats:
                stats[first]["first_bloods"] += 1
        alive = {team: set(members) for team, members in rosters.items()} if full_rosters and timed else None
        clutcher = None
        for event in events:
            killer = (event.get("killer") or {}).get("puuid")
            victim = (event.get("victim") or {}).get("puuid")
            if killer in stats:
                stats[killer]["round_kills"][number] += 1
                weapon = _kill_weapon(event)
                if weapon:
                    stats[killer]["weapons"][weapon] += 1
            if victim in stats:
                stats[victim]["round_deaths"][number] += 1
            if alive is not None:
                for members in alive.values():
                    members.discard(victim)
                ours, theirs = alive[side], alive[enemy_side]
                if clutcher is None and len(ours) == 1 and theirs:
                    survivor = next(iter(ours))
                    if survivor in stats:
                        clutcher = survivor
        if clutcher and number in winners:
            stats[clutcher]["clutches"][1] += 1
            stats[clutcher]["clutches"][0] += winners[number] == side
    return stats


def _half_split(stat, rounds_total):
    if not rounds_total or rounds_total <= 12:
        return None
    first = [sum(v for r, v in stat[key].items() if r <= 12) for key in ("round_kills", "round_deaths")]
    second = [sum(v for r, v in stat[key].items() if 12 < r <= 24) for key in ("round_kills", "round_deaths")]
    return first, second


def _top_multikills(facts):
    plays = []
    for item in facts.get("round_highlights") or []:
        for play in item.get("multikills", []):
            if play.get("player") and play["player"] != "Unknown":
                weapons = play.get("weapon_kills") or {}
                weapon = max(weapons, key=weapons.get) if weapons else None
                plays.append({"round": item["round"], "player": play["player"], "kills": play["kills"],
                              "ace": bool(play.get("ace")), "weapon": weapon})
    plays.sort(key=lambda p: (-p["ace"], -p["kills"], p["round"]))
    return plays


def pick_story_angles(facts, players, recap_context=None, squad_context=None, limit=2):
    """Rank the available story angles and return the strongest ones as plain sentences.

    ``players`` maps each teammate's name to the derived line data built in ``build_facts_packet``.
    """
    outcome, won, lost = _outcome(facts)
    candidates = []
    for row in recap_context or []:
        name = row.get("player")
        player = players.get(name)
        if not player:
            continue
        changes = row.get("rank_changes") or []
        if changes:
            change = changes[-1]
            when, direction, to_rank = change.get("when"), change.get("direction"), change.get("to_rank")
            line = player.get("kda_text")
            tail = f", then went {line} in this {outcome}" if line and outcome else ""
            if when == "this match":
                candidates.append((90 if direction == "down" else 75,
                                   f"{name} ranked {direction} to {to_rank} on this match"))
            elif direction == "up" and outcome == "loss":
                candidates.append((100, f"{name} ranked up to {to_rank} {when}{tail}"))
            elif direction == "down" and outcome == "win":
                candidates.append((70, f"{name} ranked down to {to_rank} {when}{tail}"))
        streak = row.get("streak_entering_match")
        if streak and outcome in ("win", "loss"):
            results = "wins" if streak["outcome"] == "win" else "losses"
            if streak["outcome"] != outcome:
                candidates.append((65, f"{name} came in on {streak['games']} straight {results} "
                                       f"and this one was a {outcome}"))
            elif streak["games"] >= 3:
                candidates.append((55, f"{name} came in on {streak['games']} straight {results} "
                                       f"and added another {outcome}"))

    for name, player in players.items():
        after = player.get("after_big_round")
        if after and after["kd"] is not None and float(after["kd"]) < 1:
            play = after["play"]
            gear = f" with the {play['weapon']}" if play["weapon"] else ""
            label = (f"aced round {play['round']}" if play["ace"]
                     else f"dropped a {play['kills']}K in round {play['round']}")
            candidates.append((95 if play["ace"] else 85,
                               f"{name} {label}{gear}, then went {after['kd']} KD for the rest of the match"))
        kd, deaths = player.get("kd"), player.get("deaths") or 0
        if player.get("first_bloods", 0) >= 3 and kd is not None and float(kd) < 0.9:
            candidates.append((60, f"{name} took {player['first_bloods']} first bloods but finished at {kd} KD"))
        if deaths >= 14 and kd is not None and float(kd) <= 0.5:
            candidates.append((72, f"{name} went {player['kda_text']}"))
        if player.get("is_smurf") and kd is not None:
            if player.get("poor_smurf_performance"):
                candidates.append((80, f"{name} was on a smurf account and still went {player['kda_text']}"))
            elif float(kd) >= 1.5:
                candidates.append((55, f"{name} was on a smurf account and went {player['kda_text']}"))
        acs = player.get("acs") or 0
        if kd is not None and float(kd) >= 1.5 and acs >= 260:
            candidates.append((55 if outcome == "win" else 50,
                               f"{name} carried with {player['kda_text']} and {acs} ACS"))
        clutch_won, clutch_tries = player.get("clutches") or (0, 0)
        if clutch_tries >= 3 and clutch_won == 0:
            candidates.append((58, f"{name} went 0/{clutch_tries} in clutches"))
        elif clutch_won >= 2:
            candidates.append((60, f"{name} won {clutch_won}/{clutch_tries} clutches"))

    halves = facts.get("half_results")
    if halves and outcome:
        (h1w, h1l), (h2w, h2l) = halves["first_half"], halves["second_half"]
        if h2w == 0 and h2l >= 3 and outcome == "loss":
            candidates.append((88, f"the team won 0 rounds in the second half ({h2w}-{h2l})"))
        elif h1w > h1l and outcome == "loss":
            candidates.append((85, f"the team led {h1w}-{h1l} at halftime and still lost {won}-{lost}"))
        elif h1w < h1l and outcome == "win":
            candidates.append((85, f"the team trailed {h1w}-{h1l} at halftime and came back to win {won}-{lost}"))
        elif h2l == 0 and h2w >= 3 and outcome == "win":
            candidates.append((60, f"the team dropped 0 rounds in the second half ({h2w}-{h2l})"))

    squad_context = squad_context or {}
    if squad_context.get("history"):
        candidates.append((64, squad_context["history"].rstrip(".")))
    callback = squad_context.get("callback")
    if callback:
        candidates.append((62, f"squad lore \"{callback['label']}\" applies: {callback['match_evidence'].rstrip('.')}"))

    if not candidates and players and outcome:
        name, top = max(players.items(), key=lambda item: item[1].get("acs") or 0)
        if top.get("acs"):
            candidates.append((10, f"{name} led the squad with {top['acs']} ACS in a {won}-{lost} {outcome}"))
    ranked = sorted(candidates, key=lambda item: -item[0])
    return list(dict.fromkeys(text for _, text in ranked))[:limit]


def build_facts_packet(detail, teammates, representative, facts, recap_context=None, squad_context=None):
    """Return the text packet sent to the model and the derived per-player data."""
    outcome, won, lost = _outcome(facts)
    rounds_total = won + lost if outcome else None
    stats = player_round_stats(detail, teammates, representative.get("team_id"))
    plays = _top_multikills(facts)
    players = {}
    for source, fact in zip(teammates, facts.get("teammates") or []):
        name = fact.get("name")
        if not name:
            continue
        stat = stats.get(source.get("puuid"))
        info = dict(fact)
        kills, deaths, assists = fact.get("kills"), fact.get("deaths"), fact.get("assists")
        info["kd"] = _kd(kills, deaths) if kills is not None and deaths is not None else None
        if kills is not None and deaths is not None:
            kda = f"{kills}/{deaths}/{assists}" if assists is not None else f"{kills}/{deaths}"
            info["kda_text"] = f"{kda} ({info['kd']} KD)" if info["kd"] else kda
        if stat:
            info["first_bloods"] = stat["first_bloods"]
            if stat["clutches"][1]:
                info["clutches"] = tuple(stat["clutches"])
            if stat["weapons"]:
                weapon, count = stat["weapons"].most_common(1)[0]
                info["best_weapon"] = (weapon, count)
            split = _half_split(stat, rounds_total)
            if split and sum(split[0]) + sum(split[1]):
                info["halves"] = split
            big = next((p for p in plays if p["player"] == name and p["kills"] >= 4), None)
            if big and kills is not None and deaths is not None:
                rest_k = kills - stat["round_kills"][big["round"]]
                rest_d = deaths - stat["round_deaths"][big["round"]]
                if rest_k >= 0 and rest_d > 0:
                    info["after_big_round"] = {"play": big, "kills": rest_k, "deaths": rest_d,
                                               "kd": _kd(rest_k, rest_d)}
        players[name] = info

    angles = pick_story_angles(facts, players, recap_context, squad_context)
    lines = []
    if outcome:
        word = {"win": "Victory", "loss": "Defeat", "draw": "Draw"}[outcome]
        lines.append(f"RESULT: {word} {won}-{lost}" + (f" on {facts['map']}" if facts.get("map") else ""))
    elif facts.get("map"):
        lines.append(f"RESULT: unknown score on {facts['map']}")
    if angles:
        lines.append(f"STORY_ANGLE: {angles[0]}")
    if len(angles) > 1:
        lines.append(f"SECOND_ANGLE: {angles[1]}")
    halves = facts.get("half_results")
    if halves:
        (h1w, h1l), (h2w, h2l) = halves["first_half"], halves["second_half"]
        lines.append(f"HALVES: first half {h1w}-{h1l}, second half {h2w}-{h2l}")
    if players:
        lines.append("PLAYERS:")
    for name, info in players.items():
        parts = []
        if info.get("kda_text"):
            parts.append(info["kda_text"])
        if info.get("acs") is not None:
            parts.append(f"{info['acs']} ACS")
        if "first_bloods" in info:
            fb = info["first_bloods"]
            parts.append(f"{fb} first blood{'s' if fb != 1 else ''}")
        if info.get("clutches"):
            parts.append(f"clutches {info['clutches'][0]}/{info['clutches'][1]}")
        if info.get("halves"):
            (k1, d1), (k2, d2) = info["halves"]
            parts.append(f"first half {k1}/{d1}, second half {k2}/{d2}")
        after = info.get("after_big_round")
        if after:
            parts.append(f"after round {after['play']['round']}: {after['kills']}/{after['deaths']}"
                         + (f" ({after['kd']} KD)" if after["kd"] else ""))
        if info.get("best_weapon"):
            weapon, count = info["best_weapon"]
            parts.append(f"best weapon {weapon} ({count} kills)")
        if info.get("is_smurf"):
            parts.append("playing on a smurf account")
        agent = f" ({info['agent']})" if info.get("agent") else ""
        lines.append(f"- {name}{agent}: " + ", ".join(parts) if parts else f"- {name}{agent}")
    if plays:
        lines.append("MULTIKILLS:")
        for play in plays[:4]:
            label = "ace" if play["ace"] else f"{play['kills']}K"
            gear = f" ({play['weapon']})" if play["weapon"] else ""
            lines.append(f"- {play['player']} {label} in round {play['round']}{gear}")
    acs_values = [info["acs"] for info in players.values() if info.get("acs") is not None]
    if len(acs_values) >= 2:
        lines.append(f"SQUAD_AVG_ACS: {round(sum(acs_values) / len(acs_values))}")
    for row in recap_context or []:
        name = row.get("player")
        if name not in players:
            continue
        for change in row.get("rank_changes") or []:
            lines.append(f"RANK: {name} ranked {change['direction']} from {change['from_rank']} to "
                         f"{change['to_rank']} {change['when']}")
        streak = row.get("streak_entering_match")
        if streak:
            results = "wins" if streak["outcome"] == "win" else "losses"
            lines.append(f"STREAK: {name} came in on {streak['games']} straight {results}")
    squad_context = squad_context or {}
    if squad_context.get("history"):
        lines.append(f"HISTORY: {squad_context['history']}")
    callback = squad_context.get("callback")
    if callback:
        who = f" -> {callback['player']}" if callback.get("player") else ""
        lines.append(f"LORE: \"{callback['label']}\" ({callback['kind']}){who}; "
                     f"evidence: {callback['match_evidence']}")
    if squad_context.get("games_together"):
        lines.append(f"TOGETHER: {squad_context['games_together']} games")
    return "\n".join(lines), players


def numbers_in(text, exempt=()):
    """Every number claimed in ``text``: digits plus spelled-out numbers from three upward."""
    for phrase in sorted(exempt, key=len, reverse=True):
        if phrase:
            text = re.sub(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", " ", text, flags=re.IGNORECASE)
    found = {float(match) for match in _DIGITS.findall(text)}
    for tens, unit, single in _SPELLED.findall(text):
        value = _TENS[tens.casefold()] + _UNITS[unit.casefold()] if tens and unit else (
            _TENS[tens.casefold()] if tens else _UNITS[single.casefold()])
        if value >= _SPELLED_MINIMUM:
            found.add(float(value))
    return found


def validate_recap(output, packet, *, names=(), other_names=(), labels=()):
    """Return ``(recap, problems)``. ``recap`` is None when any check fails."""
    if not isinstance(output, dict):
        return None, ["the answer was not a JSON object"]
    headline, body = output.get("headline"), output.get("body")
    if not isinstance(headline, str) or not isinstance(body, str):
        return None, ["headline and body must both be strings"]
    headline = " ".join(headline.split()).upper()
    body = re.sub(r"@(?=\w)", "", " ".join(body.split()))
    problems = []
    if not headline or len(headline.split()) > HEADLINE_MAX_WORDS:
        problems.append(f"the headline must be 1-{HEADLINE_MAX_WORDS} words")
    words = len(body.split())
    if not BODY_MIN_WORDS <= words <= BODY_MAX_WORDS or len(body) > BODY_MAX_CHARS:
        problems.append(f"the body had {words} words; it must be {BODY_MIN_WORDS}-{BODY_MAX_WORDS} words")
    exempt = set(names) | set(labels)
    allowed = numbers_in(packet, exempt)
    invented = sorted(numbers_in(f"{headline} {body}", exempt) - allowed)
    if invented:
        shown = ", ".join(f"{n:g}" for n in invented)
        problems.append(f"numbers not in FACTS: {shown}")
    plain = f"{headline} {body}"
    for phrase in sorted(exempt, key=len, reverse=True):
        plain = re.sub(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", " ", plain, flags=re.IGNORECASE)
    strangers = sorted(n for n in other_names if re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", plain, re.I))
    if strangers:
        problems.append("mentioned players not in PLAYERS")
    if problems:
        return None, problems
    return {"headline": headline, "recap": body}, []
