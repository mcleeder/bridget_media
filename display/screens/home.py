from __future__ import annotations

from typing import Final

from PIL import Image

import display.copy as copy
import display.renderer as renderer
import display.screens.list_layout as layout
from display.events import Event, HomeMenuItem, HomeMenuSelected, ListScrolled

_ROW_FONT_SIZE: Final[int] = 13
_ROW_TEXT_Y_OFFSET: Final[int] = 9
_ROW_ICON_SIZE: Final[int] = 18
_ICON_ZONE_WIDTH: Final[int] = 40
_CHEVRON_ZONE_WIDTH: Final[int] = 30

# Ordered so the three listening destinations occupy the visible rows and the
# setup screens — the ones you touch when setting the device up, not when
# using it — are what falls below the fold. Wi-Fi leads that pair: when both
# are wrong, the network is the one to fix first.
_MENU_ROWS: Final[list[tuple[str, str, HomeMenuItem]]] = [
    (copy.HOME_ITEM_PODCASTS, renderer.ICON_PODCASTS, HomeMenuItem.PODCASTS),
    (copy.HOME_ITEM_RADIO, renderer.ICON_RADIO, HomeMenuItem.RADIO),
    (copy.HOME_ITEM_QUEUE, renderer.ICON_QUEUE_MUSIC, HomeMenuItem.QUEUE),
    (copy.HOME_ITEM_WIFI, renderer.ICON_WIFI, HomeMenuItem.WIFI),
    (copy.HOME_ITEM_BLUETOOTH, renderer.ICON_BLUETOOTH, HomeMenuItem.BLUETOOTH),
]


class HomeScreen:
    """Root menu: scrollable rows, no back button.

    Unlike the other list screens this one is never rebuilt, so its scroller
    is long-lived and the menu stays where the user left it.
    """

    def __init__(self) -> None:
        self._scroller = layout.ListScroller(len(_MENU_ROWS))

    def render(self) -> Image.Image:
        image, draw = renderer.new_canvas()
        header_font = renderer.load_text_font(layout.HEADER_FONT_SIZE)
        row_font = renderer.load_text_font(_ROW_FONT_SIZE)
        icon_font = renderer.load_icon_font(_ROW_ICON_SIZE)

        layout.draw_header(
            draw,
            copy.HEADER_HOME,
            header_font,
            show_back_icon=False,
            icon_font=renderer.load_icon_font(layout.HEADER_FONT_SIZE),
        )

        for index, (label, icon, _) in enumerate(_MENU_ROWS[self._scroller.visible_slice()]):
            y = layout.row_top(index)
            # Stop at the sidebar so row dividers don't cut through the chevrons
            renderer.draw_divider(draw, y, x_end=layout.SIDEBAR_X)
            renderer.draw_icon_centered(
                draw, icon, (0, y, _ICON_ZONE_WIDTH, y + layout.ROW_HEIGHT), icon_font
            )
            draw.text(
                (_ICON_ZONE_WIDTH + 6, y + _ROW_TEXT_Y_OFFSET),
                label,
                font=row_font,
                fill=renderer.BLACK,
            )
            renderer.draw_icon_centered(
                draw,
                renderer.ICON_CHEVRON_RIGHT,
                (
                    layout.SIDEBAR_X - _CHEVRON_ZONE_WIDTH,
                    y,
                    layout.SIDEBAR_X,
                    y + layout.ROW_HEIGHT,
                ),
                icon_font,
            )

        layout.draw_sidebar(draw, self._scroller)
        return image

    def handle_touch(self, x: int, y: int) -> Event | None:
        if layout.is_sidebar_touch(x, y):
            return ListScrolled() if self._scroller.handle_sidebar_touch(y) else None

        visible_row = layout.row_index_at(y)
        if visible_row is None:
            return None

        row = self._scroller.offset + visible_row
        if row >= len(_MENU_ROWS):
            return None
        return HomeMenuSelected(_MENU_ROWS[row][2])
