"""Render the weekly squad recap card in the bot's dark card style."""

import io

from PIL import Image, ImageDraw

from graphics.assets import match_font, wrap_image_text
from services.matchfeed import MATCHFEED_DAY_ZONE

WIDTH, PAD = 1200, 40
BACKGROUND = (17, 17, 22)
PANEL, PANEL_EDGE = (28, 27, 32), (57, 55, 63)
CORAL, GREEN = (240, 99, 106), (102, 207, 147)
GOLD = (255, 205, 90)
WHITE, MUTED, RULE = (243, 242, 246), (171, 170, 182), (64, 61, 70)
ROW, SECTION_GAP, HEADING = 40, 30, 44


def _fit(measure, text, font, width):
    while text and measure.textlength(text, font=font) > width:
        text = text[:-2] + "…"
    return text


def _rr_label(player):
    if player["rr"] is None:
        return "RR unavailable", MUTED
    if not player["games"] and not player["rr"]:
        return "no games", MUTED
    label = f"{player['rr']:+d} RR" + ("*" if player["partial"] else "")
    return label, GREEN if player["rr"] > 0 else CORAL if player["rr"] < 0 else MUTED


def _result(won):
    return ("W", GREEN) if won is True else ("L", CORAL) if won is False else ("D", MUTED)


def draw_weekly_recap(week):
    measure = ImageDraw.Draw(Image.new("RGB", (WIDTH, 1)))
    body = match_font(23)
    small = match_font(19)
    summary_lines = wrap_image_text(measure, week.get("summary") or "", body, WIDTH - PAD * 2, 8)

    players = week["players"]
    premier = week.get("premier")
    sections = [("RR THIS WEEK", max(len(players), 1) * ROW)]
    sections.append(("TOP GAMES", max(len(week["top_games"]), 1) * 52))
    sections.append(("RANK UPS", max(len(week["rank_ups"]), 1) * ROW))
    if premier:
        sections.append(("PREMIER", ROW + len(premier["matches"]) * ROW))
    if summary_lines:
        sections.append(("SUMMARY", len(summary_lines) * 32))

    header_height = 190
    height = header_height + 30 + sum(HEADING + size + SECTION_GAP for _, size in sections) + 50
    image = Image.new("RGB", (WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)

    # Header
    start = week["start"].astimezone(MATCHFEED_DAY_ZONE)
    end = week["end"].astimezone(MATCHFEED_DAY_ZONE)
    draw.rounded_rectangle((20, 16, WIDTH - 20, header_height), radius=14, fill=PANEL, outline=PANEL_EDGE, width=1)
    draw.text((PAD, 32), "WEEKLY RECAP", font=match_font(20, True), fill=CORAL)
    draw.text((PAD, 64), f"{start:%d %b} – {end:%d %b}", font=match_font(52, True), fill=WHITE)
    squad = week["squad"]
    if squad["games"]:
        noun = "game" if squad["games"] == 1 else "games"
        line = f"{squad['games']} competitive {noun} · {squad['wins']}W {squad['losses']}L as a squad"
    else:
        line = "No competitive games this week"
    draw.text((PAD, 138), line, font=body, fill=MUTED)

    y = header_height + 30
    for title, _ in sections:
        draw.text((PAD, y), title, font=match_font(20, True), fill=CORAL)
        draw.line((PAD + measure.textlength(title, font=match_font(20, True)) + 16, y + 13, WIDTH - PAD, y + 13),
                  fill=RULE)
        y += HEADING
        if title == "RR THIS WEEK":
            if not players:
                draw.text((PAD, y), "No registered players in this server.", font=body, fill=MUTED)
                y += ROW
            for player in players:
                name = player["name"] + (" (smurf)" if player["smurf"] else "")
                draw.text((PAD, y), _fit(measure, name, match_font(25), 430), font=match_font(25), fill=WHITE)
                if player["games"]:
                    noun = "game" if player["games"] == 1 else "games"
                    record = f"{player['games']} {noun} · {player['wins']}W {player['losses']}L"
                    draw.text((PAD + 450, y + 3), record, font=small, fill=MUTED)
                if player["rank"]:
                    draw.text((PAD + 720, y + 3), _fit(measure, player["rank"], small, 230), font=small, fill=MUTED)
                label, color = _rr_label(player)
                draw.text((WIDTH - PAD, y), label, font=match_font(24, True), fill=color, anchor="ra")
                y += ROW
        elif title == "TOP GAMES":
            if not week["top_games"]:
                draw.text((PAD, y), "No games to rank this week.", font=body, fill=MUTED)
                y += 52
            for index, game in enumerate(week["top_games"], 1):
                draw.text((PAD, y), f"{index}.", font=match_font(25, True), fill=GOLD if index == 1 else WHITE)
                headline = f"{game['player']} · {game['agent']} · {game['map']}"
                draw.text((PAD + 40, y), _fit(measure, headline, match_font(25), 640), font=match_font(25), fill=WHITE)
                stats = f"{game['k']}/{game['d']}/{game['a']} · {game['acs']} ACS · {game['hs']}% HS"
                draw.text((PAD + 40, y + 30), stats, font=small, fill=MUTED)
                letter, color = _result(game["won"])
                draw.text((WIDTH - PAD, y), f"{letter} {game['score']}".strip(), font=match_font(24, True),
                          fill=color, anchor="ra")
                y += 52
        elif title == "RANK UPS":
            if not week["rank_ups"]:
                draw.text((PAD, y), "No rank ups this week.", font=body, fill=MUTED)
                y += ROW
            for up in week["rank_ups"]:
                draw.text((PAD, y), _fit(measure, up["player"], match_font(25), 430), font=match_font(25), fill=WHITE)
                draw.text((WIDTH - PAD, y), f"{up['from']}  →  {up['to']}", font=match_font(24, True), fill=GREEN,
                          anchor="ra")
                y += ROW
        elif title == "PREMIER":
            record = f"{premier['wins']}W {premier['losses']}L"
            if premier["points"] is not None:
                record += f" · {premier['points']:+d} points"
            draw.text((PAD, y), record, font=match_font(25, True), fill=WHITE)
            y += ROW
            for match in premier["matches"]:
                letter, color = _result(match["won"])
                draw.text((PAD, y), letter, font=match_font(23, True), fill=color)
                text = f"{match['map']} vs {match['opponent']}"
                draw.text((PAD + 40, y), _fit(measure, text, body, 760), font=body, fill=WHITE)
                draw.text((WIDTH - PAD, y), match["score"], font=body, fill=MUTED, anchor="ra")
                y += ROW
        elif title == "SUMMARY":
            for line in summary_lines:
                draw.text((PAD, y), line, font=body, fill=WHITE)
                y += 32
        y += SECTION_GAP

    footer = f"{start:%a %d %b %H:%M} – {end:%a %d %b %H:%M} UK"
    if any(player["partial"] for player in players):
        footer += "  ·  * may miss older games"
    draw.text((PAD, height - 38), footer, font=match_font(17), fill=MUTED)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    buffer.seek(0)
    return buffer
