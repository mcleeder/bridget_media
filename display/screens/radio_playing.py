from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Final

from PIL import Image, ImageDraw

import display.copy as copy
import display.renderer as renderer
import display.screens.sleep_badge as sleep_badge
from config import DISPLAY_HEIGHT, DISPLAY_WIDTH, Station
from display.events import BackRequested, Event, PlayPauseToggled, SleepTimerRequested
from display.playback import AudioPlayer, PlaybackState

logger = logging.getLogger(__name__)

_STATION_FONT_SIZE: Final[int] = 17
_STATION_TOP: Final[int] = 28
_STATION_LINE_HEIGHT: Final[int] = 20
_STATION_MAX_LINES: Final[int] = 2
_STATION_SIDE_MARGIN: Final[int] = 10

# The line under the station name: an icon and a word, centred as one run.
_STATUS_FONT_SIZE: Final[int] = 10
_STATUS_ICON_SIZE: Final[int] = 14
_STATUS_ICON_GAP: Final[int] = 5
_STATUS_GAP_BELOW_NAME: Final[int] = 10
_STATUS_TEXT_NUDGE: Final[int] = 3

_CONTROLS_TOP: Final[int] = 95

# Back keeps the same width and position it has on Now Playing, so the gesture
# is identical on both players. Play/pause takes everything else: there is no
# seeking on a live stream, so the two skip buttons have nothing to do.
_BACK_WIDTH: Final[int] = DISPLAY_WIDTH // 4
_BTN_BACK: Final[tuple[int, int, int, int]] = (0, _CONTROLS_TOP, _BACK_WIDTH, DISPLAY_HEIGHT)
_BTN_PLAY_PAUSE: Final[tuple[int, int, int, int]] = (
    _BACK_WIDTH,
    _CONTROLS_TOP,
    DISPLAY_WIDTH,
    DISPLAY_HEIGHT,
)

_ICON_SIZE: Final[int] = 22


def _hit(rect: tuple[int, int, int, int], x: int, y: int) -> bool:
    x0, y0, x1, y1 = rect
    return x0 <= x < x1 and y0 <= y < y1


class RadioPlayingScreen:
    """Now Playing for a live stream.

    Deliberately not a mode of NowPlayingScreen: there is no duration, no
    position and no episode, so every element that screen is built around
    (progress bar, elapsed/total, ±30s) would have to be suppressed.
    """

    def __init__(
        self,
        station: Station,
        player: AudioPlayer,
        sleep_minutes_remaining: Callable[[], int | None],
    ) -> None:
        self._station = station
        self._player = player
        self._sleep_minutes_remaining = sleep_minutes_remaining

    def render(self) -> Image.Image:
        image, draw = renderer.new_canvas()
        state = self._read_playback_state()

        # Nothing else occupies the top strip here, so the badge needs no
        # clipping arrangement with a neighbour the way Now Playing does.
        sleep_badge.draw_sleep_badge(draw, self._sleep_minutes_remaining())

        name_bottom = renderer.draw_text_wrapped_centered(
            draw,
            self._station.name,
            _STATION_TOP,
            renderer.load_text_font(_STATION_FONT_SIZE),
            max_width=DISPLAY_WIDTH - 2 * _STATION_SIDE_MARGIN,
            max_lines=_STATION_MAX_LINES,
            line_height=_STATION_LINE_HEIGHT,
        )

        if state is None:
            self._draw_status_line(
                draw, renderer.ICON_ERROR_OUTLINE, copy.PLAYER_UNREACHABLE, name_bottom
            )
        else:
            self._draw_status_line(draw, renderer.ICON_GRAPHIC_EQ, copy.RADIO_LIVE, name_bottom)

        self._draw_controls(draw, state)
        return image

    @staticmethod
    def _draw_status_line(
        draw: ImageDraw.ImageDraw, icon: str, text: str, name_bottom: int
    ) -> None:
        """Icon and text side by side, centred as one block under the name."""
        status_font = renderer.load_text_font(_STATUS_FONT_SIZE)
        text_width = int(draw.textlength(text, font=status_font))
        total_width = _STATUS_ICON_SIZE + _STATUS_ICON_GAP + text_width
        x = (DISPLAY_WIDTH - total_width) // 2
        top = name_bottom + _STATUS_GAP_BELOW_NAME

        renderer.draw_icon_centered(
            draw,
            icon,
            (x, top, x + _STATUS_ICON_SIZE, top + _STATUS_ICON_SIZE),
            renderer.load_icon_font(_STATUS_ICON_SIZE),
        )
        draw.text(
            (x + _STATUS_ICON_SIZE + _STATUS_ICON_GAP, top + _STATUS_TEXT_NUDGE),
            text,
            font=status_font,
            fill=renderer.BLACK,
        )

    def handle_touch(self, x: int, y: int) -> Event | None:
        if sleep_badge.is_sleep_badge_touch(x, y):
            return SleepTimerRequested()
        if _hit(_BTN_BACK, x, y):
            return BackRequested()
        if _hit(_BTN_PLAY_PAUSE, x, y):
            return PlayPauseToggled()
        return None

    def _read_playback_state(self) -> PlaybackState | None:
        try:
            return self._player.get_state()
        except Exception:
            # Player exception types live above this layer and can't be imported here;
            # rendering must degrade to an idle view rather than crash the UI loop.
            logger.debug("Playback state unavailable", exc_info=True)
            return None

    @staticmethod
    def _draw_controls(draw: ImageDraw.ImageDraw, state: PlaybackState | None) -> None:
        icon_font = renderer.load_icon_font(_ICON_SIZE)
        renderer.draw_divider(draw, _CONTROLS_TOP)
        renderer.draw_icon_centered(draw, renderer.ICON_ARROW_BACK, _BTN_BACK, icon_font)
        draw.line(
            [(_BACK_WIDTH, _CONTROLS_TOP), (_BACK_WIDTH, DISPLAY_HEIGHT)], fill=renderer.BLACK
        )

        # Inverted (black button, white icon) to stand out as the primary action
        is_playing = state is not None and state.is_playing
        draw.rectangle(_BTN_PLAY_PAUSE, fill=renderer.BLACK)
        renderer.draw_icon_centered(
            draw,
            renderer.ICON_PAUSE if is_playing else renderer.ICON_PLAY,
            _BTN_PLAY_PAUSE,
            icon_font,
            fill=renderer.WHITE,
        )
