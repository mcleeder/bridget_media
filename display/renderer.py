from __future__ import annotations

import functools
from typing import Final

from PIL import Image, ImageChops, ImageDraw, ImageFont

from config import DISPLAY_HEIGHT, DISPLAY_WIDTH

# E-ink is 1-bit: 0 = black, 1 = white (PIL mode "1")
BLACK: Final[int] = 0
WHITE: Final[int] = 1

TEXT_FONT_PATH: Final[str] = "assets/fonts/DejaVuSans.ttf"
ICON_FONT_PATH: Final[str] = "assets/fonts/MaterialIcons-Regular.ttf"

# Material Icons glyphs — codepoints from assets/fonts/MaterialIcons-Regular.codepoints
ICON_ARROW_BACK: Final[str] = "\ue5c4"
ICON_REPLAY_30: Final[str] = "\ue05a"
ICON_PLAY: Final[str] = "\ue037"
ICON_PAUSE: Final[str] = "\ue034"
ICON_ARROW_UP: Final[str] = "\ue316"
ICON_ARROW_DOWN: Final[str] = "\ue313"
ICON_FORWARD_30: Final[str] = "\ue057"
ICON_ERROR_OUTLINE: Final[str] = "\ue001"
ICON_BLUETOOTH: Final[str] = "\ue1a7"
ICON_BLUETOOTH_CONNECTED: Final[str] = "\ue1a8"
ICON_PODCASTS: Final[str] = "\uf048"
ICON_QUEUE_MUSIC: Final[str] = "\ue03d"
ICON_CHEVRON_RIGHT: Final[str] = "\ue5cc"
ICON_PLAYLIST_ADD: Final[str] = "\ue03b"
ICON_PLAYLIST_ADD_CHECK: Final[str] = "\ue065"
ICON_REMOVE_CIRCLE_OUTLINE: Final[str] = "\ue15d"
ICON_BLUETOOTH_SEARCHING: Final[str] = "\ue1aa"
ICON_LINK_OFF: Final[str] = "\ue16f"
ICON_ADD: Final[str] = "\ue145"
ICON_RADIO: Final[str] = "\ue03e"
ICON_GRAPHIC_EQ: Final[str] = "\ue1b8"

# A glyph pair renders as one text run, which draw_icon_centered centres as a
# whole \u2014 "+" ahead of the search icon, so the button reads as "add a device".
ICON_ADD_BLUETOOTH: Final[str] = ICON_ADD + ICON_BLUETOOTH_SEARCHING


@functools.cache
def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def load_text_font(size: int) -> ImageFont.FreeTypeFont:
    return _load_font(TEXT_FONT_PATH, size)


def load_icon_font(size: int) -> ImageFont.FreeTypeFont:
    return _load_font(ICON_FONT_PATH, size)


def new_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    """Return a blank white canvas at display resolution."""
    image = Image.new("1", (DISPLAY_WIDTH, DISPLAY_HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    return image, draw


def draw_text_clipped(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    font: ImageFont.FreeTypeFont,
    max_width: int,
    fill: int = BLACK,
) -> None:
    """Draw text, truncating with ellipsis if it exceeds max_width."""
    if draw.textlength(text, font=font) <= max_width:
        draw.text(xy, text, font=font, fill=fill)
        return

    ellipsis = "…"
    while text and draw.textlength(text + ellipsis, font=font) > max_width:
        text = text[:-1]
    draw.text(xy, text + ellipsis, font=font, fill=fill)


def wrap_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    """Word-wrap text into at most max_lines; overflow lands on the last line.

    The last line is left long on purpose — callers draw it with
    draw_text_clipped, which is what applies the ellipsis.
    """
    words = text.split()
    lines: list[str] = []
    line = ""

    for index, word in enumerate(words):
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            line = candidate
            continue
        if len(lines) == max_lines - 1:
            return [*lines, " ".join([line, *words[index:]]).strip()]
        lines.append(line)
        line = word

    if line:
        lines.append(line)
    return lines


def draw_text_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int,
    line_height: int,
    fill: int = BLACK,
) -> None:
    """Draw word-wrapped text up to max_lines; the last line is ellipsis-clipped."""
    x, y = xy
    for index, line in enumerate(wrap_lines(draw, text, font, max_width, max_lines)):
        draw_text_clipped(draw, line, (x, y + index * line_height), font, max_width, fill)


def draw_text_wrapped_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    top_y: int,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int,
    line_height: int,
    fill: int = BLACK,
) -> int:
    """Draw word-wrapped text with each line horizontally centred. Returns the y below it."""
    lines = wrap_lines(draw, text, font, max_width, max_lines)
    for index, line in enumerate(lines):
        width = min(int(draw.textlength(line, font=font)), max_width)
        x = max(0, (DISPLAY_WIDTH - width) // 2)
        draw_text_clipped(draw, line, (x, top_y + index * line_height), font, max_width, fill)
    return top_y + len(lines) * line_height


@functools.cache
def _icon_ink_box(icon: str, size: int) -> tuple[int, int, int, int]:
    """Bounds of a glyph's *rendered* ink, relative to its draw origin.

    Not the same as `textbbox`, which reports the antialiased extent. The
    e-ink canvas is 1-bit, so those soft edges threshold away and the ink
    lands smaller — and higher — than textbbox predicts. Centring on
    textbbox therefore drew every icon 1-4px above its rect. Measured by
    rendering the glyph exactly as the real canvas does.
    """
    pad = size * 2
    probe = Image.new("1", (pad * 2, pad * 2), WHITE)
    ImageDraw.Draw(probe).text((pad, pad), icon, font=_load_font(ICON_FONT_PATH, size), fill=BLACK)
    box = ImageChops.invert(probe.convert("L")).getbbox()
    if box is None:  # whitespace-only glyph
        return (0, 0, 0, 0)
    left, top, right, bottom = box
    return (left - pad, top - pad, right - pad, bottom - pad)


def draw_icon_centered(
    draw: ImageDraw.ImageDraw,
    icon: str,
    rect: tuple[int, int, int, int],
    font: ImageFont.FreeTypeFont,
    fill: int = BLACK,
) -> None:
    """Draw one or more icon glyphs centred within rect."""
    x0, y0, x1, y1 = rect
    left, top, right, bottom = _icon_ink_box(icon, font.size)
    icon_w = right - left
    icon_h = bottom - top
    x = x0 + (x1 - x0 - icon_w) // 2 - left
    y = y0 + (y1 - y0 - icon_h) // 2 - top
    draw.text((x, y), icon, font=font, fill=fill)


def draw_progress_bar(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    fraction: float,
) -> None:
    """Draw a horizontal progress bar. fraction is clamped to [0, 1]."""
    x0, y0, x1, y1 = rect
    fraction = max(0.0, min(1.0, fraction))
    draw.rectangle((x0, y0, x1, y1), outline=BLACK, fill=WHITE)
    fill_x = x0 + int((x1 - x0) * fraction)
    if fill_x > x0:
        draw.rectangle((x0, y0, fill_x, y1), fill=BLACK)


def draw_divider(draw: ImageDraw.ImageDraw, y: int, x_end: int = DISPLAY_WIDTH) -> None:
    draw.line([(0, y), (x_end, y)], fill=BLACK, width=1)
