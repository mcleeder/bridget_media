"""Pick how long until playback stops.

A 2x2 grid rather than the shared list geometry, which would put two of five
rows below the fold. The one that matters is cancelling: it is what you reach
for when you set the wrong thing, half asleep in the dark, and behind a scroll
is the wrong place for it. Here every choice is one tap on a 148x52 target,
and cancelling is tapping the selected cell again — it is drawn inverted, so
tapping it to turn it back off needs no separate control and no label.
"""

from __future__ import annotations

from typing import Final

from PIL import Image, ImageDraw, ImageFont

import display.copy as copy
import display.renderer as renderer
import display.screens.list_layout as layout
from config import DISPLAY_HEIGHT, DISPLAY_WIDTH
from display.events import BackRequested, Event, SleepDurationSelected
from display.sleep_timer import DURATION_CHOICES

_COLUMNS: Final[int] = 2
_GRID_TOP: Final[int] = layout.HEADER_HEIGHT + 1
_CELL_WIDTH: Final[int] = DISPLAY_WIDTH // _COLUMNS
_CELL_HEIGHT: Final[int] = (DISPLAY_HEIGHT - _GRID_TOP) // 2

_DURATION_FONT_SIZE: Final[int] = 20
_HEADER_ICON_SIZE: Final[int] = 16
# Cap height of the duration font, for optical centring — a text bbox on this
# 1-bit canvas measures the antialiased edge the threshold throws away.
_DURATION_CAP_HEIGHT: Final[int] = 24


def cell_rect(index: int) -> tuple[int, int, int, int]:
    column, row = index % _COLUMNS, index // _COLUMNS
    x0 = column * _CELL_WIDTH
    y0 = _GRID_TOP + row * _CELL_HEIGHT
    return (x0, y0, x0 + _CELL_WIDTH, y0 + _CELL_HEIGHT)


class SleepTimerScreen:
    def __init__(self, active_minutes: int | None) -> None:
        self._active_minutes = active_minutes

    def render(self) -> Image.Image:
        image, draw = renderer.new_canvas()
        layout.draw_header(
            draw,
            copy.HEADER_SLEEP_TIMER,
            renderer.load_text_font(layout.HEADER_FONT_SIZE),
            show_back_icon=True,
            icon_font=renderer.load_icon_font(_HEADER_ICON_SIZE),
        )
        font = renderer.load_text_font(_DURATION_FONT_SIZE)
        for index, minutes in enumerate(DURATION_CHOICES):
            self._draw_cell(draw, index, minutes, font)
        return image

    def _draw_cell(
        self,
        draw: ImageDraw.ImageDraw,
        index: int,
        minutes: int,
        font: ImageFont.FreeTypeFont,
    ) -> None:
        x0, y0, x1, y1 = cell_rect(index)
        is_active = minutes == self._active_minutes
        if is_active:
            draw.rectangle((x0, y0, x1, y1), fill=renderer.BLACK)

        text = f"{minutes}{copy.SLEEP_MINUTES_SUFFIX}"
        text_width = int(draw.textlength(text, font=font))
        draw.text(
            (x0 + (_CELL_WIDTH - text_width) // 2, y0 + (_CELL_HEIGHT - _DURATION_CAP_HEIGHT) // 2),
            text,
            font=font,
            fill=renderer.WHITE if is_active else renderer.BLACK,
        )

        if x1 < DISPLAY_WIDTH:
            draw.line([(x1, y0), (x1, y1)], fill=renderer.BLACK)
        if y1 < DISPLAY_HEIGHT:
            draw.line([(x0, y1), (x1, y1)], fill=renderer.BLACK)

    def handle_touch(self, x: int, y: int) -> Event | None:
        if y < layout.HEADER_HEIGHT:
            return BackRequested()

        column = x // _CELL_WIDTH
        row = (y - _GRID_TOP) // _CELL_HEIGHT
        index = row * _COLUMNS + column
        if not 0 <= index < len(DURATION_CHOICES):
            return None

        minutes = DURATION_CHOICES[index]
        # Tapping the armed duration again clears it — the inverted cell is
        # the affordance, so no separate Off control has to earn its space.
        if minutes == self._active_minutes:
            return SleepDurationSelected(minutes=None)
        return SleepDurationSelected(minutes=minutes)
