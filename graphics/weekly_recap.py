"""Render the weekly squad recap card in the bot's dark card style."""

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from graphics.assets import chip_width, draw_result_chip, draw_soft_box, match_font, readable_font, wrap_image_text
from graphics.weekly_awards import awards_height, draw_awards
from services.matchfeed import MATCHFEED_DAY_ZONE

WIDTH, PAD = 1200, 40
SMURF_CHIP, SMURF_TEXT = (66, 45, 104), (214, 192, 255)
BACKGROUND = (17, 17, 22)
PANEL, PANEL_EDGE = (28, 27, 32), (57, 55, 63)
TILE = (38, 37, 43)
CORAL, GREEN, GOLD, GOLD_EDGE = (240, 99, 106), (102, 207, 147), (255, 205, 90), (107, 90, 42)
SILVER, SILVER_EDGE = (205, 212, 222), (88, 92, 102)
BRONZE, BRONZE_EDGE = (214, 140, 84), (104, 70, 44)
PODIUM = ((GOLD, GOLD_EDGE), (SILVER, SILVER_EDGE), (BRONZE, BRONZE_EDGE))
WHITE, MUTED, RULE = (243, 242, 246), (171, 170, 182), (64, 61, 70)

HEADER_HEIGHT = 150
RR_ROW = 44
GAME_CARD_HEIGHT = 196
SIDE_ROW = 40
SUMMARY_LINE = 32
GAP = 26


def _fit(measure, text, font, width):
    while text and measure.textlength(text, font=font) > width:
        text = text[:-2] + "…"
    return text


def _plural(count, word):
    return f"{count} {word}" + ("" if count == 1 else "s")


def _result(game_or_match):
    won = game_or_match.get("won")
    return ("W", GREEN) if won is True else ("L", CORAL) if won is False else ("D", MUTED)


def _section_title(draw, measure, y, title, right=WIDTH - PAD, left=PAD):
    font = match_font(20, True)
    draw.text((left, y), title, font=font, fill=CORAL)
    draw.line((left + measure.textlength(title, font=font) + 16, y + 13, right, y + 13), fill=RULE)


def _rr_text(player):
    if player["rr"] is None:
        return "RR unavailable", MUTED
    if not player["games"] and not player["rr"]:
        return "no games", MUTED
    label = f"{player['rr']:+d} RR" + ("*" if player["partial"] else "")
    return label, GREEN if player["rr"] > 0 else CORAL if player["rr"] < 0 else MUTED


def _paste_map_background(image, path, box, radius):
    """Cover-crop map art into ``box``, darken it for legible text and clip it to the card's rounded corners."""
    if not path or not Path(path).exists():
        return False
    try:
        with Image.open(path) as source:
            art = ImageOps.fit(source.convert("RGB"), (box[2] - box[0], box[3] - box[1]),
                               method=Image.Resampling.LANCZOS)
    except Exception:
        return False
    art = Image.blend(art, Image.new("RGB", art.size, PANEL), 0.72)
    # Slightly darker at the bottom where the stat line sits.
    shade = Image.linear_gradient("L").resize(art.size)
    art = Image.composite(Image.new("RGB", art.size, BACKGROUND), art, shade.point(lambda value: value * 0.45))
    mask = Image.new("L", art.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, art.width - 1, art.height - 1), radius=radius, fill=255)
    image.paste(art, box[:2], mask)
    return True


def _draw_game_cards(image, draw, measure, y, games, map_art):
    """Up to three side-by-side top-game cards starting at ``y``; returns the (re-created) draw handle."""
    small = match_font(19)
    card_gap = 14
    card_width = (WIDTH - PAD * 2 - card_gap * 2) // 3
    for index, game in enumerate(games):
        left = PAD + index * (card_width + card_gap)
        right = left + card_width
        box = (left, y, right, y + GAME_CARD_HEIGHT)
        rank_color, edge_color = PODIUM[index] if index < len(PODIUM) else (WHITE, PANEL_EDGE)
        has_art = _paste_map_background(image, map_art.get(str(game.get("map", "")).casefold()), box, 12)
        draw.rounded_rectangle(box, radius=12, fill=None if has_art else PANEL,
                               outline=edge_color)
        inner = left + 18
        draw.text((inner, y + 14), f"{index + 1}.", font=match_font(30, True), fill=rank_color)
        letter, color = _result(game)
        chip_text, chip_font = f"{letter} {game['score']}".strip(), match_font(20, True)
        draw_result_chip(image, (right - 16 - chip_width(chip_text, chip_font, 10), y + 16, right - 16, y + 50),
                         color, chip_text, chip_font, gradient=False)
        draw = ImageDraw.Draw(image)
        title = f"{game['player']} · {game['agent']}"
        title_font = readable_font(title, 24)
        draw.text((inner, y + 62), _fit(measure, title, title_font, card_width - 36), font=title_font, fill=WHITE)
        played = game["started_at"].astimezone(MATCHFEED_DAY_ZONE)
        draw.text((inner, y + 98), _fit(measure, f"{game['map']} · {played:%a %d %b}", small, card_width - 36),
                  font=small, fill=MUTED)
        draw.line((inner, y + 136, right - 18, y + 136), fill=RULE)
        kda = f"{game['k']}/{game['d']}/{game['a']} · "
        acs = f"{game['acs']} ACS"
        draw.text((inner, y + 152), kda, font=small, fill=MUTED)
        offset = measure.textlength(kda, font=small)
        draw.text((inner + offset, y + 152), acs, font=match_font(19, True), fill=WHITE)
        offset += measure.textlength(acs, font=match_font(19, True))
        draw.text((inner + offset, y + 152), f" · {game['hs']}% HS", font=small, fill=MUTED)
    return draw




# ---------- Layout: header, awards, RR split, top games, Premier, summary ----------

MAIN_COLUMN = 720  # width of the main-account RR column when smurfs get their own column
RANK_CHIP_ROW = 32  # extra height for a row whose rank chip drops below the name
SMURF_ROW_HEIGHT = 64
TIER_SHORT = {"Platinum": "Plat", "Diamond": "Dia", "Ascendant": "Asc", "Immortal": "Imm"}
RANK_UP, RANK_UP_TEXT = (39, 104, 71), (139, 238, 189)
RANK_DOWN, RANK_DOWN_TEXT = (104, 39, 39), (238, 139, 139)


def _short_tier(name):
    first, _, rest = str(name).partition(" ")
    return f"{TIER_SHORT.get(first, first)} {rest}".strip()


def _rank_chip_width(measure, change):
    font = match_font(14, True)
    return round(measure.textlength(_short_tier(change["from"]), font=font)
                 + measure.textlength(_short_tier(change["to"]), font=font)) + 46


def _draw_rank_chip(image, x, y, change):
    """'Plat 2 -> Plat 3' chip, green for a rank up and red for a derank; the arrow never depends on font glyphs."""
    font = match_font(14, True)
    fill, colour = (RANK_UP, RANK_UP_TEXT) if change["direction"] == "up" else (RANK_DOWN, RANK_DOWN_TEXT)
    measure = ImageDraw.Draw(image)
    width = _rank_chip_width(measure, change)
    draw_soft_box(image, (x, y, x + width, y + 26), fill, opacity=88, radius=5, outline=(*colour, 105))
    draw = ImageDraw.Draw(image)
    left, right = _short_tier(change["from"]), _short_tier(change["to"])
    draw.text((x + 8, y + 13), left, font=font, fill=colour, anchor="lm")
    arrow = x + 8 + draw.textlength(left, font=font) + 6
    draw.line((arrow, y + 13, arrow + 16, y + 13), fill=colour, width=2)
    draw.line((arrow + 11, y + 8, arrow + 16, y + 13, arrow + 11, y + 18), fill=colour, width=2)
    draw.text((arrow + 24, y + 13), right, font=font, fill=colour, anchor="lm")
    return draw


def _rank_changes_by_account(week):
    changes = {}
    for change in week["rank_changes"]:
        changes.setdefault((change["player"], bool(change.get("smurf"))), change)
    return changes


def _main_row_height(player, changes):
    return RR_ROW + (RANK_CHIP_ROW if (player["name"], False) in changes else 0)


def _rr_panel_height(mains, smurfs, changes):
    main_height = sum(_main_row_height(player, changes) for player in mains) or RR_ROW
    smurf_height = len(smurfs) * SMURF_ROW_HEIGHT
    return 44 + max(main_height, smurf_height)


def _draw_main_rows(image, draw, measure, y, players, changes, right):
    """Main accounts: name, record, RR bar and total; a rank change drops in as a chip under the name."""
    body, small = match_font(23), match_font(18)
    if not players:
        draw.text((PAD, y), "No main accounts played this week.", font=body, fill=MUTED)
        return draw
    record_x = PAD + 236
    bar_left, bar_right = PAD + 400, right - 125
    middle = (bar_left + bar_right) // 2
    biggest = max([abs(player["rr"]) for player in players if player["rr"]] or [1])
    for player in players:
        name_font = readable_font(player["name"], 24)
        draw.text((PAD, y), _fit(measure, player["name"], name_font, record_x - PAD - 12), font=name_font, fill=WHITE)
        record = f"{_plural(player['games'], 'game')} · {player['wins']}W {player['losses']}L"
        draw.text((record_x, y + 4), _fit(measure, record, small, bar_left - record_x - 14), font=small, fill=MUTED)
        bar_y = y + 12
        draw.rounded_rectangle((bar_left, bar_y, bar_right, bar_y + 10), radius=5, fill=TILE)
        if player["rr"]:
            length = max(6, round((middle - bar_left) * min(abs(player["rr"]) / biggest, 1)))
            if player["rr"] > 0:
                draw.rounded_rectangle((middle, bar_y, middle + length, bar_y + 10), radius=5, fill=GREEN)
            else:
                draw.rounded_rectangle((middle - length, bar_y, middle, bar_y + 10), radius=5, fill=CORAL)
        label, color = _rr_text(player)
        draw.text((right, y), label, font=match_font(23, True), fill=color, anchor="ra")
        change = changes.get((player["name"], False))
        if change:
            draw = _draw_rank_chip(image, PAD, y + RR_ROW - 8, change)
        y += _main_row_height(player, changes)
    return draw


def _draw_smurf_rows(image, draw, measure, x, y, players, changes, right):
    """Smurf accounts as a compact list: name and RR, with the record and any rank change underneath."""
    for player in players:
        label, color = _rr_text(player)
        label_font = match_font(22, True)
        name_font = readable_font(player["name"], 22)
        name_width = right - x - measure.textlength(label, font=label_font) - 16
        draw.text((x, y), _fit(measure, player["name"], name_font, name_width), font=name_font, fill=WHITE)
        draw.text((right, y), label, font=label_font, fill=color, anchor="ra")
        record = f"{_plural(player['games'], 'game')} · {player['wins']}W {player['losses']}L"
        small = match_font(16)
        change = changes.get((player["name"], True))
        if change:
            draw = _draw_rank_chip(image, x, y + 30, change)
            record_x = x + _rank_chip_width(measure, change) + 10
        else:
            record_x = x
        draw.text((record_x, y + 33), _fit(measure, record, small, right - record_x), font=small, fill=MUTED)
        y += SMURF_ROW_HEIGHT
    return draw


def _draw_smurf_best(image, draw, measure, y, game):
    """The best smurf game as one slim row instead of a second set of cards."""
    draw.rounded_rectangle((PAD, y, WIDTH - PAD, y + 64), radius=12, fill=PANEL, outline=PANEL_EDGE)
    chip_font = match_font(14, True)
    label = "BEST SMURF GAME"
    label_width = round(measure.textlength(label, font=chip_font)) + 16
    draw_soft_box(image, (PAD + 18, y + 18, PAD + 18 + label_width, y + 46), SMURF_CHIP, opacity=255, radius=5)
    draw = ImageDraw.Draw(image)
    draw.text((PAD + 18 + label_width / 2, y + 32), label, font=chip_font, fill=SMURF_TEXT, anchor="mm")
    letter, color = _result(game)
    result = f"{letter} {game['score']}".strip()
    result_font = match_font(18, True)
    result_left = WIDTH - PAD - 18 - chip_width(result, result_font, 10)
    draw_result_chip(image, (result_left, y + 17, WIDTH - PAD - 18, y + 47), color, result, result_font,
                     gradient=False)
    draw = ImageDraw.Draw(image)
    small = match_font(18)
    stats = f"{game['k']}/{game['d']}/{game['a']} · {game['acs']} ACS · {game['hs']}% HS"
    stats_left = result_left - 16 - measure.textlength(stats, font=small)
    draw.text((result_left - 16, y + 21), stats, font=small, fill=WHITE, anchor="ra")
    x = PAD + 36 + label_width
    title = f"{game['player']} · {game['agent']}"
    title_font = readable_font(title, 22, True)
    title = _fit(measure, title, title_font, stats_left - x - 20)
    draw.text((x, y + 18), title, font=title_font, fill=WHITE)
    x += measure.textlength(title, font=title_font) + 14
    played = game["started_at"].astimezone(MATCHFEED_DAY_ZONE)
    details = _fit(measure, f"{game['map']} · {played:%a %d %b}", small, stats_left - x - 16)
    draw.text((x, y + 21), details, font=small, fill=MUTED)
    return draw


def _premier_height(premier):
    return (64 + len(premier["matches"]) * SIDE_ROW + 10) if premier else 0


def _draw_premier(image, draw, measure, y, premier):
    height = _premier_height(premier)
    draw.rounded_rectangle((PAD, y, WIDTH - PAD, y + height), radius=12, fill=PANEL, outline=PANEL_EDGE)
    draw.text((PAD + 20, y + 18), "PREMIER", font=match_font(20, True), fill=CORAL)
    record = f"{premier['wins']}W {premier['losses']}L"
    points = f" · {premier['points']:+d} points" if premier["points"] is not None else ""
    bold = match_font(21, True)
    points_color = GREEN if (premier["points"] or 0) >= 0 else CORAL
    draw.text((WIDTH - PAD - 20, y + 18), points, font=bold, fill=points_color, anchor="ra")
    draw.text((WIDTH - PAD - 20 - measure.textlength(points, font=bold), y + 18), record, font=bold, fill=WHITE,
              anchor="ra")
    row_y = y + 64
    for match in premier["matches"]:
        letter, color = _result(match)
        draw_result_chip(image, (PAD + 18, row_y - 3, PAD + 46, row_y + 27), color, letter, match_font(18, True),
                         gradient=False)
        draw = ImageDraw.Draw(image)
        score_width = measure.textlength(match["score"], font=match_font(22))
        text = f"{match['map']} vs {match['opponent']}"
        draw.text((PAD + 56, row_y), _fit(measure, text, match_font(22), WIDTH - PAD * 2 - 120 - score_width),
                  font=match_font(22), fill=WHITE)
        draw.text((WIDTH - PAD - 20, row_y), match["score"], font=match_font(22), fill=MUTED, anchor="ra")
        row_y += SIDE_ROW
    return draw


def _footer(measure, week, players, start, end):
    parts = []
    idle = [player["name"] for player in players if not player["games"]]
    if idle:
        shown = idle[:4]
        text = "Didn't play: " + ", ".join(shown) + (f" +{len(idle) - len(shown)} more" if len(idle) > 4 else "")
        parts.append(text)
    if any(player["partial"] for player in players):
        parts.append("* may miss older games")
    parts.append(f"{start:%a %d %b %H:%M} – {end:%a %d %b %H:%M} UK")
    text = "  ·  ".join(parts)
    return _fit(measure, text, match_font(17), WIDTH - PAD * 2)


def draw_weekly_recap(week, map_art=None, agent_icons=None):
    """``map_art`` maps casefolded map names to splash image paths used behind the top-game cards.

    ``agent_icons`` maps casefolded agent names to images for the award tiles.
    """
    map_art = map_art or {}
    measure = ImageDraw.Draw(Image.new("RGB", (WIDTH, 1)))
    body = match_font(22)
    summary_lines = wrap_image_text(measure, week.get("summary") or "", body, WIDTH - PAD * 2, 8)
    players = week["players"]
    active = [player for player in players if player["games"]]
    mains = [player for player in active if not player["smurf"]]
    smurfs = [player for player in active if player["smurf"]]
    games = week["top_games"]
    smurf_games = week.get("smurf_top_games") or []
    premier = week.get("premier")
    awards = week.get("awards")
    changes = _rank_changes_by_account(week)

    sections = []  # (height, draw function) stacked top to bottom with GAP between
    award_height = awards_height(awards)
    if award_height:
        sections.append((award_height, lambda image, draw, y: draw_awards(image, y, awards, agent_icons)))

    rr_height = _rr_panel_height(mains, smurfs, changes)

    def draw_rr(image, draw, y):
        main_right = PAD + MAIN_COLUMN - 24 if smurfs else WIDTH - PAD
        _section_title(draw, measure, y, "RR THIS WEEK", main_right)
        draw = _draw_main_rows(image, draw, measure, y + 44, mains, changes, main_right)
        if smurfs:
            left = PAD + MAIN_COLUMN
            _section_title(draw, measure, y, "SMURFS", WIDTH - PAD, left)
            draw = _draw_smurf_rows(image, draw, measure, left, y + 44, smurfs, changes, WIDTH - PAD)
        return draw

    sections.append((rr_height, draw_rr))

    games_height = 44 + (GAME_CARD_HEIGHT if games else RR_ROW) + (14 + 64 if smurf_games else 0)

    def draw_games(image, draw, y):
        _section_title(draw, measure, y, "TOP GAMES")
        if not games:
            draw.text((PAD, y + 44), "No games to rank this week.", font=body, fill=MUTED)
        draw = _draw_game_cards(image, draw, measure, y + 44, games, map_art)
        if smurf_games:
            draw = _draw_smurf_best(image, draw, measure, y + games_height - 64, smurf_games[0])
        return draw

    sections.append((games_height, draw_games))
    if premier:
        sections.append((_premier_height(premier), lambda image, draw, y: _draw_premier(image, draw, measure, y,
                                                                                        premier)))
    if summary_lines:
        def draw_summary(image, draw, y):
            _section_title(draw, measure, y, "SUMMARY")
            for index, line in enumerate(summary_lines):
                draw.text((PAD, y + 44 + index * SUMMARY_LINE), line, font=body, fill=WHITE)
            return draw

        sections.append((44 + len(summary_lines) * SUMMARY_LINE, draw_summary))

    height = 20 + HEADER_HEIGHT + sum(GAP + section_height for section_height, _ in sections) + 60
    image = Image.new("RGB", (WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)

    # Header: date range and squad totals.
    start = week["start"].astimezone(MATCHFEED_DAY_ZONE)
    end = week["end"].astimezone(MATCHFEED_DAY_ZONE)
    draw.rounded_rectangle((20, 20, WIDTH - 20, 20 + HEADER_HEIGHT), radius=14, fill=PANEL, outline=PANEL_EDGE)
    draw.text((PAD, 38), "WEEKLY RECAP", font=match_font(20, True), fill=CORAL)
    draw.text((PAD, 66), f"{start:%d %b} – {end:%d %b}", font=match_font(50, True), fill=WHITE)
    draw.text((PAD, 128), f"{start:%a %H:%M} – {end:%a %H:%M} UK", font=match_font(21), fill=MUTED)
    squad = week["squad"]
    rank_ups = sum(change["direction"] == "up" for change in week["rank_changes"])
    tiles = (("GAMES", str(squad["games"])), ("RECORD", f"{squad['wins']}W {squad['losses']}L"),
             ("RANK UPS", str(rank_ups)))
    tile_font, right = match_font(36, True), WIDTH - PAD
    for label, value in reversed(tiles):
        tile_width = max(140, round(measure.textlength(value, font=tile_font)) + 32)
        box = (right - tile_width, 62, right, 152)
        draw.rounded_rectangle(box, radius=10, fill=TILE, outline=PANEL_EDGE)
        draw.text((box[0] + 16, box[1] + 12), label, font=match_font(15, True), fill=MUTED)
        draw.text((box[0] + 16, box[1] + 36), value, font=tile_font, fill=WHITE)
        right = box[0] - 12

    y = 20 + HEADER_HEIGHT
    for section_height, draw_section in sections:
        y += GAP
        draw = draw_section(image, draw, y)
        y += section_height

    draw.text((PAD, height - 38), _footer(measure, week, players, start, end), font=match_font(17), fill=MUTED)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    buffer.seek(0)
    return buffer
