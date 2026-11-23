"""Numbered strip of won and lost rounds, shared by card renderers."""

from PIL import ImageDraw

from .assets import draw_soft_box, match_font

def _round_number(round_data, index):
    number = round_data.get("id")
    return number if isinstance(number, int) else index


ROUND_WIN = ((33, 88, 58), (160, 236, 190))
ROUND_LOSS = ((104, 36, 44), (255, 168, 174))
ROUND_STRIP_HEIGHT = 58


def round_results(detail, team_id, won, lost):
    """Whether the squad won each round, in order, or None when rounds can't be matched to the score."""
    rows = detail.get("rounds") or []
    side = str(team_id or "").casefold()
    if not side or not rows or len(rows) != won + lost:
        return None
    results = []
    for _, row in sorted(enumerate(rows), key=lambda item: _round_number(item[1], item[0])):
        winner = str(row.get("winning_team") or "").casefold()
        if not winner:
            return None
        results.append(winner == side)
    return results if sum(results) == won else None


def draw_round_strip(image, center_y, results, width, side_pad, won_style=ROUND_WIN, lost_style=ROUND_LOSS):
    """One numbered block per round across the card, green for won and red for lost, split at halftime."""
    breaks = [index for index in (12, 24) if index < len(results)]
    divider, gap, count = 18, 4, len(results)
    cell = min(56, (width - 2 * side_pad - divider * len(breaks) - gap * (count - 1)) / count)
    x = (width - (cell * count + gap * (count - 1) + divider * len(breaks))) / 2
    number_font = match_font(13, True)
    draw = ImageDraw.Draw(image)
    for index, won_round in enumerate(results):
        if index in breaks:
            line_x = x - gap / 2 + divider / 2
            draw.line((line_x, center_y - 19, line_x, center_y + 19), fill=(240, 99, 106), width=2)
            x += divider
        fill, text = won_style if won_round else lost_style
        left, right = round(x), round(x + cell)
        draw_soft_box(image, (left, center_y - 15, right, center_y + 15), fill, opacity=255, radius=6,
                      outline=(*text, 105))
        draw = ImageDraw.Draw(image)
        draw.text(((left + right) / 2, center_y), str(index + 1), font=number_font, fill=text, anchor="mm")
        x += cell + gap
