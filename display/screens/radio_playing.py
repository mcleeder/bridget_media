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
from display.radio_metadata import TrackMetadata

logger = logging.getLogger(__name__)

# --- the "nothing on air we can name" layout: one big centred station name ---
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

# --- the track layout, used whenever Radio France tells us what is playing ---
_META_STATION_FONT_SIZE: Final[int] = 9
_META_STATION_Y: Final[int] = 2
_META_TITLE_FONT_SIZE: Final[int] = 13
_META_TITLE_Y: Final[int] = 15
_META_TITLE_LINE_HEIGHT: Final[int] = 16
_META_TITLE_MAX_LINES: Final[int] = 2
_META_ARTIST_FONT_SIZE: Final[int] = 10
_META_ARTIST_GAP: Final[int] = 3
_META_ALBUM_FONT_SIZE: Final[int] = 9
_META_ALBUM_GAP: Final[int] = 2
_META_SIDE_MARGIN: Final[int] = 6
# The on-air line is anchored rather than flowed: it is a status, so it should
# not move about depending on how long the track title happens to be.
_META_STATUS_Y: Final[int] = 80
_META_STATUS_ICON_SIZE: Final[int] = 11

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


def _quoted(title: str) -> str:
    """Wrap the title in guillemets, spaced the French way.

    The station is French, the panel has the glyphs, and « » distinguishes the
    track title from the artist and album lines without spending a font weight
    the 1-bit canvas does not really have.
    """
    return f"{copy.QUOTE_OPEN} {title} {copy.QUOTE_CLOSE}"


def _album_line(track: TrackMetadata) -> str | None:
    parts = [part for part in (track.album, str(track.year) if track.year else None) if part]
    return copy.RADIO_ALBUM_SEPARATOR.join(parts) if parts else None


class RadioPlayingScreen:
    """Now Playing for a live stream.

    Deliberately not a mode of NowPlayingScreen: there is no duration, no
    position and no episode, so every element that screen is built around
    (progress bar, elapsed/total, ±30s) would have to be suppressed.

    Two body layouts. When Radio France says what is on air, the track is the
    headline and the station name shrinks to a label; when it does not — a
    jingle, a talk break, or the metadata call simply failing — the station
    name takes the screen back, which is the layout this screen always had.
    """

    def __init__(
        self,
        station: Station,
        player: AudioPlayer,
        sleep_minutes_remaining: Callable[[], int | None],
        current_track: Callable[[], TrackMetadata | None],
    ) -> None:
        self._station = station
        self._player = player
        self._sleep_minutes_remaining = sleep_minutes_remaining
        self._current_track = current_track

    def render(self) -> Image.Image:
        image, draw = renderer.new_canvas()
        state = self._read_playback_state()

        # Nothing else occupies the top strip here, so the badge needs no
        # clipping arrangement with a neighbour the way Now Playing does.
        sleep_badge.draw_sleep_badge(draw, self._sleep_minutes_remaining())

        track = self._current_track()
        if state is not None and track is not None:
            self._draw_track(draw, track)
        else:
            self._draw_station(draw, state)

        self._draw_controls(draw, state)
        return image

    def _draw_track(self, draw: ImageDraw.ImageDraw, track: TrackMetadata) -> None:
        max_width = DISPLAY_WIDTH - 2 * _META_SIDE_MARGIN
        renderer.draw_text_clipped(
            draw,
            self._station.full_name,
            (_META_SIDE_MARGIN, _META_STATION_Y),
            renderer.load_text_font(_META_STATION_FONT_SIZE),
            max_width=sleep_badge.INK_LEFT - _META_SIDE_MARGIN - 6,
        )

        title_font = renderer.load_text_font(_META_TITLE_FONT_SIZE)
        title = _quoted(track.title)
        lines = renderer.wrap_lines(draw, title, title_font, max_width, _META_TITLE_MAX_LINES)
        renderer.draw_text_wrapped(
            draw,
            title,
            (_META_SIDE_MARGIN, _META_TITLE_Y),
            title_font,
            max_width=max_width,
            max_lines=_META_TITLE_MAX_LINES,
            line_height=_META_TITLE_LINE_HEIGHT,
        )
        # Flowed from the real line count, so a one-line title leaves no gap —
        # the same rule Now Playing uses for its publish date.
        y = _META_TITLE_Y + len(lines) * _META_TITLE_LINE_HEIGHT

        if track.artist is not None:
            renderer.draw_text_clipped(
                draw,
                track.artist,
                (_META_SIDE_MARGIN, y + _META_ARTIST_GAP),
                renderer.load_text_font(_META_ARTIST_FONT_SIZE),
                max_width=max_width,
            )
            y += _META_ARTIST_GAP + _META_ARTIST_FONT_SIZE + 3

        album = _album_line(track)
        if album is not None:
            renderer.draw_text_clipped(
                draw,
                album,
                (_META_SIDE_MARGIN, y + _META_ALBUM_GAP),
                renderer.load_text_font(_META_ALBUM_FONT_SIZE),
                max_width=max_width,
            )

        self._draw_on_air(draw)

    @staticmethod
    def _draw_on_air(draw: ImageDraw.ImageDraw) -> None:
        """The live marker, left-aligned at a fixed height above the controls."""
        font = renderer.load_text_font(_META_ALBUM_FONT_SIZE)
        renderer.draw_icon_centered(
            draw,
            renderer.ICON_GRAPHIC_EQ,
            (
                _META_SIDE_MARGIN,
                _META_STATUS_Y,
                _META_SIDE_MARGIN + _META_STATUS_ICON_SIZE,
                _META_STATUS_Y + _META_STATUS_ICON_SIZE,
            ),
            renderer.load_icon_font(_META_STATUS_ICON_SIZE),
        )
        draw.text(
            (_META_SIDE_MARGIN + _META_STATUS_ICON_SIZE + 4, _META_STATUS_Y + 1),
            copy.RADIO_LIVE,
            font=font,
            fill=renderer.BLACK,
        )

    def _draw_station(self, draw: ImageDraw.ImageDraw, state: PlaybackState | None) -> None:
        name_bottom = renderer.draw_text_wrapped_centered(
            draw,
            self._station.full_name,
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
