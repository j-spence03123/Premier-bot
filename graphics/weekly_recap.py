"""Render the weekly squad recap card in the bot's dark card style."""

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from graphics.assets import match_font, wrap_image_text
from services.matchfeed import MATCHFEED_DAY_ZONE

WIDTH, PAD = 1200, 40
BACKGROUND = (17, 17, 22)
PANEL, PANEL_EDGE = (28, 27, 32), (57, 55, 63)
TILE = (38, 37, 43)
CORAL, GREEN, GOLD, GOLD_EDGE = (240, 99, 106), (102, 207, 147), (255, 205, 90), (107, 90, 42)
SILVER, SILVER_EDGE = (205, 212, 222), (88, 92, 102)
BRONZE, BRONZE_EDGE = (214, 140, 84), (104, 70, 44)
PODIUM = ((GOLD, GOLD_EDGE), (SILVER, SILVER_EDGE), (BRONZE, BRONZE_EDGE))
WHITE, MUTED, RULE = (243, 242, 246), (171, 170, 182), (64, 61, 70)

HEADER_HEIGHT = 170
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


def _section_title(draw, measure, y, title):
    font = match_font(20, True)
    draw.text((PAD, y), title, font=font, fill=CORAL)
    draw.line((PAD + measure.textlength(title, font=font) + 16, y + 13, WIDTH - PAD, y + 13), fill=RULE)


def _rr_text(player):
    if player["rr"] is None:
        return "RR unavailable", MUTED
    if not player["games"] and not player["rr"]:
        return "no games", MUTED
    label = f"{player['rr']:+d} RR" + ("*" if player["partial"] else "")
    return label, GREEN if player["rr"] > 0 else CORAL if player["rr"] < 0 else MUTED


def _draw_rank_movement(draw, measure, right, y, change, color):
    """'Gold 3 -> Platinum 1' right-aligned at ``right``; the arrow is drawn so it never depends on font glyphs."""
    font = match_font(21, True)
    to_width = measure.textlength(change["to"], font=font)
    from_width = measure.textlength(change["from"], font=font)
    arrow_width, gap = 22, 12
    to_left = right - to_width
    arrow_right = to_left - gap
    arrow_left = arrow_right - arrow_width
    draw.text((to_left, y), change["to"], font=font, fill=color)
    draw.text((arrow_left - gap - from_width, y), change["from"], font=font, fill=color)
    middle = y + 13
    draw.line((arrow_left, middle, arrow_right, middle), fill=color, width=3)
    draw.line((arrow_right - 7, middle - 7, arrow_right, middle, arrow_right - 7, middle + 7), fill=color, width=3,
              joint="curve")
    return to_width + from_width + arrow_width + gap * 2


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


def _side_panel_height(week):
    changes = max(len(week["rank_changes"]), 1)
    premier = week.get("premier")
    rows = max(changes, len(premier["matches"])) if premier else changes
    return 64 + rows * SIDE_ROW + 10


def draw_weekly_recap(week, map_art=None):
    """``map_art`` maps casefolded map names to splash image paths used behind the top-game cards."""
    map_art = map_art or {}
    measure = ImageDraw.Draw(Image.new("RGB", (WIDTH, 1)))
    body = match_font(23)
    small = match_font(19)
    summary_lines = wrap_image_text(measure, week.get("summary") or "", body, WIDTH - PAD * 2, 8)
    players = week["players"]
    games = week["top_games"]
    premier = week.get("premier")

    rr_height = 44 + max(len(players), 1) * RR_ROW
    games_height = 44 + (GAME_CARD_HEIGHT if games else RR_ROW)
    side_height = _side_panel_height(week)
    summary_height = (44 + len(summary_lines) * SUMMARY_LINE) if summary_lines else 0
    height = (20 + HEADER_HEIGHT + GAP + rr_height + GAP + games_height + GAP + side_height
              + (GAP + summary_height if summary_height else 0) + 60)
    image = Image.new("RGB", (WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)

    # Header with date range and two stat tiles.
    start = week["start"].astimezone(MATCHFEED_DAY_ZONE)
    end = week["end"].astimezone(MATCHFEED_DAY_ZONE)
    draw.rounded_rectangle((20, 20, WIDTH - 20, 20 + HEADER_HEIGHT), radius=14, fill=PANEL, outline=PANEL_EDGE)
    draw.text((PAD, 40), "WEEKLY RECAP", font=match_font(20, True), fill=CORAL)
    draw.text((PAD, 70), f"{start:%d %b} – {end:%d %b}", font=match_font(54, True), fill=WHITE)
    draw.text((PAD, 142), f"{start:%a %H:%M} – {end:%a %H:%M} UK", font=body, fill=MUTED)
    squad = week["squad"]
    tiles = (("GAMES", str(squad["games"])), ("RECORD", f"{squad['wins']}W {squad['losses']}L"))
    tile_font, right = match_font(38, True), WIDTH - PAD
    for label, value in reversed(tiles):
        tile_width = max(150, round(measure.textlength(value, font=tile_font)) + 32)
        box = (right - tile_width, 70, right, 166)
        draw.rounded_rectangle(box, radius=10, fill=TILE, outline=PANEL_EDGE)
        draw.text((box[0] + 16, box[1] + 14), label, font=match_font(15, True), fill=MUTED)
        draw.text((box[0] + 16, box[1] + 38), value, font=tile_font, fill=WHITE)
        right = box[0] - 12

    # RR list with a bar that grows right for gains and left for losses.
    y = 20 + HEADER_HEIGHT + GAP
    _section_title(draw, measure, y, "RR THIS WEEK")
    y += 44
    if not players:
        draw.text((PAD, y), "No registered players in this server.", font=body, fill=MUTED)
    biggest = max([abs(player["rr"]) for player in players if player["rr"]] or [1])
    bar_left, bar_right = PAD + 440, WIDTH - PAD - 150
    middle = (bar_left + bar_right) // 2
    for player in players:
        name = player["name"] + (" (smurf)" if player["smurf"] else "")
        draw.text((PAD, y), _fit(measure, name, match_font(25), 220), font=match_font(25),
                  fill=WHITE if player["games"] else MUTED)
        record = (f"{_plural(player['games'], 'game')} · {player['wins']}W {player['losses']}L"
                  if player["games"] else "No games")
        draw.text((PAD + 230, y + 4), _fit(measure, record, small, 200), font=small, fill=MUTED)
        bar_y = y + 12
        draw.rounded_rectangle((bar_left, bar_y, bar_right, bar_y + 10), radius=5, fill=TILE)
        if player["rr"]:
            length = max(6, round((middle - bar_left) * min(abs(player["rr"]) / biggest, 1)))
            if player["rr"] > 0:
                draw.rounded_rectangle((middle, bar_y, middle + length, bar_y + 10), radius=5, fill=GREEN)
            else:
                draw.rounded_rectangle((middle - length, bar_y, middle, bar_y + 10), radius=5, fill=CORAL)
        label, color = _rr_text(player)
        draw.text((WIDTH - PAD, y), label, font=match_font(24, True), fill=color, anchor="ra")
        y += RR_ROW

    # Top games as three side-by-side cards.
    y = 20 + HEADER_HEIGHT + GAP + rr_height + GAP
    _section_title(draw, measure, y, "TOP GAMES")
    y += 44
    if not games:
        draw.text((PAD, y), "No games to rank this week.", font=body, fill=MUTED)
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
        draw.text((right - 18, y + 20), f"{letter} {game['score']}".strip(), font=match_font(22, True),
                  fill=color, anchor="ra")
        draw.text((inner, y + 62), _fit(measure, f"{game['player']} · {game['agent']}", match_font(24),
                                        card_width - 36), font=match_font(24), fill=WHITE)
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

    # Rank changes and Premier side by side (rank changes fill the row without Premier).
    y = 20 + HEADER_HEIGHT + GAP + rr_height + GAP + games_height + GAP
    panel_gap = 14
    half = (WIDTH - PAD * 2 - panel_gap) // 2
    rank_right = PAD + half if premier else WIDTH - PAD
    draw.rounded_rectangle((PAD, y, rank_right, y + side_height), radius=12, fill=PANEL, outline=PANEL_EDGE)
    draw.text((PAD + 20, y + 18), "RANK CHANGES", font=match_font(20, True), fill=CORAL)
    row_y = y + 64
    if not week["rank_changes"]:
        draw.text((PAD + 20, row_y), "No rank changes this week.", font=body, fill=MUTED)
    for change in week["rank_changes"]:
        color = GREEN if change["direction"] == "up" else CORAL
        movement_width = _draw_rank_movement(draw, measure, rank_right - 20, row_y + 2, change, color)
        draw.text((PAD + 20, row_y), _fit(measure, change["player"], match_font(23),
                                          rank_right - PAD - 60 - movement_width), font=match_font(23), fill=WHITE)
        row_y += SIDE_ROW
    if premier:
        left = PAD + half + panel_gap
        draw.rounded_rectangle((left, y, WIDTH - PAD, y + side_height), radius=12, fill=PANEL, outline=PANEL_EDGE)
        draw.text((left + 20, y + 18), "PREMIER", font=match_font(20, True), fill=CORAL)
        record = f"{premier['wins']}W {premier['losses']}L"
        points = f" · {premier['points']:+d} points" if premier["points"] is not None else ""
        bold = match_font(21, True)
        points_color = GREEN if (premier["points"] or 0) >= 0 else CORAL
        draw.text((WIDTH - PAD - 20, y + 18), points, font=bold, fill=points_color, anchor="ra")
        draw.text((WIDTH - PAD - 20 - measure.textlength(points, font=bold), y + 18), record, font=bold,
                  fill=WHITE, anchor="ra")
        row_y = y + 64
        for match in premier["matches"]:
            letter, color = _result(match)
            draw.text((left + 20, row_y), letter, font=match_font(22, True), fill=color)
            score_width = measure.textlength(match["score"], font=match_font(22))
            text = f"{match['map']} vs {match['opponent']}"
            draw.text((left + 56, row_y), _fit(measure, text, match_font(22), half - 100 - score_width),
                      font=match_font(22), fill=WHITE)
            draw.text((WIDTH - PAD - 20, row_y), match["score"], font=match_font(22), fill=MUTED, anchor="ra")
            row_y += SIDE_ROW

    # Summary paragraph.
    if summary_lines:
        y += side_height + GAP
        _section_title(draw, measure, y, "SUMMARY")
        y += 44
        for line in summary_lines:
            draw.text((PAD, y), line, font=body, fill=WHITE)
            y += SUMMARY_LINE

    footer = f"{start:%a %d %b %H:%M} – {end:%a %d %b %H:%M} UK"
    if any(player["partial"] for player in players):
        footer += "  ·  * may miss older games"
    draw.text((PAD, height - 38), footer, font=match_font(17), fill=MUTED)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    buffer.seek(0)
    return buffer
