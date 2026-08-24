"""The sleep-timer control shared by both player screens.

It is both the button and the readout, which is what keeps it to one glyph of
screen budget on a 296x128 panel: a bare moon when nothing is set, an inverted
pill with the whole minutes left when a timer is running. Inverted on purpose
— on 1-bit ink "a timer is armed" has to read at a glance, rather than
depending on the reader noticing that some extra text appeared.

Ink and tap target are deliberately different sizes. The ink stays inside the
16px top strip, but nothing else up there is tappable, so the target reaches
down over the title to make a finger-sized 72x30 zone. The same idiom as the
episode list's header doubling as its back button.
"""

from __future__ import annotations

from typing import Final

from PIL import ImageDraw

import display.copy as copy
import display.renderer as renderer
from config import DISPLAY_WIDTH

_ICON_SIZE: Final[int] = 13
_FONT_SIZE: Final[int] = 9
_RIGHT: Final[int] = DISPLAY_WIDTH - 4
_TOP: Final[int] = 1
_BOTTOM: Final[int] = 18
_TEXT_NUDGE: Final[int] = 4
_ICON_TEXT_GAP: Final[int] = 2

# The pill is a fixed width whatever it holds, so arming or clearing the timer
# never reflows the feed name beside it. All four durations are two digits, so
# nothing is wasted on the variable case.
_PILL_WIDTH: Final[int] = 44

# Left edge of the reserved slot — what a neighbouring element must clip at.
INK_LEFT: Final[int] = _RIGHT - _PILL_WIDTH

TOUCH_LEFT: Final[int] = 224
TOUCH_BOTTOM: Final[int] = 30


def draw_sleep_badge(draw: ImageDraw.ImageDraw, minutes: int | None) -> None:
    icon_font = renderer.load_icon_font(_ICON_SIZE)
    if minutes is None:
        renderer.draw_icon_centered(
            draw,
            renderer.ICON_BEDTIME,
            (_RIGHT - _ICON_SIZE, _TOP, _RIGHT, _BOTTOM),
            icon_font,
        )
        return

    text = f"{minutes}{copy.SLEEP_MINUTES_SUFFIX}"
    font = renderer.load_text_font(_FONT_SIZE)
    text_width = int(draw.textlength(text, font=font))
    run_width = _ICON_SIZE + _ICON_TEXT_GAP + text_width
    x = INK_LEFT + (_PILL_WIDTH - run_width) // 2

    draw.rectangle((INK_LEFT, _TOP, _RIGHT, _BOTTOM), fill=renderer.BLACK)
    renderer.draw_icon_centered(
        draw,
        renderer.ICON_BEDTIME,
        (x, _TOP, x + _ICON_SIZE, _BOTTOM),
        icon_font,
        fill=renderer.WHITE,
    )
    draw.text(
        (x + _ICON_SIZE + _ICON_TEXT_GAP, _TOP + _TEXT_NUDGE),
        text,
        font=font,
        fill=renderer.WHITE,
    )


def is_sleep_badge_touch(x: int, y: int) -> bool:
    return x >= TOUCH_LEFT and y < TOUCH_BOTTOM
