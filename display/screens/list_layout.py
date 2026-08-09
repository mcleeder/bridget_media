from __future__ import annotations

from typing import Final

from PIL import ImageDraw, ImageFont

import display.renderer as renderer
from config import DISPLAY_HEIGHT, DISPLAY_WIDTH

HEADER_HEIGHT: Final[int] = 23
ROW_HEIGHT: Final[int] = 35
VISIBLE_ROWS: Final[int] = 3
SIDEBAR_X: Final[int] = DISPLAY_WIDTH - 36
# Per-row action button column (queue toggle / remove), just left of the sidebar
ACTION_X: Final[int] = SIDEBAR_X - 36

_SIDEBAR_MIDDLE_Y: Final[int] = (HEADER_HEIGHT + DISPLAY_HEIGHT) // 2

HEADER_FONT_SIZE: Final[int] = 12
_SIDEBAR_ICON_SIZE: Final[int] = 20
_HEADER_ACTION_ICON_SIZE: Final[int] = 15
# Wider than the sidebar below it: the action button carries a two-glyph
# label ("+" plus an icon), which 36px can't hold legibly.
HEADER_ACTION_X: Final[int] = DISPLAY_WIDTH - 48

# Centred icon-over-text block used for every transient / error / empty state
_STATUS_ICON_SIZE: Final[int] = 16
_STATUS_FONT_SIZE: Final[int] = 10
_STATUS_ICON_GAP: Final[int] = 6
_STATUS_LINE_HEIGHT: Final[int] = 14
_STATUS_MAX_LINES: Final[int] = 3
_STATUS_SIDE_MARGIN: Final[int] = 10

_BODY_HEIGHT: Final[int] = DISPLAY_HEIGHT - HEADER_HEIGHT

# The header bar is filled inclusive of row HEADER_HEIGHT, so it is one row
# taller than the constant. Icon rects need that extra row or they centre
# against a 23px box inside a 24px bar and sit a pixel above the title.
_HEADER_BAR_BOTTOM: Final[int] = HEADER_HEIGHT + 1


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

    def scroll_to(self, offset: int) -> None:
        """Jump to an offset, clamped to the valid range."""
        max_offset = max(0, self._item_count - VISIBLE_ROWS)
        self._offset = max(0, min(offset, max_offset))

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


def is_header_action_touch(x: int, y: int) -> bool:
    """True for the right-hand button in the header (screen-level action)."""
    return x >= HEADER_ACTION_X and y < HEADER_HEIGHT


def is_action_zone_touch(x: int, y: int) -> bool:
    return ACTION_X <= x < SIDEBAR_X and y >= HEADER_HEIGHT


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
    action_icon: str | None = None,
) -> None:
    draw.rectangle((0, 0, DISPLAY_WIDTH, HEADER_HEIGHT), fill=renderer.BLACK)
    text_x = 6
    if show_back_icon:
        renderer.draw_icon_centered(
            draw,
            renderer.ICON_ARROW_BACK,
            (0, 0, 26, _HEADER_BAR_BOTTOM),
            icon_font,
            fill=renderer.WHITE,
        )
        text_x = 30

    text_end = DISPLAY_WIDTH - 6
    if action_icon is not None:
        renderer.draw_icon_centered(
            draw,
            action_icon,
            (HEADER_ACTION_X, 0, DISPLAY_WIDTH, _HEADER_BAR_BOTTOM),
            renderer.load_icon_font(_HEADER_ACTION_ICON_SIZE),
            fill=renderer.WHITE,
        )
        text_end = HEADER_ACTION_X - 4

    renderer.draw_text_clipped(
        draw, text, (text_x, 5), font, max_width=text_end - text_x, fill=renderer.WHITE
    )


def draw_status_message(draw: ImageDraw.ImageDraw, text: str, icon: str) -> None:
    """Centred icon above word-wrapped text — every transient/error/empty state.

    The whole block is vertically centred in the body area so it reads the same
    whether the copy runs to one line or three.
    """
    message_font = renderer.load_text_font(_STATUS_FONT_SIZE)
    max_width = DISPLAY_WIDTH - 2 * _STATUS_SIDE_MARGIN
    line_count = len(
        renderer.wrap_lines(draw, text, message_font, max_width, _STATUS_MAX_LINES)
    )

    block_height = _STATUS_ICON_SIZE + _STATUS_ICON_GAP + line_count * _STATUS_LINE_HEIGHT
    icon_top = HEADER_HEIGHT + max(0, (_BODY_HEIGHT - block_height) // 2)

    renderer.draw_icon_centered(
        draw,
        icon,
        (0, icon_top, DISPLAY_WIDTH, icon_top + _STATUS_ICON_SIZE),
        renderer.load_icon_font(_STATUS_ICON_SIZE),
    )
    renderer.draw_text_wrapped_centered(
        draw,
        text,
        icon_top + _STATUS_ICON_SIZE + _STATUS_ICON_GAP,
        message_font,
        max_width=max_width,
        max_lines=_STATUS_MAX_LINES,
        line_height=_STATUS_LINE_HEIGHT,
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
