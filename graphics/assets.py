"""Shared font, color, and drawing helpers for Pillow renderers."""

from pathlib import Path
import io

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps


FONT_REG = [
    "segoeui.ttf", "arial.ttf", "DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
]
FONT_BOLD = [
    "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
]
FONT_SERIF = [
    "Georgia.ttf", "DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
]
FONT_SERIF_BOLD = [
    "Georgia Bold.ttf", "DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
]
MATCH_FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"

COLS = [("ACS", 500), ("K", 565), ("D", 610), ("A", 655), ("+/-", 715), ("K/D", 780), ("ADR", 845), ("HS%", 910), ("FB", 965)]
GREY = (150, 162, 175)
WHITE = (240, 244, 248)
# Tag chip styles: (box colour, text colour[, box opacity]). Each tag gets its own hue so
# chips are recognisable at a glance; ACE and TEAM KILLER use a solid box to stand out.
PLAY_TAG_STYLES = {
    # Gold: big moments
    "MVP": ((104, 87, 39), (238, 214, 139)),            # gold
    "ACE": ((255, 196, 60), (40, 26, 0), 235),          # solid gold
    "KNIFE": ((255, 228, 140), (45, 32, 0), 235),       # solid pale gold
    "QUAD": ((104, 98, 39), (238, 230, 139)),           # yellow-gold
    "CLUTCH": ((104, 77, 39), (238, 197, 139)),         # amber
    # Green and teal: good play
    "ENTRY": ((39, 104, 71), (139, 238, 189)),          # green
    "SURVIVOR": ((39, 104, 50), (139, 238, 156)),       # leaf green
    "ASSIST KING": ((39, 104, 93), (139, 238, 222)),    # teal
    "DAMAGE DEALER": ((66, 104, 39), (180, 238, 139)),  # lime
    "DINK MACHINE": ((50, 104, 39), (156, 238, 139)),   # fresh green
    "OPERATOR": ((39, 98, 104), (139, 230, 238)),       # cyan
    "PLANTER": ((50, 93, 79), (156, 222, 200)),         # sage
    "MARTYR": ((84, 80, 66), (236, 228, 196)),          # halo ivory
    # Purple: cheeky
    "ECO FRAUD": ((77, 39, 104), (197, 139, 238)),      # purple
    "EXIT FARMER": ((55, 39, 104), (164, 139, 238)),    # indigo
    "BODY SHOOTER": ((98, 39, 104), (230, 139, 238)),   # orchid
    "PASSENGER": ((56, 56, 86), (165, 165, 212)),       # dusty lavender
    "KILL STEALER": ((110, 30, 80), (255, 130, 200)),   # hot pink
    # Red: roasts
    "BAITED": ((104, 39, 55), (238, 139, 164)),         # rose
    "LVP": ((104, 39, 39), (238, 139, 139)),            # red
    "VICTIM": ((125, 16, 36), (255, 196, 204), 235),    # solid crimson
    "TEAM KILLER": ((200, 30, 30), (255, 255, 255), 235),  # solid red
    "CHOKER": ((104, 58, 32), (240, 170, 120)),         # rust
    "TOURIST": ((88, 72, 52), (224, 196, 160)),         # sand
    "KNIFED": ((44, 44, 52), (255, 140, 140)),          # steel with red text
    "AFK": ((70, 72, 80), (205, 208, 218)),             # grey
}


def font(size, bold=False, serif=False):
    candidates = (FONT_SERIF_BOLD if bold else FONT_SERIF) if serif else (FONT_BOLD if bold else FONT_REG)
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def match_font(size, bold=False, serif=False):
    """Use bundled match-card fonts so Windows and Linux render consistently."""
    name = ("Lora-Bold.ttf" if bold else "Lora-Regular.ttf") if serif else (
        "Roboto-Bold.ttf" if bold else "Roboto-Regular.ttf"
    )
    try:
        return ImageFont.truetype(str(MATCH_FONT_DIR / name), size)
    except OSError:
        return font(size, bold=bold, serif=serif)


def draw_soft_box(image, box, fill, opacity=224, radius=4, *, outline=None):
    """Draw a lightly transparent, antialiased chip on an existing RGB image."""
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    scale = 4
    layer = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        (0, 0, width * scale - 1, height * scale - 1),
        radius=radius * scale,
        fill=(*fill, opacity),
        outline=outline,
        width=2 * scale,
    )
    layer = layer.resize((width, height), Image.Resampling.LANCZOS)
    base = image.crop((left, top, right, bottom)).convert("RGBA")
    base.alpha_composite(layer)
    image.paste(base.convert("RGB"), (left, top))


def load_icon_image(path, size):
    """Load, contain, and center a cached icon image."""
    source = Image.open(path).convert("RGBA")
    fitted = ImageOps.contain(source, (size, size), method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2))
    return canvas


def encode_png(image):
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    buffer.seek(0)
    return buffer


def wrap_image_text(draw, text, image_font, max_width, max_lines=2, *, keep_nonbreaking_spaces=False):
    words = text.split(" ") if keep_nonbreaking_spaces else text.split()
    lines, current, truncated = [], "", False
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=image_font) > max_width:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                truncated = True
                break
        else:
            current = candidate
    if current and len(lines) < max_lines:
        lines.append(current)
    if truncated and lines:
        lines[-1] = lines[-1].rstrip(" .") + "..."
    return lines


WIN_COLOR, LOSS_COLOR, DRAW_COLOR = (102, 207, 147), (240, 99, 106), (171, 170, 182)


def result_color(won):
    """Green for a win, red for a loss, grey for a draw or unknown result."""
    return WIN_COLOR if won is True else LOSS_COLOR if won is False else DRAW_COLOR


def draw_gradient_box(image, box, color, start_opacity, end_opacity, radius=8, direction="horizontal",
                      outline=None, fade_at=1.0):
    """Rounded box filled with ``color`` fading from ``start_opacity`` to ``end_opacity``.

    ``direction`` is "horizontal" (left to right) or "vertical" (top to bottom); the fade finishes at
    ``fade_at`` of the way across and holds ``end_opacity`` after that.
    """
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return
    length = width if direction == "horizontal" else height
    stop = max(1, round(length * fade_at))
    ramp = [round(start_opacity + (end_opacity - start_opacity) * min(i / stop, 1)) for i in range(length)]
    strip = Image.new("L", (length, 1))
    strip.putdata(ramp)
    alpha = strip.resize((width, height)) if direction == "horizontal" else strip.transpose(
        Image.Transpose.ROTATE_270).resize((width, height))
    scale = 4
    mask = Image.new("L", (width * scale, height * scale), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width * scale - 1, height * scale - 1),
                                           radius=radius * scale, fill=255)
    mask = mask.resize((width, height), Image.Resampling.LANCZOS)
    # A little noise breaks up the visible steps a slow 8-bit fade makes on a dark background.
    alpha = ImageChops.add(alpha, Image.effect_noise((width, height), 2).point(lambda v: min(max(v, 124), 132)),
                           offset=-128)
    alpha = Image.composite(alpha, Image.new("L", (width, height), 0), mask)
    layer = Image.new("RGBA", (width, height), (*color, 0))
    layer.putalpha(alpha)
    if outline is not None:
        edge = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
        ImageDraw.Draw(edge).rounded_rectangle((0, 0, width * scale - 1, height * scale - 1),
                                               radius=radius * scale, outline=outline, width=2 * scale)
        layer.alpha_composite(edge.resize((width, height), Image.Resampling.LANCZOS))
    base = image.crop(box).convert("RGBA")
    base.alpha_composite(layer)
    image.paste(base.convert(image.mode), (left, top))


def draw_tinted_box(image, box, color, radius=8, fill_opacity=40, edge_opacity=110, direction="horizontal"):
    """Win/loss tint: a gradient that is strongest at the start edge, with a matching outline."""
    draw_gradient_box(image, box, color, round(fill_opacity * 1.8), round(fill_opacity * 0.35), radius=radius,
                      direction=direction, outline=(*color, edge_opacity))


def draw_result_glow(image, box, color, radius=9, opacity=70, fade_at=0.45):
    """Soft result-coloured glow along the left of a row that fades out before the stats."""
    draw_gradient_box(image, box, color, opacity, 0, radius=radius, fade_at=fade_at)


def draw_result_chip(image, box, color, text, chip_font, fill_opacity=40, gradient=True):
    """Tinted chip with centred text in the chip colour, e.g. 'WIN 13-7'. Raise the fill over busy map art.

    ``gradient=False`` gives a flat tint instead of the fading one.
    """
    if gradient:
        draw_tinted_box(image, box, color, radius=7, fill_opacity=fill_opacity)
    else:
        draw_soft_box(image, box, color, opacity=fill_opacity, radius=7, outline=(*color, 110))
    ImageDraw.Draw(image).text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), text, font=chip_font,
                               fill=color, anchor="mm")


def chip_width(text, chip_font, padding=14):
    return int(chip_font.getlength(text)) + padding * 2
