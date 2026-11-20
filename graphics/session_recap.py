"""Render session summaries with the bot's existing Pillow card style."""

import io
from PIL import Image, ImageDraw

from graphics.assets import draw_result_chip, draw_result_glow, match_font, wrap_image_text
from services.matchfeed import MATCHFEED_DAY_ZONE
from utils.formatting import parse_time
from utils.session_summary import session_rr_totals


def draw_session_recap(session):
    matches = session["matches"]
    wins = sum(match["result"] == "W" for match in matches)
    losses = sum(match["result"] == "L" for match in matches)
    draws = len(matches) - wins - losses
    width, pad = 1200, 40
    font = match_font(23)
    measure = ImageDraw.Draw(Image.new("RGB", (width, 1)))
    player_totals = session_rr_totals(session)
    moments = sorted(
        [(moment["priority"], index, match["map"], moment["text"])
         for index, match in enumerate(matches, 1) for moment in match.get("moments", [])],
        key=lambda item: item[0], reverse=True,
    )[:2]
    paragraphs = [f"Game {index} · {map_name} — {text}" for _, index, map_name, text in moments]
    if session.get("summary"):
        paragraphs = [session["summary"]]
    elif wins:
        best = max((match for match in matches if match["result"] == "W"), key=lambda match: match["margin"])
        paragraphs.append(f"Biggest win · {best['map']} {best['score']}")
    paragraphs.extend(dict.fromkeys(change for match in matches for change in match.get("rank_changes", [])))
    lines = [wrap_image_text(measure, text, font, width - pad * 2, 12) for text in paragraphs]
    names_height = len(player_totals) * 38
    results_top = 208 + names_height
    story_top = results_top + len(matches) * 40 + 38
    height = story_top + sum(len(block) * 32 + 18 for block in lines) + 58
    image = Image.new("RGB", (width, height), (17, 17, 22))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((20, 16, width - 20, results_top - 22), radius=14,
                           fill=(28, 27, 32), outline=(57, 55, 63), width=1)
    coral, white, muted = (240, 99, 106), (243, 242, 246), (171, 170, 182)
    draw.text((pad, 32), "SESSION RECAP", font=match_font(20, True), fill=coral)
    record = f"{wins}W  {losses}L" + (f"  {draws}D" if draws else "")
    draw.text((pad, 66), record, font=match_font(56, True), fill=white)
    noun = "game" if len(matches) == 1 else "games"
    draw.text((pad, 140), f"{len(matches)} {noun} · {'Group' if len(session['players']) > 1 else 'Solo'} session",
              font=font, fill=muted)
    for index, player in enumerate(player_totals):
        y = 180 + index * 38
        name = player["player"]
        name_font = match_font(26)
        while measure.textlength(name, font=name_font) > 650:
            name = name[:-2] + "…"
        draw.text((pad, y), name, font=name_font, fill=white)
        rr = player["rr"]
        label = f"{rr:+d} RR" if rr is not None else f"RR unavailable ({player['covered_games']}/{player['total_games']} games)"
        color = (102, 207, 147) if rr is not None and rr > 0 else coral if rr is not None and rr < 0 else muted
        draw.text((width - pad, y), label, font=match_font(23, True), fill=color, anchor="ra")
    for index, match in enumerate(matches):
        y = results_top + index * 40
        color = (102, 207, 147) if match["result"] == "W" else coral if match["result"] == "L" else muted
        draw_result_glow(image, (pad - 12, y - 4, width - pad + 12, y + 32), color, radius=8, opacity=55, fade_at=0.6)
        draw_result_chip(image, (pad, y - 2, pad + 34, y + 30), color, match["result"], match_font(19, True))
        draw = ImageDraw.Draw(image)
        draw.text((pad + 50, y), match["map"], font=font, fill=white)
        draw.text((width - pad, y), match["score"], font=font, fill=muted, anchor="ra")
    draw.line((pad, story_top - 20, width - pad, story_top - 20), fill=(64, 61, 70))
    y = story_top
    for block in lines:
        for line in block:
            draw.text((pad, y), line, font=font, fill=white)
            y += 32
        y += 18
    ended = parse_time(session["last_finished"]).astimezone(MATCHFEED_DAY_ZONE)
    draw.text((pad, height - 35), f"Last game finished {ended:%d %b · %H:%M} UK",
              font=match_font(17), fill=muted)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    buffer.seek(0)
    return buffer
