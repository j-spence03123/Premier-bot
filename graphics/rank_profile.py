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


def at_peak(current, peak):
    """True when the player is currently sitting at their peak rank."""
    cur, top = current.get('tier') or {}, peak.get('tier') or {}
    if cur.get('id') is not None and top.get('id') is not None:
        return cur['id'] == top['id'] and cur['id'] > 2  # tiers 0-2 are unrated/unused
    name = cur.get('name')
    return bool(name) and name == top.get('name') and name.casefold() != 'unrated'


def draw_rank_profile(player_name, current, peak, current_icon=None, peak_icon=None):
    image = Image.new('RGB', (1200, 500), (17, 16, 20))
    draw = ImageDraw.Draw(image)
    white, muted, coral = (245, 244, 247), (170, 168, 178), (240, 99, 106)
    draw.rounded_rectangle((22, 22, 1178, 478), radius=18, fill=(28, 27, 32), outline=(57, 55, 63), width=2)
    draw.text((58, 70), 'RANK', font=match_font(38, True), fill=coral, anchor='lm')
    name_font = match_font(27, True)
    draw.text((1140, 70), _fit(draw, player_name, name_font, 850), font=name_font, fill=white, anchor='rm')
    draw.line((58, 108, 1142, 108), fill=(58, 56, 64), width=2)
    peaked = at_peak(current, peak)
    current_rr, peak_rr = current.get('rr'), peak.get('rr')
    # In the same tier the peak RR can't be below the current RR; HenrikDev often reports it as 0.
    if peaked and isinstance(current_rr, int) and (not isinstance(peak_rr, int) or peak_rr < current_rr):
        peak = {**peak, 'rr': current_rr}
    draw.rounded_rectangle((60, 148, 580, 450), radius=12, fill=(34, 33, 39), outline=(61, 59, 67), width=1)
    draw.rounded_rectangle((620, 148, 1140, 450), radius=12, fill=(34, 33, 39),
                           outline=coral if peaked else (61, 59, 67), width=2 if peaked else 1)

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
    if peaked:
        badge = 'AT PEAK' + (f'  ·  {str(season).upper()}' if season else '')
        draw.text((880, 419), badge, font=match_font(15, True), fill=coral, anchor='mm')
    elif season:
        draw.text((880, 419), str(season).upper(), font=match_font(15), fill=muted, anchor='mm')
    placement = (current.get('leaderboard_placement') or {}).get('rank')
    if placement:
        draw.text((58, 132), f'LEADERBOARD #{placement}', font=match_font(13), fill=muted, anchor='lm')
    return encode_png(image)
