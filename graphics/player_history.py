"""Render recent player matches in the matchfeed visual style."""

from datetime import timezone
import re

from PIL import Image, ImageDraw, ImageOps

from .assets import draw_result_chip, draw_result_glow, encode_png, match_font
from utils.formatting import parse_time


def _date_and_time(value):
    parsed = parse_time(value)
    if not parsed:
        return "DATE UNKNOWN", "Time unavailable"
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%b %d, %Y").upper(), parsed.strftime("%H:%M UTC")


def _fit(draw, text, font, width):
    text = str(text)
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "...", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "..."


def rank_summary(mmr):
    """Extract the latest identifiable competitive act without assuming API order."""
    mmr = mmr if isinstance(mmr, dict) else {}
    current = mmr.get("current") or {}
    seasonal = mmr.get("seasonal") or []
    def season_key(item):
        short = str((item.get("season") or {}).get("short") or "")
        numbers = re.findall(r"\d+", short)
        return tuple(int(number) for number in numbers) if numbers else ()
    acts = [item for item in seasonal if isinstance(item, dict) and season_key(item)]
    act = max(acts, key=season_key) if acts else {}
    wins, games = act.get("wins"), act.get("games")
    return {"rank": (current.get("tier") or {}).get("name") or ("Unrated" if mmr else "Unavailable"),
            "tier_id": (current.get("tier") or {}).get("id"), "rr": current.get("rr"),
            "act": str((act.get("season") or {}).get("short") or "").upper(),
            "wins": wins, "games": games}


def render_player_history(name, tag, mode, rows, icons, mmr=None, rank_icon=None):
    """Draw one dated row per match; icons are preloaded Pillow images."""
    width, pad, row_h = 1200, 24, 96
    groups = []
    for row in rows:
        date, clock = _date_and_time(row.get("started"))
        if not groups or groups[-1][0] != date:
            groups.append((date, []))
        groups[-1][1].append((row, clock))
    header_end = 354
    height = header_end + 10 + sum(46 + len(items) * (row_h + 10) for _, items in groups) + 20
    image = Image.new("RGB", (width, height), (17, 17, 22))
    draw = ImageDraw.Draw(image)
    white, muted, blue, coral = (247, 246, 248), (160, 157, 168), (164, 194, 245), (240, 99, 106)
    green, panel, edge, track = (102, 207, 147), (28, 27, 32), (51, 49, 56), (46, 44, 51)
    title, body, label, value = match_font(38, True), match_font(19), match_font(14, True), match_font(22, True)
    draw.rectangle((0, 0, width, 7), fill=coral)

    # Player panel: rank badge, name, rank with an RR bar, and the act record with a win-rate bar.
    rank = rank_summary(mmr)
    draw.rounded_rectangle((pad, 28, width - pad, 208), radius=12, fill=panel, outline=edge)
    if rank_icon:
        badge = ImageOps.contain(rank_icon.convert("RGBA"), (96, 96), method=Image.Resampling.LANCZOS)
        image.paste(badge, (pad + 24 + (96 - badge.width) // 2, 70 + (96 - badge.height) // 2), badge)
    text_x = pad + 144
    draw.text((text_x, 50), _fit(draw, f"{name}#{tag}", title, 580), font=title, fill=white, anchor="lt")
    rank_line = rank["rank"] + (f"  ·  {rank['rr']} RR" if rank["rr"] is not None else "")
    draw.text((text_x, 106), _fit(draw, rank_line, match_font(24, True), 580), font=match_font(24, True),
              fill=white, anchor="lt")
    if isinstance(rank["rr"], int):
        bar_w = 300
        draw.rounded_rectangle((text_x, 150, text_x + bar_w, 158), radius=4, fill=track)
        filled = round(bar_w * max(0, min(rank["rr"], 100)) / 100)
        if filled:
            draw.rounded_rectangle((text_x, 150, text_x + max(filled, 8), 158), radius=4, fill=blue)
        rr_text = f"{rank['rr']} / 100 RR" if rank["rr"] <= 100 else f"{rank['rr']} RR"
        draw.text((text_x + bar_w + 14, 154), rr_text, font=match_font(15), fill=muted, anchor="lm")
    draw.line((770, 52, 770, 184), fill=edge, width=2)
    act_x, act_right = 800, width - pad - 28
    draw.text((act_x, 52), f"{rank['act']} · ACT RECORD" if rank["act"] else "ACT RECORD", font=label,
              fill=muted, anchor="lt")
    wins_act, games_act = rank["wins"], rank["games"]
    if isinstance(wins_act, int) and isinstance(games_act, int) and 0 <= wins_act <= games_act and games_act:
        losses_act = games_act - wins_act
        record_font = match_font(32, True)
        draw.text((act_x, 78), f"{wins_act}W", font=record_font, fill=green, anchor="lt")
        offset = draw.textlength(f"{wins_act}W  ", font=record_font)
        draw.text((act_x + offset, 78), f"{losses_act}L", font=record_font, fill=coral, anchor="lt")
        split = act_x + round((act_right - act_x) * wins_act / games_act)
        draw.rounded_rectangle((act_x, 134, act_right, 142), radius=4, fill=coral)
        if wins_act:
            draw.rounded_rectangle((act_x, 134, max(split, act_x + 8), 142), radius=4, fill=green)
        draw.text((act_x, 158), f"{games_act} games  ·  {round(100 * wins_act / games_act)}% win rate",
                  font=match_font(16), fill=muted, anchor="lt")
    else:
        draw.text((act_x, 82), "—", font=match_font(32, True), fill=muted, anchor="lt")
        draw.text((act_x, 158), "Act stats unavailable", font=match_font(16), fill=muted, anchor="lt")

    # Stats strip for the matches below, with a form guide (oldest to newest, left to right).
    wins = sum(row.get("won") is True for row in rows)
    losses = sum(row.get("won") is False for row in rows)
    kills, deaths = sum(row["k"] for row in rows), sum(row["d"] for row in rows)
    average = lambda key: round(sum(row[key] for row in rows) / len(rows)) if rows else 0
    draw.rounded_rectangle((pad, 228, width - pad, 330), radius=12, fill=panel, outline=edge)
    draw.text((pad + 24, 250), f"LAST {len(rows)} · {mode.upper()}", font=label, fill=muted, anchor="lt")
    record = f"{wins}W {losses}L"
    draw.text((pad + 24, 276), record, font=match_font(26, True), fill=white, anchor="lt")
    dot_x = pad + 24 + draw.textlength(record, font=match_font(26, True)) + 22
    for row in reversed(rows[:10]):
        won = row.get("won")
        colour = green if won is True else coral if won is False else muted
        draw.ellipse((dot_x, 283, dot_x + 14, 297), fill=colour)
        dot_x += 20
    first_cell = 400
    draw.line((pad + first_cell, 248, pad + first_cell, 310), fill=edge, width=2)
    summaries = [("K/D", f"{kills / max(deaths, 1):.2f}"), ("AVG ACS", str(average("acs"))),
                 ("AVG ADR", str(average("adr"))), ("AVG HS", f"{average('hs')}%")]
    cell = (width - 2 * pad - first_cell) / len(summaries)
    for index, (heading, text) in enumerate(summaries):
        x = pad + first_cell + cell * (index + 0.5)
        draw.text((x, 258), heading, font=label, fill=muted, anchor="mm")
        draw.text((x, 292), text, font=match_font(26, True), fill=white, anchor="mm")

    y = header_end
    for date, items in groups:
        draw.text((pad, y + 17), f"{date}  ·  {len(items)} MATCH{'ES' if len(items) != 1 else ''}",
                  font=match_font(18, True), fill=coral, anchor="lm")
        y += 46
        for row, clock in items:
            won = row.get("won")
            accent = (76, 190, 116) if won is True else (225, 90, 98) if won is False else (154, 151, 160)
            draw.rounded_rectangle((pad, y, width - pad, y + row_h), radius=9,
                                   fill=(28, 27, 32), outline=(51, 49, 56))
            draw_result_glow(image, (pad + 1, y + 1, width - pad - 1, y + row_h - 1), accent)
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((pad, y + 14, pad + 5, y + row_h - 14), radius=2, fill=accent)
            icon = icons.get((row.get("agent_id") or row.get("agent") or "").casefold())
            if icon:
                icon = ImageOps.contain(icon.convert("RGBA"), (68, 68), method=Image.Resampling.LANCZOS)
                image.paste(icon, (pad + 16 + (68 - icon.width) // 2, y + 14 + (68 - icon.height) // 2), icon)
            else:
                draw.text((pad + 50, y + 48), "?", font=value, fill=muted, anchor="mm")
            draw.text((pad + 100, y + 23), f"{clock}  ·  {mode.title()}", font=match_font(14), fill=muted, anchor="lm")
            draw.text((pad + 100, y + 53), _fit(draw, row.get("map", "?"), value, 170), font=value, fill=white, anchor="lm")
            draw.text((pad + 100, y + 76), _fit(draw, row.get("agent", "?"), match_font(14), 170),
                      font=match_font(14), fill=muted, anchor="lm")
            kd = row["k"] / max(row["d"], 1)
            fields = [("SCORE", row.get("score") or "—", accent), ("K/D", f"{kd:.2f}", white),
                      ("K/D/A", f"{row['k']}/{row['d']}/{row['a']}", blue),
                      ("ADR", str(row["adr"]), white), ("HS%", f"{row['hs']}%", white),
                      ("ACS", str(row["acs"]), white)]
            # Rank at the time of the match, in its own column after the map and agent.
            draw.text((345, y + 30), "RANK", font=label, fill=muted, anchor="mm")
            tier_icon = icons.get(f"tier:{row.get('tier')}") if row.get("tier") else None
            if tier_icon:
                tier_icon = ImageOps.contain(tier_icon.convert("RGBA"), (38, 38), method=Image.Resampling.LANCZOS)
                image.paste(tier_icon, (345 - tier_icon.width // 2, y + 62 - tier_icon.height // 2), tier_icon)
            else:
                draw.text((345, y + 62), "—", font=value, fill=muted, anchor="mm")
            for (heading, text, colour), x in zip(fields, (460, 575, 710, 850, 970, 1090)):
                draw.text((x, y + 30), heading, font=label, fill=muted, anchor="mm")
                if heading == "SCORE":
                    draw_result_chip(image, (x - 52, y + 45, x + 52, y + 79), colour, text, value)
                    draw = ImageDraw.Draw(image)
                else:
                    draw.text((x, y + 62), text, font=value, fill=colour, anchor="mm")
            y += row_h + 10
    return encode_png(image)
