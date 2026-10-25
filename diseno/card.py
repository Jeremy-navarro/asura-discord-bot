"""Rendered event card for ASURA Discord alerts.

Discord messages cannot run HTML or CSS, so the "glitch profile" look
(dark card, neon cyan/purple accents, monospace type, neon glow) is
painted with Pillow and sent as a single PNG image.

The layout mirrors the reference design:
    header gradient -> circular avatar -> name -> subtitle
    -> separator -> stats row
"""

import io
from pathlib import Path

from PIL import (
    Image,
    ImageChops,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageOps,
)


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LOGO = BASE_DIR / "gang.png"


# ============================================================
# PALETTE (taken from the reference design)
# ============================================================

BACKGROUND = (13, 13, 13)
PRIMARY = (0, 242, 234)
SECONDARY = (168, 85, 247)
TEXT = (229, 229, 229)


# ============================================================
# LAYOUT (1x pixels; everything is drawn at SCALE and downscaled)
# ============================================================

CARD_WIDTH = 760
SCALE = 2
RADIUS = 40

PAD = 44
HEADER_H = 140
AVATAR_D = 222
AVATAR_TOP = 30
AVATAR_PAD = 34

NAME_SIZE = 62
NAME_BASELINE = AVATAR_TOP + AVATAR_D + 68

SUB_SIZE = 26
SUB_BASELINE = NAME_BASELINE + 46

RULE_Y = SUB_BASELINE + 28

LABEL_SIZE = 24
LABEL_BASELINE = RULE_Y + 40

VALUE_SIZE = 52
VALUE_BASELINE = LABEL_BASELINE + 62

# Footer note.
FOOTER_SIZE = 14
FOOTER_BASELINE = VALUE_BASELINE + 62

CARD_HEIGHT = FOOTER_BASELINE + 34


# ============================================================
# FONTS
# ============================================================

BOLD_FONTS = (
    "C:/Windows/Fonts/consolab.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
    "/System/Library/Fonts/Menlo.ttc",
)

REGULAR_FONTS = (
    "C:/Windows/Fonts/consola.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/System/Library/Fonts/Menlo.ttc",
)


def _load_font(size, bold=True):
    for candidate in (BOLD_FONTS if bold else REGULAR_FONTS):
        path = Path(candidate)

        if not path.is_file():
            continue

        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue

    # Pillow ships a scalable fallback since 10.1.
    return ImageFont.load_default(size=size)


def _overlay(card):
    """Transparent layer: ImageDraw replaces alpha instead of blending."""

    layer = Image.new("RGBA", card.size, (0, 0, 0, 0))

    return layer, ImageDraw.Draw(layer)


# ============================================================
# TEXT HELPERS
# ============================================================

def _spaced_width(draw, text, font, spacing):
    if not text:
        return 0.0

    return (
        sum(draw.textlength(char, font=font) for char in text)
        + spacing * (len(text) - 1)
    )


def _draw_spaced(
    draw,
    text,
    font,
    fill,
    baseline,
    center_x,
    spacing,
):
    """Draw text with letter spacing (Pillow has no native support)."""

    x = center_x - _spaced_width(draw, text, font, spacing) / 2

    for char in text:
        draw.text(
            (x, baseline),
            char,
            font=font,
            fill=fill,
            anchor="ls",
        )

        x += draw.textlength(char, font=font) + spacing


def _fit_text(draw, text, max_width, size, ratio, bold=True):
    """Shrink the font until the text fits the available width."""

    while size > 14:
        spacing = size * ratio
        font = _load_font(size, bold=bold)

        if _spaced_width(draw, text, font, spacing) <= max_width:
            return font, spacing

        size -= 2

    return _load_font(size, bold=bold), size * ratio


# ============================================================
# AVATAR
# ============================================================

def _load_logo(logo_path, diameter, monochrome, primary):
    size = diameter - AVATAR_PAD * 2

    try:
        logo = Image.open(logo_path).convert("RGBA")
    except (OSError, ValueError):
        return None

    logo.thumbnail((size, size), Image.Resampling.LANCZOS)

    if monochrome:
        # Duotone: keep the artwork's detail, recolor it neon.
        alpha = logo.getchannel("A")

        gray = ImageOps.autocontrast(
            ImageOps.grayscale(logo),
            cutoff=1,
        )

        # The source art is mostly dark, so lift the midtones before
        # mapping it onto the neon palette.
        gray = gray.point(
            lambda value: int(255 * (value / 255) ** 0.45)
        )

        gray = ImageEnhance.Brightness(gray).enhance(2.2)

        logo = ImageOps.colorize(
            gray,
            black=(0, 48, 48),
            white=primary,
        ).convert("RGBA")

        logo.putalpha(alpha)

    else:
        # Original colours, with the shadows lifted so the artwork
        # does not disappear against the dark card.
        alpha = logo.getchannel("A")

        logo = ImageEnhance.Brightness(
            logo.convert("RGB")
        ).enhance(1.75)

        logo = ImageEnhance.Contrast(logo).enhance(1.05)
        logo = logo.convert("RGBA")
        logo.putalpha(alpha)

    mask = Image.new("L", logo.size, 0)

    ImageDraw.Draw(mask).ellipse(
        (0, 0, logo.size[0] - 1, logo.size[1] - 1),
        fill=255,
    )

    logo.putalpha(ImageChops.multiply(logo.getchannel("A"), mask))

    return logo


def _draw_avatar(card, primary, logo_path, monochrome):
    scale = SCALE
    diameter = AVATAR_D * scale

    cx = card.width // 2
    top = AVATAR_TOP * scale
    box = (
        cx - diameter // 2,
        top,
        cx + diameter // 2,
        top + diameter,
    )

    # Neon backlight.
    glow = Image.new("RGBA", card.size, (0, 0, 0, 0))

    ImageDraw.Draw(glow).ellipse(
        (
            box[0] - 10 * scale,
            box[1] - 10 * scale,
            box[2] + 10 * scale,
            box[3] + 10 * scale,
        ),
        fill=primary + (58,),
    )

    card.alpha_composite(
        glow.filter(ImageFilter.GaussianBlur(14 * scale))
    )

    # Dark disc so the logo hides the header line behind it.
    ImageDraw.Draw(card).ellipse(box, fill=BACKGROUND + (255,))

    # Soft inner light so the artwork reads against the black.
    inner = Image.new("RGBA", card.size, (0, 0, 0, 0))

    ImageDraw.Draw(inner).ellipse(
        (
            box[0] + 12 * scale,
            box[1] + 12 * scale,
            box[2] - 12 * scale,
            box[3] - 12 * scale,
        ),
        fill=primary + (26,),
    )

    card.alpha_composite(
        inner.filter(ImageFilter.GaussianBlur(22 * scale))
    )

    ring, ring_draw = _overlay(card)

    ring_draw.ellipse(
        box,
        outline=primary + (77,),
        width=max(2, int(2.5 * scale)),
    )

    card.alpha_composite(ring)

    logo = _load_logo(
        logo_path,
        diameter,
        monochrome,
        primary,
    )

    if logo is None:
        return

    card.alpha_composite(
        logo,
        (
            cx - logo.width // 2,
            top + (diameter - logo.height) // 2,
        ),
    )


# ============================================================
# CARD
# ============================================================

def _draw_header(card, primary, secondary):
    scale = SCALE
    width = card.width
    height = HEADER_H * scale

    # 45 degree gradient: cyan tint on the bottom-left, fading out.
    gradient = Image.new("RGBA", (2, 2))

    gradient.putpixel((0, 0), primary + (26,))
    gradient.putpixel((1, 1), primary + (26,))
    gradient.putpixel((0, 1), primary + (46,))
    gradient.putpixel((1, 0), BACKGROUND + (0,))

    gradient = gradient.resize(
        (width, height),
        Image.Resampling.BICUBIC,
    )

    card.alpha_composite(gradient, (0, 0))

    # Purple radial bloom near the top center.
    bloom = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    ImageDraw.Draw(bloom).ellipse(
        (
            -width * 0.15,
            -height * 1.2,
            width * 1.15,
            height * 1.1,
        ),
        fill=secondary + (16,),
    )

    card.alpha_composite(
        bloom.filter(ImageFilter.GaussianBlur(60 * scale))
    )

    # Header bottom divider.
    layer, draw = _overlay(card)

    draw.rectangle(
        (0, height - max(1, int(2.5 * scale)), width, height),
        fill=primary + (26,),
    )

    card.alpha_composite(layer)


def _draw_text_block(card, title, subtitle, stats, primary, secondary):
    scale = SCALE
    center = card.width / 2
    layer, draw = _overlay(card)

    # Glitch/chromatic split behind the title.
    title_font, title_spacing = _fit_text(
        draw,
        title,
        card.width - PAD * 2 * scale,
        NAME_SIZE * scale,
        0.1,
    )

    _draw_spaced(
        draw,
        title,
        title_font,
        secondary + (70,),
        NAME_BASELINE * scale,
        center - 2 * scale,
        title_spacing,
    )

    _draw_spaced(
        draw,
        title,
        title_font,
        primary + (60,),
        NAME_BASELINE * scale,
        center + 2 * scale,
        title_spacing,
    )

    _draw_spaced(
        draw,
        title,
        title_font,
        TEXT + (255,),
        NAME_BASELINE * scale,
        center,
        title_spacing,
    )

    sub_font, sub_spacing = _fit_text(
        draw,
        subtitle,
        card.width - PAD * 2 * scale,
        SUB_SIZE * scale,
        0.14,
    )

    _draw_spaced(
        draw,
        subtitle,
        sub_font,
        primary + (204,),
        SUB_BASELINE * scale,
        center,
        sub_spacing,
    )

    # Separator above the stats.
    draw.rectangle(
        (
            PAD * scale,
            RULE_Y * scale,
            card.width - PAD * scale,
            RULE_Y * scale + max(1, int(2.5 * scale)),
        ),
        fill=primary + (51,),
    )

    # Stats row.
    columns = max(1, len(stats))
    usable = card.width - PAD * 2 * scale
    column_width = usable / columns
    max_value_width = column_width - 16 * scale

    for index, (label, value) in enumerate(stats):
        column_center = PAD * scale + column_width * (index + 0.5)

        label_font, label_spacing = _fit_text(
            draw,
            label,
            column_width - 12 * scale,
            LABEL_SIZE * scale,
            0.1,
        )

        _draw_spaced(
            draw,
            label,
            label_font,
            TEXT + (153,),
            LABEL_BASELINE * scale,
            column_center,
            label_spacing,
        )

        value_font, value_spacing = _fit_text(
            draw,
            value,
            max_value_width,
            VALUE_SIZE * scale,
            0.02,
        )

        _draw_spaced(
            draw,
            value,
            value_font,
            primary + (255,),
            VALUE_BASELINE * scale,
            column_center,
            value_spacing,
        )

    card.alpha_composite(layer)


def _draw_footer(card, text):
    if not text:
        return

    scale = SCALE
    layer, draw = _overlay(card)

    font, spacing = _fit_text(
        draw,
        text,
        card.width - PAD * 2 * scale,
        FOOTER_SIZE * scale,
        0.12,
    )

    _draw_spaced(
        draw,
        text,
        font,
        TEXT + (110,),
        FOOTER_BASELINE * scale,
        card.width / 2,
        spacing,
    )

    card.alpha_composite(layer)


def render_event_card(
    title,
    subtitle,
    stats,
    primary=PRIMARY,
    secondary=SECONDARY,
    logo_path=DEFAULT_LOGO,
    monochrome_logo=False,
    footer=None,
):
    """Return a PNG of the event card as an in-memory buffer."""

    scale = SCALE
    width = CARD_WIDTH * scale
    height = CARD_HEIGHT * scale

    card = Image.new("RGBA", (width, height), BACKGROUND + (255,))

    _draw_header(card, primary, secondary)
    _draw_text_block(
        card,
        title.upper(),
        subtitle.upper(),
        [(label.upper(), value.upper()) for label, value in stats],
        primary,
        secondary,
    )
    _draw_avatar(card, primary, logo_path, monochrome_logo)
    _draw_footer(card, (footer or "").upper())

    # Clip everything to the rounded card shape.
    mask = Image.new("L", (width, height), 0)

    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=RADIUS * scale,
        fill=255,
    )

    card.putalpha(
        ImageChops.multiply(card.getchannel("A"), mask)
    )

    # Neon border, clipped to the same shape.
    border = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    ImageDraw.Draw(border).rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=RADIUS * scale,
        outline=primary + (51,),
        width=max(2, int(2.5 * scale)),
    )

    border.putalpha(
        ImageChops.multiply(border.getchannel("A"), mask)
    )

    card.alpha_composite(border)

    # Outer glow around the whole card.
    margin = 30 * scale
    canvas = Image.new(
        "RGBA",
        (width + margin * 2, height + margin * 2),
        (0, 0, 0, 0),
    )

    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))

    ImageDraw.Draw(shadow).rounded_rectangle(
        (
            margin,
            margin,
            margin + width - 1,
            margin + height - 1,
        ),
        radius=RADIUS * scale,
        fill=primary + (24,),
    )

    canvas.alpha_composite(
        shadow.filter(ImageFilter.GaussianBlur(11 * scale))
    )

    canvas.alpha_composite(card, (margin, margin))

    canvas = canvas.resize(
        (canvas.width // scale, canvas.height // scale),
        Image.Resampling.LANCZOS,
    )

    buffer = io.BytesIO()

    canvas.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)

    return buffer
