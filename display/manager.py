from __future__ import annotations

import logging
from collections.abc import Callable

from db.models import Feed
from db.queries import EpisodeRepository, FeedRepository
from display.drivers.base import DisplayDriver
from display.events import (
    BackRequested,
    EpisodeSelected,
    Event,
    FeedSelected,
    ListScrolled,
    PlayPauseToggled,
    SkipRequested,
)
from display.playback import AudioPlayer
from display.screens.base import Screen
from display.screens.episode_list import EpisodeListScreen
from display.screens.now_playing import NowPlayingScreen
from display.screens.podcast_list import PodcastListScreen
from display.state_machine import AppState, transition

logger = logging.getLogger(__name__)


class DisplayError(Exception):
    pass


class ScreenManager:
    """Drives the UI state machine.

    Screens translate touches into events; this class applies each event's
    side effects (player commands, screen construction), asks the pure
    transition function for the next state, and refreshes the display —
    full refresh on state changes, partial refresh for in-screen updates.
    """

    def __init__(
        self,
        driver: DisplayDriver,
        feed_repository: FeedRepository,
        episode_repository: EpisodeRepository,
        player: AudioPlayer,
    ) -> None:
        self._driver = driver
        self._episode_repository = episode_repository
        self._player = player

        self._state: AppState = AppState.PODCAST_LIST
        self._selected_feed: Feed | None = None
        self._podcast_screen = PodcastListScreen(feed_repository.get_all())
        self._episode_screen: EpisodeListScreen | None = None
        self._now_playing_screen: NowPlayingScreen | None = None

        self._show(full_refresh=True)

    def handle_touch(self, x: int, y: int) -> None:
        event = self._current_screen().handle_touch(x, y)
        if event is None:
            return

        self._apply_side_effects(event)
        next_state = transition(self._state, event)

        if next_state is not self._state:
            logger.info(
                "State %s -> %s on %s", self._state.name, next_state.name, type(event).__name__
            )
            self._state = next_state
            self._show(full_refresh=True)
        elif isinstance(event, ListScrolled | PlayPauseToggled | SkipRequested):
            self._show(full_refresh=False)

    def refresh_playback(self) -> None:
        """Redraw playback progress. Called periodically by the main loop."""
        if self._state is AppState.NOW_PLAYING:
            self._show(full_refresh=False)

    def _apply_side_effects(self, event: Event) -> None:
        match event:
            case FeedSelected(feed):
                self._selected_feed = feed
                episodes = self._episode_repository.get_for_feed(feed.id)
                self._episode_screen = EpisodeListScreen(feed, episodes)
            case EpisodeSelected(episode):
                feed_name = self._selected_feed.name if self._selected_feed else ""
                self._now_playing_screen = NowPlayingScreen(episode, feed_name, self._player)
                self._player_command(lambda: self._player.play(episode.audio_url), "play")
            case BackRequested() if self._state is AppState.NOW_PLAYING:
                self._player_command(self._player.stop, "stop")
            case PlayPauseToggled():
                self._toggle_play_pause()
            case SkipRequested(seconds) if seconds >= 0:
                self._player_command(lambda: self._player.skip_forward(seconds), "skip forward")
            case SkipRequested(seconds):
                self._player_command(lambda: self._player.skip_back(-seconds), "skip back")
            case _:
                pass

    def _toggle_play_pause(self) -> None:
        try:
            is_playing = self._player.get_state().is_playing
        except Exception:
            # Player exception types live above this layer (see layer hierarchy);
            # without playback state there is nothing sensible to toggle.
            logger.warning("Cannot toggle play/pause: playback state unavailable")
            return
        if is_playing:
            self._player_command(self._player.pause, "pause")
        else:
            self._player_command(self._player.resume, "resume")

    def _player_command(self, command: Callable[[], None], description: str) -> None:
        try:
            command()
        except Exception:
            # Player exception types live above this layer (see layer hierarchy);
            # a playback failure must degrade to a log line, not kill the UI loop.
            logger.exception("Player command failed: %s", description)

    def _current_screen(self) -> Screen:
        match self._state:
            case AppState.PODCAST_LIST:
                return self._podcast_screen
            case AppState.EPISODE_LIST:
                if self._episode_screen is None:
                    raise DisplayError("EPISODE_LIST state reached without an episode screen")
                return self._episode_screen
            case AppState.NOW_PLAYING:
                if self._now_playing_screen is None:
                    raise DisplayError("NOW_PLAYING state reached without a now-playing screen")
                return self._now_playing_screen

    def _show(self, full_refresh: bool) -> None:
        image = self._current_screen().render()
        if full_refresh:
            self._driver.display(image)
        else:
            self._driver.display_partial(image)
