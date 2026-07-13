from __future__ import annotations

from typing import Final

from PIL import Image

import display.renderer as renderer
import display.screens.list_layout as layout
from config import DISPLAY_WIDTH
from display.events import Event, HomeMenuItem, HomeMenuSelected

_ROW_FONT_SIZE: Final[int] = 13
_ROW_TEXT_Y_OFFSET: Final[int] = 9
_ROW_ICON_SIZE: Final[int] = 18
_ICON_ZONE_WIDTH: Final[int] = 40
_CHEVRON_ZONE_WIDTH: Final[int] = 30

_MENU_ROWS: Final[list[tuple[str, str, HomeMenuItem]]] = [
    ("Bluetooth", renderer.ICON_BLUETOOTH, HomeMenuItem.BLUETOOTH),
    ("Podcasts", renderer.ICON_PODCASTS, HomeMenuItem.PODCASTS),
    ("Next", renderer.ICON_QUEUE_MUSIC, HomeMenuItem.QUEUE),
]


class HomeScreen:
    """Root menu: three fixed rows, no scrolling, no back button."""

    def render(self) -> Image.Image:
        image, draw = renderer.new_canvas()
        header_font = renderer.load_text_font(layout.HEADER_FONT_SIZE)
        row_font = renderer.load_text_font(_ROW_FONT_SIZE)
        icon_font = renderer.load_icon_font(_ROW_ICON_SIZE)

        layout.draw_header(
            draw,
            "Bridget Media",
            header_font,
            show_back_icon=False,
            icon_font=renderer.load_icon_font(layout.HEADER_FONT_SIZE),
        )

        for index, (label, icon, _) in enumerate(_MENU_ROWS):
            y = layout.row_top(index)
            renderer.draw_divider(draw, y)
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
                (DISPLAY_WIDTH - _CHEVRON_ZONE_WIDTH, y, DISPLAY_WIDTH, y + layout.ROW_HEIGHT),
                icon_font,
            )

        return image

    def handle_touch(self, x: int, y: int) -> Event | None:
        row = layout.row_index_at(y)
        if row is None or row >= len(_MENU_ROWS):
            return None
        return HomeMenuSelected(_MENU_ROWS[row][2])
