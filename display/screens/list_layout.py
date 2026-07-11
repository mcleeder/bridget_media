from __future__ import annotations

from typing import Final

from PIL import ImageDraw, ImageFont

import display.renderer as renderer
from config import DISPLAY_HEIGHT, DISPLAY_WIDTH

HEADER_HEIGHT: Final[int] = 23
ROW_HEIGHT: Final[int] = 35
VISIBLE_ROWS: Final[int] = 3
SIDEBAR_X: Final[int] = DISPLAY_WIDTH - 36

_SIDEBAR_MIDDLE_Y: Final[int] = (HEADER_HEIGHT + DISPLAY_HEIGHT) // 2

HEADER_FONT_SIZE: Final[int] = 12
_SIDEBAR_ICON_SIZE: Final[int] = 20


class ListScroller:
    """Scroll-window state and sidebar hit-testing shared by the list screens."""

    def __init__(self, item_count: int) -> None:
        self._item_count = item_count
        self._offset = 0

    @property
    def offset(self) -> int:
        return self._offset

    @property
    def can_scroll_up(self) -> bool:
        return self._offset > 0

    @property
    def can_scroll_down(self) -> bool:
        return self._offset + VISIBLE_ROWS < self._item_count

    def visible_slice(self) -> slice:
        return slice(self._offset, self._offset + VISIBLE_ROWS)

    def handle_sidebar_touch(self, y: int) -> bool:
        """Scroll one row for a sidebar touch. Returns True if the view changed."""
        direction = -1 if y < _SIDEBAR_MIDDLE_Y else 1
        max_offset = max(0, self._item_count - VISIBLE_ROWS)
        new_offset = max(0, min(self._offset + direction, max_offset))
        changed = new_offset != self._offset
        self._offset = new_offset
        return changed


def is_sidebar_touch(x: int, y: int) -> bool:
    return x >= SIDEBAR_X and y >= HEADER_HEIGHT


def row_index_at(y: int) -> int | None:
    """Visible row index for a touch, or None for the header area."""
    if y < HEADER_HEIGHT:
        return None
    return (y - HEADER_HEIGHT) // ROW_HEIGHT


def row_top(visible_index: int) -> int:
    return HEADER_HEIGHT + visible_index * ROW_HEIGHT


def draw_header(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    show_back_icon: bool,
    icon_font: ImageFont.FreeTypeFont,
) -> None:
    draw.rectangle((0, 0, DISPLAY_WIDTH, HEADER_HEIGHT), fill=renderer.BLACK)
    text_x = 6
    if show_back_icon:
        renderer.draw_icon_centered(
            draw,
            renderer.ICON_ARROW_BACK,
            (0, 0, 26, HEADER_HEIGHT),
            icon_font,
            fill=renderer.WHITE,
        )
        text_x = 30
    renderer.draw_text_clipped(
        draw, text, (text_x, 5), font, max_width=DISPLAY_WIDTH - text_x - 6, fill=renderer.WHITE
    )


def draw_sidebar(draw: ImageDraw.ImageDraw, scroller: ListScroller) -> None:
    icon_font = renderer.load_icon_font(_SIDEBAR_ICON_SIZE)
    draw.line([(SIDEBAR_X, HEADER_HEIGHT), (SIDEBAR_X, DISPLAY_HEIGHT)], fill=renderer.BLACK)
    if scroller.can_scroll_up:
        renderer.draw_icon_centered(
            draw,
            renderer.ICON_ARROW_UP,
            (SIDEBAR_X, HEADER_HEIGHT, DISPLAY_WIDTH, _SIDEBAR_MIDDLE_Y),
            icon_font,
        )
    if scroller.can_scroll_down:
        renderer.draw_icon_centered(
            draw,
            renderer.ICON_ARROW_DOWN,
            (SIDEBAR_X, _SIDEBAR_MIDDLE_Y, DISPLAY_WIDTH, DISPLAY_HEIGHT),
            icon_font,
        )
