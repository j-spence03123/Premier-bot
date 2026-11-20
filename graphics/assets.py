"""Shared font, color, and drawing helpers for Pillow renderers."""

from pathlib import Path
import io

from PIL import Image, ImageDraw, ImageFont, ImageOps


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
    "MVP": ((120, 90, 20), (255, 210, 80)),             # gold
    "ACE": ((255, 196, 60), (40, 26, 0), 235),          # solid gold
    "QUAD": ((110, 104, 20), (245, 240, 110)),          # lemon
    "ECO FRAUD": ((70, 105, 15), (196, 245, 90)),       # lime
    "SURVIVOR": ((25, 105, 50), (120, 235, 145)),       # green
    "ASSIST KING": ((15, 100, 90), (110, 240, 215)),    # teal
    "OPERATOR": ((15, 85, 115), (110, 220, 255)),       # cyan
    "ENTRY": ((30, 60, 140), (140, 175, 255)),          # blue
    "PLANTER": ((65, 45, 150), (185, 165, 255)),        # indigo
    "DINK MACHINE": ((105, 40, 140), (225, 160, 255)),  # violet
    "CLUTCH": ((140, 30, 120), (255, 130, 230)),        # magenta
    "BAITED": ((135, 35, 75), (255, 140, 180)),         # rose
    "DAMAGE DEALER": ((145, 60, 15), (255, 160, 90)),   # orange
    "LVP": ((130, 25, 25), (255, 110, 110)),            # red
    "TEAM KILLER": ((200, 30, 30), (255, 255, 255), 235),  # solid red
    "BODY SHOOTER": ((110, 60, 25), (225, 150, 85)),    # copper
    "PASSENGER": ((100, 92, 70), (235, 220, 180)),      # sand
    "VICTIM": ((70, 72, 80), (205, 208, 218)),          # grey
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


def draw_tinted_box(image, box, color, radius=8, fill_opacity=40, edge_opacity=110):
    """Low-opacity fill with a matching outline: the win/loss tint used for chips and panels."""
    draw_soft_box(image, box, color, opacity=fill_opacity, radius=radius, outline=(*color, edge_opacity))


def draw_result_chip(image, box, color, text, chip_font, fill_opacity=40):
    """Tinted chip with centred text in the chip colour, e.g. 'WIN 13-7'. Raise the fill over busy map art."""
    draw_tinted_box(image, box, color, radius=7, fill_opacity=fill_opacity)
    ImageDraw.Draw(image).text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), text, font=chip_font,
                               fill=color, anchor="mm")


def chip_width(text, chip_font, padding=14):
    return int(chip_font.getlength(text)) + padding * 2
