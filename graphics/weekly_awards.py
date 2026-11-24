"""Player of the week and individual award tiles for the weekly recap, in the match feed tile style."""

from PIL import Image, ImageDraw, ImageOps

from graphics.assets import PLAY_TAG_STYLES, draw_soft_box, match_font, readable_font, wrap_image_text

PAD, SECTION_TITLE, SECTION_GAP = 40, 44, 26
HERO_HEIGHT, HERO_ICON, HERO_STATS_LEFT = 182, 100, 680
TILE_HEIGHT, TILE_GAP, TILE_ICON, COLUMNS = 150, 16, 62, 2
BACKGROUND, TILE, TILE_EDGE = (17, 17, 22), (28, 27, 31), (42, 40, 45)
GOLD, GOLD_EDGE, GOLD_PANEL = (255, 205, 90), (107, 90, 42), (34, 31, 24)
CORAL, WHITE, LABEL, RULE = (240, 99, 106), (247, 246, 248), (154, 151, 160), (64, 61, 70)
PLAYER_BLUE, BODY = (164, 194, 245), (214, 213, 220)

# Purple for cheeky, red for roasts, matching the match feed tags.
AWARD_STYLES = {
    "YO-YO": PLAY_TAG_STYLES["EXIT FARMER"],
    "ON TILT": PLAY_TAG_STYLES["CHOKER"],
    "CLUTCH ZERO": PLAY_TAG_STYLES["VICTIM"],
    "FREE FALL": PLAY_TAG_STYLES["LVP"],
    "CAMEO": PLAY_TAG_STYLES["TOURIST"],
    "BOTTOM FRAG": PLAY_TAG_STYLES["BAITED"],
    "BODY SHOOTER": PLAY_TAG_STYLES["BODY SHOOTER"],
    "PASSENGER": PLAY_TAG_STYLES["PASSENGER"],
    "NO LIFE": PLAY_TAG_STYLES["KILL STEALER"],
    "LVP MAGNET": PLAY_TAG_STYLES["LVP"],
    "CARRIED": PLAY_TAG_STYLES["ECO FRAUD"],
    "KD PLAYER": PLAY_TAG_STYLES["KNIFED"],
    "NPC": PLAY_TAG_STYLES["AFK"],  # grey: nothing to see here
}
DEFAULT_STYLE = ((68, 68, 78), (235, 235, 240))


def awards_height(awards):
    if not awards:
        return 0
    rows = (len(awards["awards"]) + COLUMNS - 1) // COLUMNS
    height = SECTION_TITLE + HERO_HEIGHT
    if rows:
        height += SECTION_GAP + SECTION_TITLE + rows * (TILE_HEIGHT + TILE_GAP) - TILE_GAP
    return height


def _section_title(draw, width, y, title):
    font = match_font(20, True)
    draw.text((PAD, y), title, font=font, fill=CORAL)
    draw.line((PAD + draw.textlength(title, font=font) + 16, y + 13, width - PAD, y + 13), fill=RULE)


def _paste_icon(image, draw, icon, x, y, size, edge=None):
    draw.rounded_rectangle((x, y, x + size, y + size), radius=8, fill=TILE, outline=edge)
    if icon is not None:
        icon = ImageOps.contain(icon.convert("RGBA"), (size, size), method=Image.Resampling.LANCZOS)
        image.paste(icon, (x + (size - icon.width) // 2, y + (size - icon.height) // 2), icon)


def _tag(image, x, y, text, style):
    """Match feed tag chip; returns the draw handle for the updated image."""
    font = match_font(14, True)
    fill, colour, *opacity = style
    width = int(ImageDraw.Draw(image).textlength(text, font=font)) + 16
    draw_soft_box(image, (x, y, x + width, y + 30), fill, opacity=opacity[0] if opacity else 88, radius=5,
                  outline=(*colour, 105) if not opacity else None)
    draw = ImageDraw.Draw(image)
    bbox = font.getbbox(text, anchor="mm")
    draw.text((x + width / 2, y + 15 - (bbox[1] + bbox[3]) / 2), text, font=font, fill=colour, anchor="mm")
    return draw


def _crown(draw, x, y, width=30, height=22):
    draw.polygon([(x, y + height), (x, y + 6), (x + width * 0.27, y + height * 0.55), (x + width / 2, y),
                  (x + width * 0.73, y + height * 0.55), (x + width, y + 6), (x + width, y + height)], fill=GOLD)


def _fit(draw, text, font, width):
    while text and draw.textlength(text, font=font) > width:
        text = text[:-2] + "…"
    return text


def _icon(icons, entry):
    return (icons or {}).get(str(entry.get("agent") or "").casefold())


def draw_awards(image, y, awards, icons=None):
    """Draw the awards section with its top edge at ``y``; returns the draw handle."""
    width = image.width
    draw = ImageDraw.Draw(image)
    potw = awards["player_of_the_week"]

    _section_title(draw, width, y, "PLAYER OF THE WEEK")
    y += SECTION_TITLE
    draw.rounded_rectangle((PAD, y, width - PAD, y + HERO_HEIGHT), radius=14, fill=GOLD_PANEL, outline=GOLD_EDGE,
                           width=2)
    _paste_icon(image, draw, _icon(icons, potw), PAD + 22, y + 22, HERO_ICON, edge=GOLD_EDGE)
    _crown(draw, PAD + 22 + (HERO_ICON - 30) // 2, y + 132)
    # Name, tag and blurb on the left; the stat cells sit on the right of a divider.
    x, text_right = PAD + 146, HERO_STATS_LEFT - 30
    chip = "TOP CLIMBER" if potw.get("by_rr") else f"LEADS {len(potw['leads'])} OF {len(potw['stats'])} STATS"
    chip_width = int(draw.textlength(chip, font=match_font(14, True))) + 16
    name_room, size = text_right - x - chip_width - 14, 34
    name_font = readable_font(potw["player"], size, True)
    while size > 26 and draw.textlength(potw["player"], font=name_font) > name_room:
        size -= 1
        name_font = readable_font(potw["player"], size, True)
    name = _fit(draw, potw["player"], name_font, name_room)
    draw.text((x, y + 20), name, font=name_font, fill=GOLD)
    draw = _tag(image, x + int(draw.textlength(name, font=name_font)) + 14, y + 27, chip, PLAY_TAG_STYLES["MVP"])
    body = readable_font(potw["line"], 20)
    for index, line in enumerate(wrap_image_text(draw, potw["line"], body, text_right - x, 3)):
        draw.text((x, y + 72 + index * 28), line, font=body, fill=BODY)
    draw.line((HERO_STATS_LEFT - 20, y + 30, HERO_STATS_LEFT - 20, y + HERO_HEIGHT - 30), fill=GOLD_EDGE)
    cell_width = (width - PAD - 24 - HERO_STATS_LEFT) // len(potw["stats"])
    for index, stat in enumerate(potw["stats"]):
        centre = HERO_STATS_LEFT + index * cell_width + cell_width // 2
        draw.text((centre, y + 72), stat["label"], font=match_font(16), fill=LABEL, anchor="mm")
        draw.text((centre, y + 106), stat["value"], font=match_font(28, True), fill=GOLD if stat["lead"] else WHITE,
                  anchor="mm")
        if stat["lead"]:
            draw.rounded_rectangle((centre - 14, y + 128, centre + 14, y + 132), radius=2, fill=GOLD)

    tiles = awards["awards"]
    if not tiles:
        return draw
    y += HERO_HEIGHT + SECTION_GAP
    _section_title(draw, width, y, "INDIVIDUAL AWARDS")
    y += SECTION_TITLE
    rows = (len(tiles) + COLUMNS - 1) // COLUMNS
    tile_width = (width - PAD * 2 - TILE_GAP) // COLUMNS
    value_font, label_font, line_font = match_font(28, True), match_font(15), match_font(18)
    for index, award in enumerate(tiles):
        column, row = index % COLUMNS, index // COLUMNS
        if len(tiles) % COLUMNS and row == rows - 1:
            left = (width - tile_width) // 2
        else:
            left = PAD + column * (tile_width + TILE_GAP)
        top = y + row * (TILE_HEIGHT + TILE_GAP)
        right = left + tile_width
        draw.rounded_rectangle((left, top, right, top + TILE_HEIGHT), radius=14, fill=TILE, outline=TILE_EDGE)
        _paste_icon(image, draw, _icon(icons, award), left + 16, top + 16, TILE_ICON)
        value_width = max(draw.textlength(award["value"], font=value_font),
                          draw.textlength(award["label"], font=label_font))
        name_font = readable_font(award["player"], 23, True)
        name_left = left + 94
        draw.text((name_left, top + 16), _fit(draw, award["player"], name_font, right - 40 - value_width - name_left),
                  font=name_font, fill=PLAYER_BLUE, anchor="lt")
        draw = _tag(image, name_left, top + 50, award["award"], AWARD_STYLES.get(award["award"], DEFAULT_STYLE))
        draw.text((right - 20, top + 26), award["label"], font=label_font, fill=LABEL, anchor="rm")
        draw.text((right - 20, top + 60), award["value"], font=value_font, fill=WHITE, anchor="rm")
        for line_index, line in enumerate(wrap_image_text(draw, award["line"], line_font, tile_width - 36, 2)):
            draw.text((left + 18, top + 94 + line_index * 25), line, font=line_font, fill=BODY)
    return draw
