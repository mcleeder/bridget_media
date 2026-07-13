from __future__ import annotations

from typing import Final

from PIL import Image

import display.renderer as renderer
import display.screens.list_layout as layout
from db.models import Feed
from display.events import BackRequested, Event, FeedSelected, ListScrolled

_ROW_FONT_SIZE: Final[int] = 13
_ROW_TEXT_Y_OFFSET: Final[int] = 9


class PodcastListScreen:
    def __init__(self, feeds: list[Feed], scroll_offset: int = 0) -> None:
        self._feeds = feeds
        self._scroller = layout.ListScroller(len(feeds))
        self._scroller.scroll_to(scroll_offset)

    @property
    def scroll_offset(self) -> int:
        """Current scroll position, so a rebuilt screen can restore it."""
        return self._scroller.offset

    def render(self) -> Image.Image:
        image, draw = renderer.new_canvas()
        header_font = renderer.load_text_font(layout.HEADER_FONT_SIZE)
        row_font = renderer.load_text_font(_ROW_FONT_SIZE)

        layout.draw_header(
            draw,
            "Podcasts",
            header_font,
            show_back_icon=True,
            icon_font=renderer.load_icon_font(layout.HEADER_FONT_SIZE + 4),
        )

        if not self._feeds:
            draw.text(
                (6, layout.row_top(0) + _ROW_TEXT_Y_OFFSET),
                "No podcasts — add feeds in config.py",
                font=row_font,
                fill=renderer.BLACK,
            )
            return image

        visible = self._feeds[self._scroller.visible_slice()]
        for index, feed in enumerate(visible):
            y = layout.row_top(index)
            # Stop at the sidebar so row dividers don't cut through the chevrons
            renderer.draw_divider(draw, y, x_end=layout.SIDEBAR_X)
            renderer.draw_text_clipped(
                draw,
                feed.name,
                (6, y + _ROW_TEXT_Y_OFFSET),
                row_font,
                max_width=layout.SIDEBAR_X - 12,
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

        feed_index = self._scroller.offset + visible_row
        if feed_index >= len(self._feeds):
            return None
        return FeedSelected(self._feeds[feed_index])
