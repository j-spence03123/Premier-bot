"""Weekly recap awards: one player of the week and one roast award each for the rest of the squad.

Player of the week leads the most of ``POTW_STATS`` (headshot rate is left out); ties go to the best average placing. Roast awards are
handed out once each and at most one per player: rarer event awards first, then stat awards among whoever is
still empty-handed. Only main accounts take part.
"""

from collections import Counter

POTW_MIN_GAMES = 5
POTW_MIN_LEADS = 2  # leading fewer stats than this hands player of the week to the biggest RR climber
CAMEO_MAX_GAMES = 3
TILT_MIN_STREAK = 4
CLUTCH_ZERO_MIN_CHANCES = 5
FREE_FALL_MIN_LOSS = 30  # RR; a -1 week is not a free fall
LVP_MAGNET_MIN = 3  # bottom of the team's scoreboard at least this many times
PASSENGER_MAX_ACS = 180
CARRIED_MAX_KD = 0.9  # winning record on a KD below this
KD_PLAYER_MIN_KD = 1.15  # losing record on a KD at or above this
BODY_SHOOTER_MAX_HS = 25  # %; at or above this the aim is fine, whatever the squad ranking says

# key, tile label, value format, noun used in the blurb
POTW_STATS = (
    ("rr", "RR", lambda value: f"{value:+d}", "RR"),
    ("kd", "KD", lambda value: f"{value:.2f}", "KD"),
    ("acs", "ACS", lambda value: f"{value:.0f}", "ACS"),
    ("adr", "ADR", lambda value: f"{value:.0f}", "ADR"),
    ("wr", "WIN %", lambda value: f"{value:.0f}%", "win rate"),
)


def _plural(count, word):
    return f"{count} {word}" + ("" if count == 1 else "s")


def player_stats(player):
    """Weekly averages for one collected player (``collect_player_data`` row)."""
    games = sorted(player.get("games") or [], key=lambda game: game.get("started_at") or 0)
    count = len(games)
    kills, deaths = sum(game["k"] for game in games), sum(game["d"] for game in games)
    streak = longest = 0
    for game in games:
        streak = streak + 1 if game.get("won") is False else 0
        longest = max(longest, streak)
    agents = Counter(game.get("agent") for game in games if game.get("agent") not in (None, "?"))
    agent = agents.most_common(1)[0][0] if agents else None
    agent_id = next((game.get("agent_id") for game in games if game.get("agent") == agent and game.get("agent_id")),
                    None)
    average = (lambda key: sum(game.get(key, 0) for game in games) / count) if count else (lambda key: 0)
    return {
        "name": player["name"], "games": count, "rr": player.get("rr"),
        "kd": kills / max(deaths, 1), "acs": average("acs"), "adr": average("adr"), "hs": average("hs"),
        "wr": 100 * sum(game.get("won") is True for game in games) / count if count else 0,
        "wins": sum(game.get("won") is True for game in games),
        "losses": sum(game.get("won") is False for game in games), "loss_streak": longest,
        "agent": agent, "agent_id": agent_id,
        "clutch": player.get("clutch"), "rank_swing": player.get("rank_swing"),
    }


def _value(stats, key):
    value = stats[key]
    return float("-inf") if value is None else value


def player_of_the_week(stats):
    """``(stats, leads, eligible, by_rr)`` for the winner, or None with fewer than two eligible players.

    The winner leads the most stats. If that is fewer than ``POTW_MIN_LEADS``, nobody had a standout week and the
    award goes to the most RR gained instead (``by_rr`` is then True).
    """
    eligible = [row for row in stats if row["games"] >= POTW_MIN_GAMES]
    if len(eligible) < 2:
        return None
    leads = {id(row): [] for row in eligible}
    placing = {id(row): 0 for row in eligible}
    for key, *_ in POTW_STATS:
        best = max(_value(row, key) for row in eligible)
        for row in eligible:
            if row[key] is not None and _value(row, key) == best:
                leads[id(row)].append(key)
            placing[id(row)] += sum(_value(other, key) > _value(row, key) for other in eligible)
    winner = max(eligible, key=lambda row: (len(leads[id(row)]), -placing[id(row)], row["games"]))
    by_rr = False
    climbers = [row for row in eligible if row["rr"] is not None]
    if len(leads[id(winner)]) < POTW_MIN_LEADS and climbers:
        winner = max(climbers, key=lambda row: (row["rr"], -placing[id(row)], row["games"]))
        by_rr = True
    return winner, leads[id(winner)], eligible, by_rr


def climber_blurb(winner, leads):
    games = _plural(winner["games"], "game")
    if winner["rr"] > 0:
        text = f"{winner['rr']:+d} RR over {games}, the biggest climb in the squad."
    else:
        text = f"Nobody climbed this week, but {winner['rr']:+d} RR over {games} was the smallest loss."
    rest = [noun for key, _, _, noun in POTW_STATS if key in leads and key != "rr"]
    if rest:
        text += " Also top of the squad in " + (", ".join(rest[:-1]) + " and " + rest[-1] if len(rest) > 1
                                                else rest[0]) + "."
    return text


def potw_blurb(winner, leads, eligible):
    others = [row for row in eligible if row is not winner]
    margins = []
    for key, _, fmt, noun in POTW_STATS:
        if key not in leads:
            continue
        second = max(_value(row, key) for row in others)
        if second == float("-inf"):
            continue
        margins.append(((winner[key] - second) / max(abs(second), 1), key, fmt, noun, second))
    games = _plural(winner["games"], "game")
    if not margins:
        return f"Never top of a single stat, but the most consistent across the board over {games}."
    _, key, fmt, noun, second = max(margins, key=lambda margin: margin[0])
    text = f"{fmt(winner[key])} {noun} and nobody else got past {fmt(second)}."
    rest = [margin[3] for margin in margins if margin[1] != key]
    if rest:
        listed = ", ".join(rest[:-1]) + " and " + rest[-1] if len(rest) > 1 else rest[0]
        text += f" Also top of the squad in {listed} across {games}."
    else:
        text += f" Best all-round placing across {games}."
    if len(leads) * 2 >= len(POTW_STATS):
        text += " Clearest week in the room."
    return text


def _event_candidates(row):
    """``(weight, award, label, value, line)`` for the rare awards this player qualifies for."""
    found = []
    swing = row.get("rank_swing")
    if swing:
        lasted = swing["drop_game"] - swing["peak_game"]
        found.append((100, "YO-YO", "PEAKED", swing["peak"],
                      f"{swing['peak']} by game {swing['peak_game']}, {swing['end']} by game {swing['drop_game']}. "
                      f"{_plural(lasted, 'game')} was all it lasted."))
    if row["loss_streak"] >= TILT_MIN_STREAK:
        found.append((90 + row["loss_streak"], "ON TILT", "LOSS STREAK", str(row["loss_streak"]),
                      f"Lost {row['loss_streak']} in a row and kept queueing through every one of them."))
    clutch = row.get("clutch") or {}
    chances = clutch.get("won", 0) + clutch.get("lost", 0)
    if clutch.get("won") == 0 and chances >= CLUTCH_ZERO_MIN_CHANCES:
        found.append((85, "CLUTCH ZERO", "CLUTCHES", f"0/{chances}",
                      f"{chances} clutch chances across {_plural(clutch['games'], 'game')} "
                      "and converted exactly none of them."))
    record = f"{row['wins']}W {row['losses']}L"
    if row["games"] >= POTW_MIN_GAMES and row["wins"] > row["losses"] and row["kd"] < CARRIED_MAX_KD:
        # Weighted below the rare awards; a weaker KD makes a stronger case.
        found.append((55 + (CARRIED_MAX_KD - row["kd"]), "CARRIED", "RECORD", record,
                      f"{record} on a {row['kd']:.2f} KD. Make sure to thank your teammates."))
    if row["games"] >= POTW_MIN_GAMES and row["wins"] < row["losses"] and row["kd"] >= KD_PLAYER_MIN_KD:
        found.append((55 + (row["kd"] - KD_PLAYER_MIN_KD), "KD PLAYER", "KD", f"{row['kd']:.2f}",
                      f"{row['kd']:.2f} KD and a {record} record. The stats look great, the scoreboard disagrees."))
    if 0 < row["games"] <= CAMEO_MAX_GAMES:
        found.append((60, "CAMEO", "GAMES", str(row["games"]),
                      f"Logged on for {_plural(row['games'], 'game')} and called it a week."))
    return found


# award, stat, worst end ("low" or "high"), label, value format, line(row, worst_in_squad)
STAT_AWARDS = (
    ("BOTTOM FRAG", "kd", "low", "KD", lambda value: f"{value:.2f}",
     lambda row, worst: ("Lowest KD in the squad" if worst else "{:.2f} KD".format(row["kd"]))
                        + f" over {_plural(row['games'], 'game')}. The enemy team's favourite teammate."),
    ("BODY SHOOTER", "hs", "low", "HEADSHOT %", lambda value: f"{value:.1f}%",
     lambda row, worst: "Aiming at the chest like it pays rent. "
                        + ("Lowest headshot rate in the squad." if worst else f"{row['hs']:.0f}% headshots all week.")),
    ("PASSENGER", "acs", "low", "ACS", lambda value: f"{value:.0f}",
     lambda row, worst: f"{row['acs']:.0f} ACS across {_plural(row['games'], 'game')}. "
                        "Enjoyed the ride, never touched the wheel."),
    ("NO LIFE", "games", "high", "MOST ACTIVE", lambda value: _plural(value, "game"),
     lambda row, worst: f"{_plural(row['games'], 'game')} and only {_plural(row['wins'], 'win')} to show for it."),
)


# Stat awards a player must actually deserve, not just be worst-placed among whoever is left.
STAT_AWARD_LIMITS = {
    "BODY SHOOTER": lambda row: row["hs"] < BODY_SHOOTER_MAX_HS,
    "PASSENGER": lambda row: row["acs"] < PASSENGER_MAX_ACS,
    "NO LIFE": lambda row: row["wins"] < row["losses"],  # grinding a winning week is not a roast
}


NPC_LINES = (
    "{kd} KD, {acs} ACS, {record}. Perfectly average, completely forgettable.",
    "{record} with a {kd} KD. Showed up, clicked some heads, left no trace.",
    "Not good enough for the crown, not bad enough for a roast. {record}, {acs} ACS.",
)


def npc_line(row):
    """A deterministic pick so the same week always renders the same text."""
    record = f"{row['wins']}W {row['losses']}L"
    template = NPC_LINES[sum(map(ord, row["name"])) % len(NPC_LINES)]
    return template.format(kd=f"{row['kd']:.2f}", acs=f"{row['acs']:.0f}", record=record)


def roast_awards(stats, exclude=None):
    awards, taken_players, taken_awards = [], set(), set()

    def take(row, award, label, value, line):
        taken_players.add(id(row))
        taken_awards.add(award)
        awards.append({"award": award, "player": row["name"], "agent": row["agent"], "agent_id": row["agent_id"],
                       "label": label, "value": value, "line": line})

    candidates = [(weight, award, label, value, line, row)
                  for row in stats if row is not exclude
                  for weight, award, label, value, line in _event_candidates(row)]
    lvp_counts = [row for row in stats
                  if row is not exclude and (row.get("clutch") or {}).get("lvps", 0) >= LVP_MAGNET_MIN]
    if lvp_counts:
        row = max(lvp_counts, key=lambda row: (row["clutch"]["lvps"],
                                               row["clutch"]["lvps"] / row["clutch"]["lvp_games"]))
        lvps, counted = row["clutch"]["lvps"], row["clutch"]["lvp_games"]
        candidates.append((88, "LVP MAGNET", "LVPS", f"{lvps}/{counted}",
                           f"Bottom of the team's scoreboard in {lvps} of {_plural(counted, 'game')}. "
                           "Someone has to hold it up.", row))
    fallers = [row for row in stats if row is not exclude and row["games"] and row["rr"] is not None]
    if fallers:
        row = min(fallers, key=lambda row: row["rr"])
        if row["rr"] <= -FREE_FALL_MIN_LOSS:
            candidates.append((80, "FREE FALL", "RR", f"{row['rr']:+d}",
                               f"Shed {-row['rr']} RR this week. Gravity remains undefeated.", row))
    for weight, award, label, value, line, row in sorted(candidates, key=lambda item: -item[0]):
        if id(row) not in taken_players and award not in taken_awards:
            take(row, award, label, value, line)
    # Stat awards: whoever is left gets the stat they rank worst in, worst placings settled first.
    field = [row for row in stats if row is not exclude and row["games"] >= POTW_MIN_GAMES]
    ranked = []
    for order, (award, key, end, label, fmt, line) in enumerate(STAT_AWARDS):
        ordered = sorted(field, key=lambda row: row[key], reverse=end == "high")
        for place, row in enumerate(ordered):
            ranked.append((place, order, row, award, label, fmt(row[key]), line(row, place == 0)))
    for _, _, row, award, label, value, line in sorted(ranked, key=lambda item: item[:2]):
        if not STAT_AWARD_LIMITS.get(award, lambda row: True)(row):
            continue
        if id(row) not in taken_players and award not in taken_awards:
            take(row, award, label, value, line)
    # Anyone who played but fits nothing gets the NPC card; unlike the others it can go to several players.
    for row in stats:
        if row is not exclude and row["games"] and id(row) not in taken_players:
            take(row, "NPC", "RECORD", f"{row['wins']}W {row['losses']}L", npc_line(row))
    return awards


def build_awards(players):
    """Awards for the card, or None when too few main accounts played enough to compare."""
    stats = [player_stats(player) for player in players if not player.get("smurf")]
    stats = [row for row in stats if row["games"]]
    picked = player_of_the_week(stats)
    if not picked:
        return None
    winner, leads, eligible, by_rr = picked
    return {
        "player_of_the_week": {
            "player": winner["name"], "agent": winner["agent"], "agent_id": winner["agent_id"],
            "leads": leads, "games": winner["games"], "by_rr": by_rr,
            "line": climber_blurb(winner, leads) if by_rr else potw_blurb(winner, leads, eligible),
            "stats": [{"key": key, "label": label, "value": "–" if winner[key] is None else fmt(winner[key]),
                       "lead": key in leads} for key, label, fmt, _ in POTW_STATS],
        },
        "awards": roast_awards(stats, exclude=winner),
    }
