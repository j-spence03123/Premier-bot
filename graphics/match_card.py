import io
import logging
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageOps

from .assets import PLAY_TAG_STYLES, chip_width, draw_soft_box, match_font, readable_font, wrap_image_text
from utils.formatting import parse_time, uk_time
from utils.match_summary import _clutch_rounds, _deaths_by_round, _play_headline, _play_recap


logger = logging.getLogger(__name__)
_reported_gaps = set()


def _report_missing_fields(detail):
    """Log once per process when match data lacks fields some tags depend on, so a dead tag is noticed."""
    kills = detail.get("kills") or []
    players = detail.get("players") or []
    gaps = []
    if kills and not any("assistants" in event for event in kills):
        gaps.append(("assistants", "kill events have no assist lists; TOURIST counts kills only and "
                                   "KILL STEALER can't be awarded"))
    if players and not any("afk_rounds" in (player.get("behavior") or {}) for player in players):
        gaps.append(("afk_rounds", "player behaviour has no afk_rounds; AFK can't be awarded"))
    for key, message in gaps:
        if key not in _reported_gaps:
            _reported_gaps.add(key)
            logger.warning("Match data: %s", message)


# Tags every eligible player keeps, even when a teammate earned the same one.
SHARED_TAGS = {"ACE", "CLUTCH", "VICTIM", "KNIFE", "KNIFED", "AFK"}
OPERATOR_MIN_KILLS = 6
EXIT_FARMER_MIN_KILLS = 6
KNIFE_WEAPONS = {"knife", "melee"}
KNIFE_WEAPON_ID = "2f59173c-4bed-b6c3-2191-dea9b58be9c7"  # valorant-api.com "Melee"
ECO_LOADOUT_RATIO = 0.5
ECO_MIN_KILLER_LOADOUT = 2500
PASSENGER_SCORE_RATIO = 0.8
CHOKER_MIN_LOSSES = 4
KILL_STEALER_MIN_KILLS = 4
MARTYR_MIN_ROUNDS = 3
TOURIST_IDLE_SHARE = 0.6


def _tag_key(tag):
    return tag.split(" x", 1)[0]


def _assign_unique_tags(tracked):
    """Give each tag to one eligible player, balancing tied awards across cards."""
    candidates = {}
    assigned = [[] for _ in tracked]
    for index, item in enumerate(tracked):
        for tag in item["tags"]:
            if _tag_key(tag) in SHARED_TAGS:
                assigned[index].append(tag)
            else:
                candidates.setdefault(_tag_key(tag), []).append((index, tag))
    # Settle uncontested awards before using the current award count for ties.
    for group in sorted(candidates.values(), key=len):
        index, tag = min(group, key=lambda candidate: (len(assigned[candidate[0]]), candidate[0]))
        assigned[index].append(tag)
    for item, tags in zip(tracked, assigned):
        item["tags"] = [tag for tag in item["tags"] if tag in tags]


def _is_knife(weapon):
    """HenrikDev sometimes sends the knife as {"name": None, "type": "Melee"}, so check every field."""
    if not isinstance(weapon, dict):
        return False
    return (str(weapon.get("name") or "").casefold() in KNIFE_WEAPONS
            or str(weapon.get("type") or "").casefold() in KNIFE_WEAPONS
            or str(weapon.get("id") or "").casefold() == KNIFE_WEAPON_ID)


def _round_number(round_data, index):
    number = round_data.get("id")
    return number if isinstance(number, int) else index


def _plants(detail):
    """Count bomb plants per player from the round list."""
    plants = {}
    for round_data in detail.get("rounds") or []:
        planter = ((round_data.get("plant") or {}).get("player") or {}).get("puuid")
        if planter:
            plants[planter] = plants.get(planter, 0) + 1
    return plants


def _loadouts(detail):
    """Map round number -> puuid -> loadout value for that round."""
    loadouts = {}
    for index, round_data in enumerate(detail.get("rounds") or []):
        values = {}
        for row in round_data.get("stats") or []:
            puuid = (row.get("player") or {}).get("puuid")
            value = (row.get("economy") or {}).get("loadout_value")
            if puuid and isinstance(value, (int, float)):
                values[puuid] = value
        if values:
            loadouts[_round_number(round_data, index)] = values
    return loadouts


def _round_winners(detail):
    """Map round number -> casefolded winning team id, for rounds that report one."""
    winners = {}
    for index, round_data in enumerate(detail.get("rounds") or []):
        winner = str(round_data.get("winning_team") or "").casefold()
        if winner:
            winners[_round_number(round_data, index)] = winner
    return winners


def _kill_events(detail):
    """Count Operator, eco, team, knife and lost-round kills per player."""
    team_by_puuid = {p.get("puuid"): p.get("team_id") for p in detail.get("players") or [] if p.get("puuid")}
    loadouts = _loadouts(detail)
    winners = _round_winners(detail)
    operator, eco, team_kills, knife, lost_round = {}, {}, {}, {}, {}
    for event in detail.get("kills") or []:
        killer = (event.get("killer") or {}).get("puuid")
        victim = (event.get("victim") or {}).get("puuid")
        if not killer or not victim or killer == victim:
            continue
        killer_team = team_by_puuid.get(killer) or (event.get("killer") or {}).get("team")
        victim_team = team_by_puuid.get(victim) or (event.get("victim") or {}).get("team")
        if killer_team and killer_team == victim_team:
            team_kills[killer] = team_kills.get(killer, 0) + 1
            continue
        weapon = event.get("weapon") or {}
        weapon_name = str(weapon.get("name") or "").casefold() if isinstance(weapon, dict) else ""
        if weapon_name == "operator":
            operator[killer] = operator.get(killer, 0) + 1
        if _is_knife(weapon):
            knife[killer] = knife.get(killer, 0) + 1
        round_number = event.get("round", 0) or 0
        winner = winners.get(round_number)
        if winner and killer_team and str(killer_team).casefold() != winner:
            lost_round[killer] = lost_round.get(killer, 0) + 1
        values = loadouts.get(round_number, {})
        mine, theirs = values.get(killer), values.get(victim)
        # Eco kill: the killer is on a full buy and the victim is on a much cheaper loadout.
        if mine is not None and theirs is not None and mine >= ECO_MIN_KILLER_LOADOUT \
                and theirs <= mine * ECO_LOADOUT_RATIO:
            eco[killer] = eco.get(killer, 0) + 1
    return operator, eco, team_kills, knife, lost_round


def _roast_events(detail, teammate_ids):
    """Per-teammate counts behind the KNIFED, TOURIST, KILL STEALER and MARTYR tags.

    ``knifed``: times knifed by an enemy. ``involved``: rounds with a kill or an assist. ``stolen``: kills
    that two or more other teammates assisted on. ``martyr``: rounds they died first and the team still won.
    """
    team_by_puuid = {p.get("puuid"): p.get("team_id") for p in detail.get("players") or [] if p.get("puuid")}
    winners = _round_winners(detail)
    counts = {"knifed": {}, "involved": {}, "stolen": {}, "martyr": {}}
    by_round = {}
    for event in detail.get("kills") or []:
        number = event.get("round", 0) or 0
        by_round.setdefault(number, []).append(event)
        killer = (event.get("killer") or {}).get("puuid")
        victim = (event.get("victim") or {}).get("puuid")
        helpers = {helper.get("puuid") for helper in event.get("assistants") or [] if isinstance(helper, dict)}
        helpers &= teammate_ids
        for helper in helpers:
            counts["involved"].setdefault(helper, set()).add(number)
        if killer in teammate_ids and victim and victim not in teammate_ids:
            counts["involved"].setdefault(killer, set()).add(number)
            if len(helpers - {killer}) >= 2:
                counts["stolen"][killer] = counts["stolen"].get(killer, 0) + 1
        if victim in teammate_ids and killer and killer not in teammate_ids:
            if _is_knife(event.get("weapon")):
                counts["knifed"][victim] = counts["knifed"].get(victim, 0) + 1
    for number, events in by_round.items():
        if not all(isinstance(event.get("time_in_round_in_ms"), (int, float)) for event in events):
            continue
        first = min(events, key=lambda event: event["time_in_round_in_ms"])
        victim = (first.get("victim") or {}).get("puuid")
        if victim in teammate_ids and winners.get(number) == str(team_by_puuid.get(victim) or "").casefold():
            counts["martyr"][victim] = counts["martyr"].get(victim, 0) + 1
    return counts


def _friendly_fire(player):
    return ((player.get("behavior") or {}).get("friendly_fire") or {}).get("outgoing") or 0


def _build_tracked(detail, queued_players, all_teammates, round_count, kills_per_round,
                   first_bloods, first_deaths, top_score, low_score):
    """Work out each queued player's stat line and the tags they earned this match."""
    _report_missing_fields(detail)
    deaths_by_round = _deaths_by_round(detail)
    clutch_wins, clutch_losses = _clutch_rounds(detail, all_teammates)
    plants = _plants(detail)
    operator_kills, eco_kills, team_kills, knife_kills, lost_round_kills = _kill_events(detail)
    teammate_ids = {p.get("puuid") for p in all_teammates}

    def team_max(counts):
        return max((counts.get(puuid, 0) for puuid in teammate_ids), default=0)

    roast = _roast_events(detail, teammate_ids)
    knifed, involved, stolen, martyr = roast["knifed"], roast["involved"], roast["stolen"], roast["martyr"]
    most_clutch_losses, most_stolen, most_martyr = team_max(clutch_losses), team_max(stolen), team_max(martyr)
    # Rounds with no kill or assist. Only meaningful when kill events name at least one teammate.
    idle = {puuid: round_count - len(involved.get(puuid, ())) for puuid in teammate_ids} if involved else {}
    most_idle = max(idle.values(), default=0)

    assists_by_id = {p.get("puuid"): (p.get("stats") or {}).get("assists", 0) for p in all_teammates}
    damage_by_id = {
        p.get("puuid"): round(((p.get("stats") or {}).get("damage") or {}).get("dealt", 0) / round_count)
        for p in all_teammates
    }
    most_assists = max(assists_by_id.values(), default=0)
    highest_adr = max(damage_by_id.values(), default=0)
    most_first_bloods = team_max(first_bloods)
    most_first_deaths = team_max(first_deaths)
    most_plants = team_max(plants)
    most_eco_kills = team_max(eco_kills)
    most_team_kills = team_max(team_kills)
    most_lost_round_kills = team_max(lost_round_kills)
    most_friendly_fire = max((_friendly_fire(p) for p in all_teammates), default=0)
    operator_share = {}
    for player in all_teammates:
        puuid = player.get("puuid")
        kills = (player.get("stats") or {}).get("kills", 0)
        if operator_kills.get(puuid, 0) >= OPERATOR_MIN_KILLS and kills:
            share = operator_kills[puuid] / kills
            if share >= 0.4:
                operator_share[puuid] = share
    best_operator = max(operator_share.values(), default=0)
    headshot_rates = {}
    for player in all_teammates:
        stats = player.get("stats") or {}
        shots = sum(stats.get(part, 0) for part in ("headshots", "bodyshots", "legshots"))
        if stats.get("kills", 0) >= 15 and shots:
            headshot_rates[player.get("puuid")] = round(stats.get("headshots", 0) * 100 / shots)
    highest_hs = max(headshot_rates.values(), default=0)
    lowest_hs = min(headshot_rates.values(), default=100)
    lowest_deaths = min(((p.get("stats") or {}).get("deaths", 0) for p in all_teammates), default=0)
    tracked = []
    for p in queued_players:
        st = p.get("stats", {})
        shots = st.get("headshots", 0) + st.get("bodyshots", 0) + st.get("legshots", 0)
        hs = round(st.get("headshots", 0) * 100 / shots) if shots else 0
        tags = []
        puuid = p.get("puuid")
        best_round = max((kills_per_round.get(r, {}).get(puuid, 0) for r in kills_per_round), default=0)
        if best_round >= 5: tags.append("ACE")
        elif best_round == 4: tags.append("QUAD")
        if top_score is not None and st.get("score", 0) == top_score: tags.append("MVP")
        if most_first_bloods >= 3 and first_bloods.get(puuid, 0) == most_first_bloods: tags.append("ENTRY")
        if most_first_deaths >= 4 and first_deaths.get(puuid, 0) == most_first_deaths: tags.append("BAITED")
        if best_operator and operator_share.get(puuid) == best_operator: tags.append("OPERATOR")
        if most_plants >= 4 and plants.get(puuid, 0) == most_plants: tags.append("PLANTER")
        if most_eco_kills >= 3 and eco_kills.get(puuid, 0) == most_eco_kills: tags.append("ECO FRAUD")
        if most_team_kills and team_kills.get(puuid, 0) == most_team_kills:
            tags.append("TEAM KILLER")
        elif not most_team_kills and most_friendly_fire >= 100 and _friendly_fire(p) == most_friendly_fire:
            tags.append("TEAM KILLER")
        if highest_hs >= 30 and headshot_rates.get(puuid) == highest_hs: tags.append("DINK MACHINE")
        if lowest_hs <= 15 and headshot_rates.get(puuid) == lowest_hs: tags.append("BODY SHOOTER")
        if most_assists >= 8 and assists_by_id.get(puuid, 0) == most_assists: tags.append("ASSIST KING")
        if knife_kills.get(puuid, 0):
            tags.append("KNIFE" if knife_kills[puuid] == 1 else f"KNIFE x{knife_kills[puuid]}")
        if most_lost_round_kills >= EXIT_FARMER_MIN_KILLS and lost_round_kills.get(puuid, 0) == most_lost_round_kills:
            tags.append("EXIT FARMER")
        if highest_adr >= 160 and damage_by_id.get(puuid, 0) == highest_adr: tags.append("DAMAGE DEALER")
        if round_count >= 10 and ((st.get("deaths", 0) / round_count) <= 0.45) and st.get("deaths", 0) == lowest_deaths:
            tags.append("SURVIVOR")
        if clutch_wins.get(puuid, 0):
            tags.append(f"CLUTCH x{clutch_wins[puuid]}")
        death_rounds = sum(1 for events in deaths_by_round.values() if events.get(puuid, 0) > 0)
        if round_count > 0 and death_rounds >= round_count: tags.append("VICTIM")
        if low_score is not None and st.get("score", 0) == low_score: tags.append("LVP")
        if knifed.get(puuid, 0):
            tags.append("KNIFED" if knifed[puuid] == 1 else f"KNIFED x{knifed[puuid]}")
        if (most_clutch_losses >= CHOKER_MIN_LOSSES and clutch_losses.get(puuid, 0) == most_clutch_losses
                and not clutch_wins.get(puuid)):
            tags.append("CHOKER")
        if round_count >= 10 and most_idle >= TOURIST_IDLE_SHARE * round_count and idle.get(puuid) == most_idle:
            tags.append("TOURIST")
        if most_stolen >= KILL_STEALER_MIN_KILLS and stolen.get(puuid, 0) == most_stolen: tags.append("KILL STEALER")
        if most_martyr >= MARTYR_MIN_ROUNDS and martyr.get(puuid, 0) == most_martyr: tags.append("MARTYR")
        afk_rounds = (p.get("behavior") or {}).get("afk_rounds")
        if isinstance(afk_rounds, (int, float)) and afk_rounds >= 1: tags.append("AFK")
        tracked.append({"p": p, "st": st, "hs": hs, "tags": tags,
                        "fb": first_bloods.get(puuid, 0), "fd": first_deaths.get(puuid, 0),
                        "adr": damage_by_id.get(puuid, 0)})
    _assign_unique_tags(tracked)
    _assign_passenger(tracked, all_teammates, low_score)
    return tracked


def _assign_passenger(tracked, all_teammates, low_score):
    """Tag the next-lowest scorer after the LVP, when they also scored well below the team."""
    scores = {p.get("puuid"): (p.get("stats") or {}).get("score", 0) for p in all_teammates}
    if len(scores) < 3 or low_score is None:
        return
    lvp = next((item["p"].get("puuid") for item in tracked if "LVP" in item["tags"]), None)
    if lvp is None:
        lvp = next(puuid for puuid, score in scores.items() if score == low_score)
    others = {puuid: score for puuid, score in scores.items() if puuid != lvp}
    passenger_score = min(others.values())
    average = sum(scores.values()) / len(scores)
    if passenger_score >= average * PASSENGER_SCORE_RATIO:
        return
    eligible = [item for item in tracked if others.get(item["p"].get("puuid")) == passenger_score]
    if eligible:
        min(eligible, key=lambda item: len(item["tags"]))["tags"].append("PASSENGER")


def _recap_mentions(text, players, discord_names):
    """Replace unambiguous Riot names with the server names for this card."""
    if not discord_names:
        return text, None
    labels = {}
    spellings = {}
    for player in players:
        spelling = " ".join((player.get("name") or "").split())
        name = spelling.casefold()
        if not name:
            continue
        key = f"{player.get('name', '')}#{player.get('tag', '')}".casefold()
        display = " ".join(discord_names.get(key, "").split()).lstrip("@").strip()
        if name in labels:
            labels[name] = ""
        else:
            labels[name] = "@" + display.replace(" ", "\u00a0") if display else ""
            spellings[name] = spelling
    labels = {name: label for name, label in labels.items() if label}
    if not labels:
        return text, None
    options = "|".join(re.escape(spellings[name]) for name in sorted(labels, key=len, reverse=True))
    text = re.sub(rf"(?<![\w@])@?({options})(?!\w)", lambda match: labels.get(match[1].casefold(), match[0]),
                  " ".join(text.split()), flags=re.IGNORECASE)
    mentions = "|".join(re.escape(label) for label in sorted(set(labels.values()), key=len, reverse=True))
    return text, re.compile(rf"({mentions})(?!\w)")


def draw_play_result(detail, queued_players, all_teammates, representative, map_path, ai_recap=None, summary_players=None, tone="no_filter", footer=None, fallback_context="", discord_names=None):
    meta = detail.get("metadata", {})
    teams = {t.get("team_id"): t for t in detail.get("teams", [])}
    team = teams.get(representative.get("team_id"), {})
    won = bool(team.get("won"))
    rounds = team.get("rounds") or {}
    our_score = rounds.get("won", 0)
    their_score = rounds.get("lost", 0)
    map_data = meta.get("map") or {}
    map_name = map_data.get("name", "Unknown")
    started = parse_time(meta.get("started_at"))
    duration_ms = meta.get("game_length_in_ms") or 0
    duration = f"{duration_ms // 60000} min" if duration_ms else "Competitive"
    stats_by_id, kills_per_round, first_bloods, first_deaths = {}, {}, {}, {}
    for kill in detail.get("kills") or []:
        killer = (kill.get("killer") or {}).get("puuid")
        round_number = kill.get("round", 0) or 0
        if killer:
            kills_per_round.setdefault(round_number, {}).setdefault(killer, 0)
            kills_per_round[round_number][killer] += 1
    kill_events_by_round = {}
    for event in detail.get("kills") or []:
        kill_events_by_round.setdefault(event.get("round", 0) or 0, []).append(event)
    for events in kill_events_by_round.values():
        if not events:
            continue
        first_event = min(events, key=lambda event: event.get("time_in_round_in_ms", 0))
        first_killer = (first_event.get("killer") or {}).get("puuid")
        first_victim = (first_event.get("victim") or {}).get("puuid")
        if first_killer:
            first_bloods[first_killer] = first_bloods.get(first_killer, 0) + 1
        if first_victim:
            first_deaths[first_victim] = first_deaths.get(first_victim, 0) + 1
    for p in all_teammates:
        st = p.get("stats", {})
        stats_by_id[p.get("puuid")] = st
    scores = [stats.get("score", 0) for stats in stats_by_id.values()]
    top_score = max(scores) if scores else None
    low_score = min(scores) if scores else None
    round_count = max(our_score + their_score, 1)
    tracked = _build_tracked(detail, queued_players, all_teammates, round_count, kills_per_round,
                             first_bloods, first_deaths, top_score, low_score)
    width, hero_h, gap = 1200, 270, 18
    focus = summary_players if summary_players is not None else all_teammates
    registered_only = summary_players is not None
    focus_ids = {p.get("puuid") for p in focus if p.get("puuid")}
    summary_tracked = [item for item in tracked if item["p"].get("puuid") in focus_ids] if registered_only else tracked
    recap = (ai_recap or {}).get("recap") or _play_recap(map_name, won, our_score, their_score, summary_tracked, focus, duration, detail, registered_only, tone)
    if fallback_context:
        recap += " " + fallback_context
    recap, mention_pattern = _recap_mentions(recap, focus, discord_names)
    headline = ((ai_recap or {}).get("headline") or _play_headline(focus, our_score, their_score, registered_only, tone)).upper()
    recap_font = readable_font(recap, 23)
    measure_draw = ImageDraw.Draw(Image.new("RGB", (width, 1)))
    columns, side_pad, column_gap = 2, 24, 18
    recap_lines = wrap_image_text(measure_draw, recap, recap_font, width - 2 * side_pad, 20,
                                  keep_nonbreaking_spaces=mention_pattern is not None)
    summary_h = 114 + max(0, len(recap_lines) - 1) * 42
    card_width = (width - 2 * side_pad - column_gap) // columns
    tag_font = match_font(14, True)
    tag_width_limit = card_width - 132
    max_tag_rows = 1
    for item in tracked:
        used, tag_rows = 0, 1
        for tag in item["tags"]:
            tag_width = int(measure_draw.textlength(tag, font=tag_font)) + 16
            if used and used + tag_width > tag_width_limit:
                tag_rows += 1
                used = 0
            used += tag_width + 6
        max_tag_rows = max(max_tag_rows, tag_rows)
    card_h = 208 + (max_tag_rows - 1) * 28
    rows = max(1, (len(tracked) + columns - 1) // columns)
    cards_top = hero_h + summary_h + 22
    cards_bottom = cards_top + rows * (card_h + gap) - gap
    footer_height = 58 if footer else 26
    height = cards_bottom + footer_height
    image = Image.new("RGB", (width, height), (17, 17, 22))
    draw = ImageDraw.Draw(image)
    if map_path and Path(map_path).exists():
        try:
            bg = Image.open(map_path).convert("RGB")
            ratio = max(width / bg.width, hero_h / bg.height)
            bg = bg.resize((int(bg.width * ratio), int(bg.height * ratio)))
            left, top = (bg.width - width) // 2, (bg.height - hero_h) // 2
            bg = bg.crop((left, top, left + width, top + hero_h))
            bg = Image.blend(bg, Image.new("RGB", bg.size, (8, 9, 12)), 0.60)
            image.paste(bg, (0, 0))
        except Exception as exc:
            logger.warning("Match card map art could not be drawn from %s: %s", map_path, exc)
    draw.rectangle((0, hero_h, width, height), fill=(17, 17, 22))
    accent = (72, 181, 105) if won else (220, 86, 94)
    headline_color = (102, 207, 147) if won else (240, 99, 106)
    if not won and "won" in rounds and "lost" in rounds and our_score == their_score:
        accent = (116, 116, 130)
        headline_color = (191, 190, 201)
    f_sub = match_font(19)
    draw.text((side_pad, 169), map_name.upper(), font=match_font(56, True), fill=(250, 250, 252), anchor="lm")
    if started:
        date_label = uk_time(started).strftime("%a %d %b %Y, %H:%M UK")
    else:
        date_label = "Time unavailable"
    draw.text((side_pad, 224), f"Competitive · {duration} · {date_label}", font=f_sub, fill=(207, 205, 210), anchor="lm")
    badge = f"{'WIN' if won else 'DRAW' if our_score == their_score else 'LOSS'} {our_score}-{their_score}"
    badge_font = match_font(23, True)
    badge_box = (width - side_pad - max(208, chip_width(badge, badge_font)), 186, width - side_pad, 238)
    draw_soft_box(image, badge_box, accent, opacity=238, radius=7)
    draw = ImageDraw.Draw(image)
    draw.text(((badge_box[0] + badge_box[2]) // 2, (badge_box[1] + badge_box[3]) // 2), badge,
              font=badge_font, fill=(255, 250, 250), anchor="mm")
    headline_size = 32
    headline_font = readable_font(headline, headline_size, True)
    while headline_size > 22 and draw.textlength(headline, font=headline_font) > width - 64:
        headline_size -= 1
        headline_font = readable_font(headline, headline_size, True)
    if draw.textlength(headline, font=headline_font) > width - 64:
        while headline and draw.textlength(headline + "...", font=headline_font) > width - 64:
            headline = headline[:-1]
        headline = headline.rstrip() + "..."
    draw.text((side_pad, hero_h + 44), headline, font=headline_font, fill=headline_color, anchor="lm")
    for line_index, line in enumerate(recap_lines):
        y = hero_h + 100 + line_index * 42
        parts = mention_pattern.split(line) if mention_pattern else [line]
        prefix = ""
        for index, part in enumerate(parts):
            x = side_pad + draw.textlength(prefix, font=recap_font)
            color = (149, 190, 255) if index % 2 else (226, 226, 232)
            draw.text((x, y), part, font=recap_font, fill=color, anchor="lm")
            prefix += part
    for index, item in enumerate(tracked):
        col, row = index % columns, index // columns
        if len(tracked) % columns and row == rows - 1:
            x = (width - card_width) // 2
        else:
            x = side_pad + col * (card_width + column_gap)
        y = cards_top + row * (card_h + gap)
        right = x + card_width
        draw.rounded_rectangle((x, y, right, y + card_h), radius=14, fill=(28, 27, 31), outline=(42, 40, 45), width=1)
        p, st = item["p"], item["st"]
        icon = p.get("_play_icon")
        icon_size = 76
        icon_x, icon_y = x + 18, y + 18
        draw.rounded_rectangle((icon_x, icon_y, icon_x + icon_size, icon_y + icon_size), radius=8, fill=(28, 27, 31))
        if icon:
            icon = ImageOps.contain(icon.convert("RGBA"), (icon_size, icon_size), method=Image.Resampling.LANCZOS)
            fitted_x = icon_x + (icon_size - icon.width) // 2
            fitted_y = icon_y + (icon_size - icon.height) // 2
            image.paste(icon, (fitted_x, fitted_y), icon)
        player_name = str(p.get("name", "?"))
        player_name_size = 25
        player_name_font = readable_font(player_name, player_name_size, True)
        player_name_x = x + 112
        while player_name_size > 18 and draw.textlength(player_name, font=player_name_font) > right - player_name_x - 20:
            player_name_size -= 1
            player_name_font = readable_font(player_name, player_name_size, True)
        player_blue = (164, 194, 245)
        draw.text((player_name_x, y + 18), player_name, font=player_name_font, fill=player_blue, anchor="lt")
        tx, tag_row = player_name_x, 0
        for tag in item["tags"]:
            tw = int(draw.textlength(tag, font=tag_font)) + 16
            max_right = right - 20
            if tx + tw > max_right:
                tag_row += 1
                tx = player_name_x
            tag_key = tag.split(" x", 1)[0]
            tag_colour, tag_text, *tag_opacity = PLAY_TAG_STYLES.get(tag_key, ((68, 68, 78), (235, 235, 240)))
            tag_y = y + 54 + tag_row * 32
            draw_soft_box(image, (tx, tag_y, tx + tw, tag_y + 30), tag_colour,
                          opacity=tag_opacity[0] if tag_opacity else 88, radius=5,
                          outline=(*tag_text, 105) if not tag_opacity else None)
            text_bbox = tag_font.getbbox(tag, anchor="mm")
            text_center_offset = (text_bbox[1] + text_bbox[3]) / 2
            draw.text((tx + tw / 2, tag_y + 15 - text_center_offset),
                      tag, font=tag_font, fill=tag_text, anchor="mm")
            tx += tw + 6
        stat_label_y = y + 118 + tag_row * 32
        stat_value_y = stat_label_y + 31
        labels = [("KDA", f"{st.get('kills',0)}/{st.get('deaths',0)}/{st.get('assists',0)}"),
                  ("ACS", str(round(st.get("score", 0) / round_count))),
                  ("KD", f"{st.get('kills',0) / max(st.get('deaths',0),1):.2f}")]
        cell_w = (right - x - 44) // 3
        for cell, (label, value) in enumerate(labels):
            cx = x + 22 + cell * cell_w + cell_w // 2
            draw.text((cx, stat_label_y), label, font=match_font(16), fill=(154, 151, 160), anchor="mm")
            draw.text((cx, stat_value_y), value, font=match_font(24, True), fill=(247, 246, 248), anchor="mm")
        subtext_y = stat_value_y + 33
        draw.text(((x + right) // 2, subtext_y),
                  f"HS {item['hs']}% | FB {item['fb']} | FD {item['fd']}",
                  font=match_font(15), fill=(155, 152, 161), anchor="mm")
    if footer:
        footer_y = height - 25
        footer_font = match_font(19)
        footer_color = (173, 170, 180)
        draw.line((side_pad, cards_bottom + 16, width - side_pad, cards_bottom + 16), fill=(42, 40, 45))
        draw.text((side_pad, footer_y), footer, font=footer_font, fill=footer_color, anchor="lm")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    buffer.seek(0)
    return buffer
