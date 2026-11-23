from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageOps

from .assets import (PLAY_TAG_STYLES, display_font, display_font_for, draw_soft_box, draw_spaced_text, encode_png,
                     match_font, readable_font, wrap_image_text)
from services.matchfeed import MATCHFEED_DAY_ZONE
from utils.formatting import parse_time
from utils.match_summary import _clutch_wins, _deaths_by_round, _play_headline, _play_recap


# Tags every eligible player keeps, even when a teammate earned the same one.
SHARED_TAGS = {"ACE", "CLUTCH", "VICTIM", "KNIFE"}
OPERATOR_MIN_KILLS = 6
EXIT_FARMER_MIN_KILLS = 6
KNIFE_WEAPONS = {"knife", "melee"}
ECO_LOADOUT_RATIO = 0.5
ECO_MIN_KILLER_LOADOUT = 2500
PASSENGER_SCORE_RATIO = 0.8


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
        if weapon_name in KNIFE_WEAPONS:
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


def _friendly_fire(player):
    return ((player.get("behavior") or {}).get("friendly_fire") or {}).get("outgoing") or 0


def _build_tracked(detail, queued_players, all_teammates, round_count, kills_per_round,
                   first_bloods, first_deaths, top_score, low_score):
    """Work out each queued player's stat line and the tags they earned this match."""
    deaths_by_round = _deaths_by_round(detail)
    clutch_wins = _clutch_wins(detail, all_teammates)
    plants = _plants(detail)
    operator_kills, eco_kills, team_kills, knife_kills, lost_round_kills = _kill_events(detail)
    teammate_ids = {p.get("puuid") for p in all_teammates}

    def team_max(counts):
        return max((counts.get(puuid, 0) for puuid in teammate_ids), default=0)

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


# ---------- Card layout ----------

WIDTH, PAD = 1200, 32
HERO_H, STRIP_H, HEADLINE_H, RECAP_LINE = 300, 64, 50, 36
HEADER_H, ROW_GAP, FOOTER_H = 36, 10, 60
BG, HERO_FALLBACK = (17, 17, 22), (26, 25, 32)
ROW_BG, ROW_EDGE, ICON_BG = (27, 26, 32), (44, 42, 50), (38, 37, 45)
MVP_EDGE, GOLD = (150, 128, 70), (238, 214, 139)
TEXT, RECAP_TEXT, MUTED, LABEL = (244, 243, 247), (226, 226, 232), (173, 170, 182), (150, 148, 160)
CORAL, NAME_BLUE, MENTION = (240, 99, 106), (164, 194, 245), (149, 190, 255)
GOOD, BAD = (102, 207, 147), (240, 99, 106)
ROUND_WIN, ROUND_LOSS = ((33, 88, 58), (160, 236, 190)), ((104, 36, 44), (255, 168, 174))
RANK_X, ICON_X, ICON_SIZE = PAD + 30, PAD + 58, 64
NAME_X, NAME_RIGHT = PAD + 140, 572
COLUMNS = (("K / D / A", 650), ("ACS", 770), ("K/D", 872), ("ADR", 960), ("HS", 1040), ("FB / FD", 1114))
TAG_H, TAG_GAP = 30, 6


def _result_palette(won, our_score, their_score, rounds):
    if not won and "won" in rounds and "lost" in rounds and our_score == their_score:
        return {"word": "DRAW", "accent": (96, 96, 110), "text": (191, 190, 201)}
    if won:
        return {"word": "VICTORY", "accent": (40, 128, 76), "text": GOOD}
    return {"word": "DEFEAT", "accent": (190, 52, 62), "text": BAD}


def _round_results(detail, team_id, total):
    """Whether the squad won each round, in order, or None when rounds can't be matched to the score."""
    rows = detail.get("rounds") or []
    side = str(team_id or "").casefold()
    if not side or not rows or len(rows) != total:
        return None
    results = []
    for _, row in sorted(enumerate(rows), key=lambda item: _round_number(item[1], item[0])):
        winner = str(row.get("winning_team") or "").casefold()
        if not winner:
            return None
        results.append(winner == side)
    return results


def _halves_text(results):
    if not results or len(results) <= 12:
        return ""
    first, second, extra = results[:12], results[12:24], results[24:]
    text = f"1ST HALF {sum(first)}–{len(first) - sum(first)} · 2ND HALF {sum(second)}–{len(second) - sum(second)}"
    if extra:
        text += f" · OT {sum(extra)}–{len(extra) - sum(extra)}"
    return text


def _cover(path, size):
    if not path or not Path(path).exists():
        return None
    try:
        with Image.open(path) as source:
            return ImageOps.fit(source.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    except Exception:
        return None


def _ramp_mask(size, stops, horizontal):
    """Alpha mask that changes linearly between (position 0-1, alpha) stops across or down ``size``."""
    width, height = size
    length = width if horizontal else height
    values = []
    for index in range(length):
        t = index / max(length - 1, 1)
        for (t0, a0), (t1, a1) in zip(stops, stops[1:]):
            if t <= t1:
                values.append(round(a0 + (a1 - a0) * ((t - t0) / (t1 - t0) if t1 > t0 else 1)))
                break
        else:
            values.append(stops[-1][1])
    strip = Image.new("L", (length, 1) if horizontal else (1, length))
    strip.putdata(values)
    return strip.resize(size)


def _fit_headline(measure, headline, max_width):
    size = 46
    face = display_font_for(headline, size)
    while size > 30 and measure.textlength(headline, font=face) > max_width:
        size -= 1
        face = display_font_for(headline, size)
    if measure.textlength(headline, font=face) > max_width:
        while headline and measure.textlength(headline + "...", font=face) > max_width:
            headline = headline[:-1]
        headline = headline.rstrip() + "..."
    return face, headline


def _agent_name(player):
    agent = player.get("agent") or player.get("character") or {}
    name = agent.get("name") if isinstance(agent, dict) else agent
    return str(name).strip() if name else ""


def _row_layout(measure, item):
    """Name font and tag positions for one scoreboard row, plus the row height they need."""
    name = str(item["p"].get("name", "?"))
    size = 25
    name_font = readable_font(name, size, True)
    while size > 18 and measure.textlength(name, font=name_font) > NAME_RIGHT - NAME_X:
        size -= 1
        name_font = readable_font(name, size, True)
    tag_font = match_font(14, True)
    tags, x, row = [], 0, 0
    for tag in item["tags"]:
        width = int(measure.textlength(tag, font=tag_font)) + 16
        if x and x + width > NAME_RIGHT - NAME_X:
            row, x = row + 1, 0
        tags.append((tag, x, row, width))
        x += width + TAG_GAP
    tag_rows = row + 1 if tags else 0
    content = 30 + (10 + tag_rows * TAG_H + (tag_rows - 1) * TAG_GAP if tag_rows else 0)
    return {"name": name, "name_font": name_font, "tag_font": tag_font, "tags": tags, "content": content,
            "height": max(ICON_SIZE + 28, content + 36)}


def _paste_icon(image, icon, xy):
    tile = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (*ICON_BG, 255))
    if icon is not None:
        fitted = ImageOps.contain(icon.convert("RGBA"), (ICON_SIZE, ICON_SIZE), method=Image.Resampling.LANCZOS)
        tile.alpha_composite(fitted, ((ICON_SIZE - fitted.width) // 2, (ICON_SIZE - fitted.height) // 2))
    mask = Image.new("L", (ICON_SIZE * 4, ICON_SIZE * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, ICON_SIZE * 4 - 1, ICON_SIZE * 4 - 1), radius=48, fill=255)
    image.paste(tile.convert("RGB"), xy, mask.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS))


def _draw_hero(image, map_path, map_name, started, duration_ms, palette, our_score, their_score, results, footer):
    art = _cover(map_path, (WIDTH, HERO_H))
    hero = (Image.blend(art, Image.new("RGB", art.size, (8, 9, 12)), 0.42) if art
            else Image.new("RGB", (WIDTH, HERO_H), HERO_FALLBACK))
    shade = Image.new("RGB", hero.size, BG)
    # Darken behind the map name on the left and the score on the right, then fade into the card.
    hero.paste(shade, (0, 0), _ramp_mask(hero.size, [(0, 225), (0.55, 70), (1, 165)], horizontal=True))
    hero.paste(shade, (0, 0), _ramp_mask(hero.size, [(0, 0), (0.5, 0), (1, 255)], horizontal=False))
    image.paste(hero, (0, 0))
    draw = ImageDraw.Draw(image)

    parts = ["COMPETITIVE"]
    if duration_ms:
        parts.append(f"{duration_ms // 60000} MIN")
    if started:
        parts.append(started.astimezone(MATCHFEED_DAY_ZONE).strftime("%a %d %b · %H:%M").upper())
    draw_spaced_text(draw, (PAD, 96), " · ".join(parts), match_font(16, True), CORAL, 2)
    title = map_name.upper()
    draw.text((PAD, 212), title, font=display_font_for(title, 112), fill=TEXT, anchor="ls")
    if footer:
        draw.text((PAD, 252), footer, font=readable_font(footer, 17), fill=MUTED, anchor="ls")

    right = WIDTH - PAD
    big = display_font(124)
    them, us = str(their_score), str(our_score)
    draw.text((right, 212), them, font=big, fill=(214, 212, 222), anchor="rs")
    x = right - draw.textlength(them, font=big) - 18
    draw.rounded_rectangle((x - 26, 166, x, 172), radius=3, fill=LABEL)
    draw.text((x - 44, 212), us, font=big, fill=palette["text"], anchor="rs")

    word_font = match_font(16, True)
    word_width = sum(draw.textlength(char, font=word_font) for char in palette["word"]) + 3 * (len(palette["word"]) - 1)
    pill = (int(right - word_width - 32), 70, right, 104)
    draw_soft_box(image, pill, palette["accent"], opacity=240, radius=17)
    draw = ImageDraw.Draw(image)
    draw_spaced_text(draw, ((pill[0] + pill[2]) / 2, 87), palette["word"], word_font, (255, 255, 255), 3, anchor="mm")
    halves = _halves_text(results)
    if halves:
        draw.text((right, 252), halves, font=match_font(17), fill=MUTED, anchor="rs")


def _draw_round_strip(image, top, results):
    draw = ImageDraw.Draw(image)
    middle = top + STRIP_H // 2 - 2
    draw_spaced_text(draw, (PAD, middle), "ROUNDS", match_font(13, True), LABEL, 2, anchor="lm")
    left = PAD + 96
    breaks = [index for index in (12, 24) if index < len(results)]
    divider, gap, count = 18, 4, len(results)
    cell = min(40, int((WIDTH - PAD - left - divider * len(breaks) - gap * (count - 1)) / count))
    number_font = match_font(13, True)
    x = left
    for index, won_round in enumerate(results):
        if index in breaks:
            line_x = x - gap / 2 + divider / 2
            draw.line((line_x, middle - 20, line_x, middle + 20), fill=CORAL, width=2)
            x += divider
        fill, text = ROUND_WIN if won_round else ROUND_LOSS
        draw_soft_box(image, (int(x), middle - 15, int(x) + cell, middle + 15), fill, opacity=255, radius=6)
        draw = ImageDraw.Draw(image)
        draw.text((int(x) + cell / 2, middle), str(index + 1), font=number_font, fill=text, anchor="mm")
        x += cell + gap


def _draw_player_row(image, top, index, item, layout, round_count, top_acs):
    draw = ImageDraw.Draw(image)
    bottom = top + layout["height"]
    middle = (top + bottom) // 2
    mvp = any(_tag_key(tag) == "MVP" for tag in item["tags"])
    draw.rounded_rectangle((PAD, top, WIDTH - PAD, bottom), radius=14, fill=ROW_BG,
                           outline=MVP_EDGE if mvp else ROW_EDGE, width=2 if mvp else 1)
    draw.text((RANK_X, middle), str(index + 1), font=display_font(30), fill=GOLD if index == 0 else LABEL, anchor="mm")
    _paste_icon(image, item["p"].get("_play_icon"), (ICON_X, middle - ICON_SIZE // 2))
    draw = ImageDraw.Draw(image)

    name_top = middle - layout["content"] // 2
    draw.text((NAME_X, name_top), layout["name"], font=layout["name_font"], fill=NAME_BLUE, anchor="lt")
    agent = _agent_name(item["p"])
    if agent:
        agent_font = match_font(15)
        agent_x = NAME_X + draw.textlength(layout["name"], font=layout["name_font"]) + 10
        if agent_x + draw.textlength(agent, font=agent_font) <= NAME_RIGHT:
            draw.text((agent_x, name_top + 8), agent, font=agent_font, fill=MUTED, anchor="lt")
    tag_top = name_top + 40
    for tag, offset, row, width in layout["tags"]:
        tx, ty = NAME_X + offset, tag_top + row * (TAG_H + TAG_GAP)
        colour, text, *opacity = PLAY_TAG_STYLES.get(_tag_key(tag), ((68, 68, 78), (235, 235, 240)))
        draw_soft_box(image, (tx, ty, tx + width, ty + TAG_H), colour, opacity=opacity[0] if opacity else 88,
                      radius=5, outline=(*text, 105) if not opacity else None)
        draw = ImageDraw.Draw(image)
        bbox = layout["tag_font"].getbbox(tag, anchor="mm")
        draw.text((tx + width / 2, ty + TAG_H / 2 - (bbox[1] + bbox[3]) / 2), tag, font=layout["tag_font"],
                  fill=text, anchor="mm")

    stats = item["st"]
    kills, deaths, assists = stats.get("kills", 0), stats.get("deaths", 0), stats.get("assists", 0)
    acs = round(stats.get("score", 0) / round_count)
    kd = kills / max(deaths, 1)
    value_font, small_font = match_font(23, True), match_font(21, True)
    column = dict(COLUMNS)
    draw.text((column["K / D / A"], middle), f"{kills}/{deaths}/{assists}", font=value_font, fill=TEXT, anchor="mm")
    draw.text((column["ACS"], middle - 6), str(acs), font=value_font, fill=TEXT, anchor="mm")
    bar_left = column["ACS"] - 35
    draw.rounded_rectangle((bar_left, middle + 14, bar_left + 70, middle + 18), radius=2, fill=(48, 46, 56))
    draw.rounded_rectangle((bar_left, middle + 14, bar_left + max(4, round(70 * min(acs / top_acs, 1))), middle + 18),
                           radius=2, fill=CORAL)
    draw.text((column["K/D"], middle), f"{kd:.2f}", font=value_font, fill=GOOD if kd >= 1 else BAD, anchor="mm")
    draw.text((column["ADR"], middle), str(item.get("adr", 0)), font=small_font, fill=RECAP_TEXT, anchor="mm")
    draw.text((column["HS"], middle), f"{item['hs']}%", font=small_font, fill=RECAP_TEXT, anchor="mm")
    draw.text((column["FB / FD"], middle), f"{item['fb']}/{item['fd']}", font=small_font, fill=RECAP_TEXT, anchor="mm")


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
    focus = summary_players if summary_players is not None else all_teammates
    registered_only = summary_players is not None
    focus_ids = {p.get("puuid") for p in focus if p.get("puuid")}
    summary_tracked = [item for item in tracked if item["p"].get("puuid") in focus_ids] if registered_only else tracked
    recap = (ai_recap or {}).get("recap") or _play_recap(map_name, won, our_score, their_score, summary_tracked, focus, duration, detail, registered_only, tone)
    if fallback_context:
        recap += " " + fallback_context
    recap, mention_pattern = _recap_mentions(recap, focus, discord_names)
    headline = ((ai_recap or {}).get("headline") or _play_headline(focus, our_score, their_score, registered_only, tone)).upper()
    palette = _result_palette(won, our_score, their_score, rounds)
    results = _round_results(detail, representative.get("team_id"), our_score + their_score)
    measure = ImageDraw.Draw(Image.new("RGB", (WIDTH, 1)))
    recap_font = readable_font(recap, 22)
    recap_lines = wrap_image_text(measure, recap, recap_font, WIDTH - 2 * PAD, 20,
                                  keep_nonbreaking_spaces=mention_pattern is not None)
    headline_font, headline = _fit_headline(measure, headline, WIDTH - 2 * PAD)
    rows = sorted(tracked, key=lambda item: item["st"].get("score", 0), reverse=True)
    layouts = [_row_layout(measure, item) for item in rows]
    row_height = max((layout["height"] for layout in layouts), default=0)
    for layout in layouts:
        layout["height"] = row_height
    strip_h = STRIP_H if results else 0
    summary_h = 22 + HEADLINE_H + 12 + len(recap_lines) * RECAP_LINE + 18
    players_h = (HEADER_H + sum(layout["height"] for layout in layouts) + ROW_GAP * (len(layouts) - 1)) if layouts else 0
    footer_h = FOOTER_H if our_score + their_score else 24
    height = HERO_H + strip_h + summary_h + players_h + footer_h
    image = Image.new("RGB", (WIDTH, height), BG)

    _draw_hero(image, map_path, map_name, started, duration_ms, palette, our_score, their_score, results, footer)
    y = HERO_H
    if results:
        _draw_round_strip(image, y, results)
        y += strip_h

    draw = ImageDraw.Draw(image)
    y += 22
    draw.text((PAD, y), headline, font=headline_font, fill=palette["text"], anchor="lt")
    y += HEADLINE_H + 12
    for line in recap_lines:
        parts = mention_pattern.split(line) if mention_pattern else [line]
        x = PAD
        for index, part in enumerate(parts):
            draw.text((x, y), part, font=recap_font, fill=MENTION if index % 2 else RECAP_TEXT, anchor="lt")
            x += draw.textlength(part, font=recap_font)
        y += RECAP_LINE
    y += 18

    if layouts:
        label_font = match_font(13, True)
        header_y = y + HEADER_H // 2
        draw_spaced_text(draw, (NAME_X, header_y), "PLAYER", label_font, LABEL, 2, anchor="lm")
        for label, x in COLUMNS:
            draw_spaced_text(draw, (x, header_y), label, label_font, LABEL, 2, anchor="mm")
        y += HEADER_H
        top_acs = max((round(item["st"].get("score", 0) / round_count) for item in rows), default=0) or 1
        for index, (item, layout) in enumerate(zip(rows, layouts)):
            _draw_player_row(image, y, index, item, layout, round_count, top_acs)
            y += layout["height"] + ROW_GAP
        y -= ROW_GAP

    if our_score + their_score:
        draw = ImageDraw.Draw(image)
        rule_y = height - footer_h + 18
        draw.line((PAD, rule_y, WIDTH - PAD, rule_y), fill=ROW_EDGE)
        squad_scores = [stats.get("score", 0) / round_count for stats in stats_by_id.values()]
        squad_acs = round(sum(squad_scores) / len(squad_scores)) if squad_scores else 0
        draw.text((PAD, rule_y + 22), f"{our_score + their_score} rounds · squad ACS {squad_acs} · tags are awarded from match data",
                  font=match_font(15), fill=LABEL, anchor="lm")
    return encode_png(image)
