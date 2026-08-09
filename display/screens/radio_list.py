from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from PIL import Image

import display.copy as copy
import display.renderer as renderer
import display.screens.list_layout as layout
from config import Station
from display.events import BackRequested, Event, ListScrolled, StationSelected

_ROW_FONT_SIZE: Final[int] = 13
_ROW_TEXT_Y_OFFSET: Final[int] = 9


class RadioListScreen:
    """Live stations. No action zone — the whole row tunes in."""

    def __init__(self, stations: Sequence[Station], scroll_offset: int = 0) -> None:
        self._stations = stations
        self._scroller = layout.ListScroller(len(stations))
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
            copy.HEADER_RADIO,
            header_font,
            show_back_icon=True,
            icon_font=renderer.load_icon_font(layout.HEADER_FONT_SIZE + 4),
        )

        if not self._stations:
            layout.draw_status_message(draw, copy.NO_STATIONS, renderer.ICON_RADIO)
            return image

        visible = self._stations[self._scroller.visible_slice()]
        for index, station in enumerate(visible):
            y = layout.row_top(index)
            # Stop at the sidebar so row dividers don't cut through the chevrons
            renderer.draw_divider(draw, y, x_end=layout.SIDEBAR_X)
            renderer.draw_text_clipped(
                draw,
                station.name,
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

        station_index = self._scroller.offset + visible_row
        if station_index >= len(self._stations):
            return None
        return StationSelected(self._stations[station_index])
