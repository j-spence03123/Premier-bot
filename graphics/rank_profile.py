"""Render a player's current and peak rank in the rank announcement style."""

from PIL import Image, ImageDraw, ImageOps

from .assets import encode_png, match_font


def _fit(draw, value, font, width):
    value = str(value)
    if draw.textlength(value, font=font) <= width:
        return value
    while value and draw.textlength(value + '...', font=font) > width:
        value = value[:-1]
    return value.rstrip() + '...'


def draw_rank_profile(player_name, current, peak, current_icon=None, peak_icon=None):
    image = Image.new('RGB', (1200, 500), (17, 16, 20))
    draw = ImageDraw.Draw(image)
    white, muted, coral = (245, 244, 247), (170, 168, 178), (240, 99, 106)
    draw.rounded_rectangle((22, 22, 1178, 478), radius=18, fill=(28, 27, 32), outline=(57, 55, 63), width=2)
    draw.text((58, 70), 'RANK', font=match_font(38, True), fill=coral, anchor='lm')
    name_font = match_font(27, True)
    draw.text((1140, 70), _fit(draw, player_name, name_font, 850), font=name_font, fill=white, anchor='rm')
    draw.line((58, 108, 1142, 108), fill=(58, 56, 64), width=2)
    for panel in ((60, 148, 580, 450), (620, 148, 1140, 450)):
        draw.rounded_rectangle(panel, radius=12, fill=(34, 33, 39), outline=(61, 59, 67), width=1)

    for center, heading, rank, icon in ((320, 'CURRENT RANK', current, current_icon),
                                       (880, 'PEAK RANK', peak, peak_icon)):
        draw.text((center, 179), heading, font=match_font(16, True), fill=(154, 151, 161), anchor='mm')
        if icon is not None:
            fitted = ImageOps.contain(icon.convert('RGBA'), (132, 132), method=Image.Resampling.LANCZOS)
            image.paste(fitted, (center - fitted.width // 2, 203 + (132 - fitted.height) // 2), fitted)
        label = (rank.get('tier') or {}).get('name') or ('Unrated' if heading == 'CURRENT RANK' else 'Unavailable')
        font = match_font(27, True)
        draw.text((center, 356), _fit(draw, label.upper(), font, 460), font=font, fill=white, anchor='mm')
        rr = rank.get('rr')
        draw.text((center, 389), f'{rr} RR' if rr is not None else 'RR unavailable',
                  font=match_font(21, True), fill=white, anchor='mm')
    change = current.get('last_change')
    if isinstance(change, int) and not isinstance(change, bool):
        color = (77, 190, 116) if change > 0 else (224, 86, 99) if change < 0 else muted
        draw.text((320, 419), f'LAST GAME  {change:+d} RR', font=match_font(15, True), fill=color, anchor='mm')
    else:
        draw.text((320, 419), 'LAST GAME  unavailable', font=match_font(15), fill=muted, anchor='mm')
    season = (peak.get('season') or {}).get('short')
    if season:
        draw.text((880, 419), str(season).upper(), font=match_font(15), fill=muted, anchor='mm')
    placement = (current.get('leaderboard_placement') or {}).get('rank')
    if placement:
        draw.text((58, 132), f'LEADERBOARD #{placement}', font=match_font(13), fill=muted, anchor='lm')
    return encode_png(image)
