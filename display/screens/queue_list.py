from __future__ import annotations

from typing import Final

from PIL import Image

import display.renderer as renderer
import display.screens.list_layout as layout
from db.models import QueueEntry
from display.events import (
    BackRequested,
    EpisodeSelected,
    Event,
    ListScrolled,
    QueueRemoveRequested,
)

_TITLE_FONT_SIZE: Final[int] = 12
_META_FONT_SIZE: Final[int] = 9
_TITLE_Y_OFFSET: Final[int] = 4
_META_Y_OFFSET: Final[int] = 21
_ACTION_ICON_SIZE: Final[int] = 18


class QueueListScreen:
    def __init__(self, entries: list[QueueEntry], scroll_offset: int = 0) -> None:
        self._entries = entries
        self._scroller = layout.ListScroller(len(entries))
        self._scroller.scroll_to(scroll_offset)

    @property
    def scroll_offset(self) -> int:
        """Current scroll position, so a rebuilt screen can restore it."""
        return self._scroller.offset

    def render(self) -> Image.Image:
        image, draw = renderer.new_canvas()
        header_font = renderer.load_text_font(layout.HEADER_FONT_SIZE)
        title_font = renderer.load_text_font(_TITLE_FONT_SIZE)
        meta_font = renderer.load_text_font(_META_FONT_SIZE)
        action_font = renderer.load_icon_font(_ACTION_ICON_SIZE)

        layout.draw_header(
            draw,
            "Next",
            header_font,
            show_back_icon=True,
            icon_font=renderer.load_icon_font(layout.HEADER_FONT_SIZE + 4),
        )

        if not self._entries:
            draw.text(
                (6, layout.row_top(0) + _TITLE_Y_OFFSET),
                "Queue is empty",
                font=title_font,
                fill=renderer.BLACK,
            )
            return image

        visible = self._entries[self._scroller.visible_slice()]
        for index, entry in enumerate(visible):
            y = layout.row_top(index)
            # Stop at the sidebar so row dividers don't cut through the chevrons
            renderer.draw_divider(draw, y, x_end=layout.SIDEBAR_X)

            renderer.draw_text_clipped(
                draw,
                entry.episode.title,
                (6, y + _TITLE_Y_OFFSET),
                title_font,
                max_width=layout.ACTION_X - 12,
            )
            draw.text(
                (6, y + _META_Y_OFFSET), entry.feed_name, font=meta_font, fill=renderer.BLACK
            )

            renderer.draw_icon_centered(
                draw,
                renderer.ICON_REMOVE_CIRCLE_OUTLINE,
                (layout.ACTION_X, y, layout.SIDEBAR_X, y + layout.ROW_HEIGHT),
                action_font,
            )

        layout.draw_sidebar(draw, self._scroller)
        return image

    def handle_touch(self, x: int, y: int) -> Event | None:
        if y < layout.HEADER_HEIGHT:
            return BackRequested()

        if layout.is_sidebar_touch(x, y):
            return ListScrolled() if self._scroller.handle_sidebar_touch(y) else None

        visible_row = layout.row_index_at(y)
        if visible_row is None:
            return None

        entry_index = self._scroller.offset + visible_row
        if entry_index >= len(self._entries):
            return None

        entry = self._entries[entry_index]
        if layout.is_action_zone_touch(x, y):
            return QueueRemoveRequested(entry.episode)
        return EpisodeSelected(entry.episode)
