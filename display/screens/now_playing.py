from __future__ import annotations

import logging
from typing import Final

from PIL import Image, ImageDraw

import display.renderer as renderer
from config import DISPLAY_HEIGHT, DISPLAY_WIDTH
from db.models import Episode
from display.events import BackRequested, Event, PlayPauseToggled, SkipRequested
from display.playback import AudioPlayer, PlaybackState

logger = logging.getLogger(__name__)

_FEED_FONT_SIZE: Final[int] = 9
_TITLE_FONT_SIZE: Final[int] = 12
_TIME_FONT_SIZE: Final[int] = 9
_ICON_SIZE: Final[int] = 22

_FEED_NAME_Y: Final[int] = 3
_TITLE_Y: Final[int] = 16
_TITLE_LINE_HEIGHT: Final[int] = 15
_TITLE_MAX_LINES: Final[int] = 2
_PROGRESS_RECT: Final[tuple[int, int, int, int]] = (6, 60, DISPLAY_WIDTH - 6, 68)
_TIME_Y: Final[int] = 73
_CONTROLS_TOP: Final[int] = 95

_SKIP_SECONDS: Final[float] = 30.0

_BUTTON_WIDTH: Final[int] = DISPLAY_WIDTH // 4
_BTN_BACK: Final[tuple[int, int, int, int]] = (0, _CONTROLS_TOP, _BUTTON_WIDTH, DISPLAY_HEIGHT)
_BTN_SKIP_BACK: Final[tuple[int, int, int, int]] = (
    _BUTTON_WIDTH,
    _CONTROLS_TOP,
    _BUTTON_WIDTH * 2,
    DISPLAY_HEIGHT,
)
_BTN_PLAY_PAUSE: Final[tuple[int, int, int, int]] = (
    _BUTTON_WIDTH * 2,
    _CONTROLS_TOP,
    _BUTTON_WIDTH * 3,
    DISPLAY_HEIGHT,
)
_BTN_SKIP_FORWARD: Final[tuple[int, int, int, int]] = (
    _BUTTON_WIDTH * 3,
    _CONTROLS_TOP,
    DISPLAY_WIDTH,
    DISPLAY_HEIGHT,
)


def _format_seconds(total: float) -> str:
    minutes, seconds = divmod(int(total), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _hit(rect: tuple[int, int, int, int], x: int, y: int) -> bool:
    x0, y0, x1, y1 = rect
    return x0 <= x < x1 and y0 <= y < y1


class NowPlayingScreen:
    def __init__(self, episode: Episode, feed_name: str, player: AudioPlayer) -> None:
        self._episode = episode
        self._feed_name = feed_name
        self._player = player

    def render(self) -> Image.Image:
        image, draw = renderer.new_canvas()
        state = self._read_playback_state()

        feed_font = renderer.load_text_font(_FEED_FONT_SIZE)
        title_font = renderer.load_text_font(_TITLE_FONT_SIZE)

        renderer.draw_text_clipped(
            draw, self._feed_name, (6, _FEED_NAME_Y), feed_font, max_width=DISPLAY_WIDTH - 12
        )
        renderer.draw_text_wrapped(
            draw,
            self._episode.title,
            (6, _TITLE_Y),
            title_font,
            max_width=DISPLAY_WIDTH - 12,
            max_lines=_TITLE_MAX_LINES,
            line_height=_TITLE_LINE_HEIGHT,
        )

        self._draw_progress(draw, state)
        self._draw_controls(draw, state)
        return image

    def handle_touch(self, x: int, y: int) -> Event | None:
        if _hit(_BTN_BACK, x, y):
            return BackRequested()
        if _hit(_BTN_SKIP_BACK, x, y):
            return SkipRequested(seconds=-_SKIP_SECONDS)
        if _hit(_BTN_PLAY_PAUSE, x, y):
            return PlayPauseToggled()
        if _hit(_BTN_SKIP_FORWARD, x, y):
            return SkipRequested(seconds=_SKIP_SECONDS)
        return None

    def _read_playback_state(self) -> PlaybackState | None:
        try:
            return self._player.get_state()
        except Exception:
            # Player exception types live above this layer and can't be imported here;
            # rendering must degrade to an idle view rather than crash the UI loop.
            logger.debug("Playback state unavailable", exc_info=True)
            return None

    def _draw_progress(self, draw: ImageDraw.ImageDraw, state: PlaybackState | None) -> None:
        time_font = renderer.load_text_font(_TIME_FONT_SIZE)

        fraction = 0.0
        if state is not None and state.duration_sec:
            fraction = state.elapsed_sec / state.duration_sec
        renderer.draw_progress_bar(draw, _PROGRESS_RECT, fraction)

        elapsed_text = _format_seconds(state.elapsed_sec) if state is not None else "--:--"
        duration_text = (
            _format_seconds(state.duration_sec)
            if state is not None and state.duration_sec
            else "--:--"
        )
        draw.text((6, _TIME_Y), elapsed_text, font=time_font, fill=renderer.BLACK)
        duration_width = int(draw.textlength(duration_text, font=time_font))
        draw.text(
            (DISPLAY_WIDTH - duration_width - 6, _TIME_Y),
            duration_text,
            font=time_font,
            fill=renderer.BLACK,
        )

    def _draw_controls(self, draw: ImageDraw.ImageDraw, state: PlaybackState | None) -> None:
        icon_font = renderer.load_icon_font(_ICON_SIZE)
        renderer.draw_divider(draw, _CONTROLS_TOP)

        for rect, icon in (
            (_BTN_BACK, renderer.ICON_ARROW_BACK),
            (_BTN_SKIP_BACK, renderer.ICON_REPLAY_30),
            (_BTN_SKIP_FORWARD, renderer.ICON_FORWARD_30),
        ):
            renderer.draw_icon_centered(draw, icon, rect, icon_font)
            self._draw_button_separator(draw, rect)

        # Play/pause is inverted (black button, white icon) to stand out as the primary action
        is_playing = state is not None and state.is_playing
        draw.rectangle(_BTN_PLAY_PAUSE, fill=renderer.BLACK)
        play_pause_icon = renderer.ICON_PAUSE if is_playing else renderer.ICON_PLAY
        renderer.draw_icon_centered(
            draw, play_pause_icon, _BTN_PLAY_PAUSE, icon_font, fill=renderer.WHITE
        )

    @staticmethod
    def _draw_button_separator(
        draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int]
    ) -> None:
        x1 = rect[2]
        if x1 < DISPLAY_WIDTH:
            draw.line([(x1, _CONTROLS_TOP), (x1, DISPLAY_HEIGHT)], fill=renderer.BLACK)

