from __future__ import annotations

import dataclasses
import logging
import time
from collections.abc import Callable
from typing import Final

from db.database import DatabaseError
from db.models import Episode, Feed
from db.queries import EpisodeRepository, FeedRepository, QueueRepository
from display.bluetooth_control import BluetoothDevice, BluetoothService
from display.drivers.base import DisplayDriver
from display.events import (
    BackRequested,
    BluetoothDeviceSelected,
    EpisodeSelected,
    Event,
    FeedSelected,
    HomeMenuItem,
    HomeMenuSelected,
    ListScrolled,
    PlayPauseToggled,
    QueueRemoveRequested,
    QueueToggled,
    SkipRequested,
)
from display.playback import AudioPlayer, PlaybackState
from display.screens.base import Screen
from display.screens.bluetooth_list import BluetoothScreen
from display.screens.episode_list import EpisodeListScreen
from display.screens.home import HomeScreen
from display.screens.now_playing import NowPlayingScreen
from display.screens.podcast_list import PodcastListScreen
from display.screens.queue_list import QueueListScreen
from display.state_machine import AppState, transition

logger = logging.getLogger(__name__)

# An episode counts as played once this fraction of it has been heard.
_PLAYED_FRACTION_THRESHOLD: Final[float] = 0.9

# How often the play position is written to the database while listening —
# a compromise between resume accuracy and SD-card write wear.
_POSITION_PERSIST_INTERVAL_SEC: Final[float] = 30.0

# One physical tap can arrive as two touch events: capacitive jitter moves
# the coordinate a pixel or two, defeating the driver's held-finger filter.
# For toggle actions a double-fire silently undoes itself, so taps inside
# this window are ignored (e-ink can't visibly respond faster anyway).
_TOUCH_DEBOUNCE_SEC: Final[float] = 0.3

# Screen transitions normally use flash-free partial refresh; every Nth
# transition gets a real full refresh to clear accumulated e-ink ghosting
# (the same page-flash cadence e-readers use).
_TRANSITIONS_BETWEEN_FULL_REFRESHES: Final[int] = 5


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
        queue_repository: QueueRepository,
        player: AudioPlayer,
        bluetooth: BluetoothService,
    ) -> None:
        self._driver = driver
        self._feed_repository = feed_repository
        self._episode_repository = episode_repository
        self._queue_repository = queue_repository
        self._player = player
        self._bluetooth = bluetooth

        self._state: AppState = AppState.HOME
        self._selected_feed: Feed | None = None
        self._playing_episode: Episode | None = None
        # Previous playback poll — natural-finish detection compares two
        # consecutive polls. Reset whenever playback (re)starts or stops.
        self._last_playback_state: PlaybackState | None = None
        # Where Back from Now Playing returns to — see transition()
        self._now_playing_origin: AppState = AppState.EPISODE_LIST
        self._last_position_persist: float = 0.0
        self._last_touch_time: float = 0.0
        # Start at the threshold so the very first frame is a full refresh,
        # giving later partial refreshes a base frame to diff against.
        self._transitions_since_full_refresh: int = _TRANSITIONS_BETWEEN_FULL_REFRESHES
        self._home_screen = HomeScreen()
        self._podcast_screen = PodcastListScreen(feed_repository.get_all())
        self._episode_screen: EpisodeListScreen | None = None
        self._queue_screen: QueueListScreen | None = None
        self._now_playing_screen: NowPlayingScreen | None = None
        self._bluetooth_screen: BluetoothScreen | None = None

        self._show(full_refresh=True)

    def handle_touch(self, x: int, y: int) -> None:
        now = time.monotonic()
        if now - self._last_touch_time < _TOUCH_DEBOUNCE_SEC:
            return
        self._last_touch_time = now

        event = self._current_screen().handle_touch(x, y)
        if event is None:
            return

        self._apply_side_effects(event)
        next_state = transition(self._state, event, self._now_playing_origin)

        if next_state is AppState.NOW_PLAYING and self._state is not AppState.NOW_PLAYING:
            self._now_playing_origin = self._state

        if next_state is not self._state:
            logger.info(
                "State %s -> %s on %s", self._state.name, next_state.name, type(event).__name__
            )
            self._state = next_state
            self._show(full_refresh=True)
        elif isinstance(
            event,
            ListScrolled
            | PlayPauseToggled
            | SkipRequested
            | QueueToggled
            | QueueRemoveRequested
            | BluetoothDeviceSelected,
        ):
            self._show(full_refresh=False)

    def refresh_playback(self) -> None:
        """Poll playback and redraw progress. Called periodically by the main loop.

        Polling runs whenever an episode is active, whatever screen is showing —
        mark-played, position persistence, and queue auto-advance must not stop
        because the user navigated away — but only Now Playing is redrawn.
        """
        if self._playing_episode is not None:
            self._poll_playback()
        if self._state is AppState.NOW_PLAYING:
            self._show(full_refresh=False)

    def _poll_playback(self) -> None:
        state = self._read_player_state()
        if state is None:
            return
        previous = self._last_playback_state
        self._last_playback_state = state
        if self._is_natural_finish(previous, state):
            try:
                self._advance_queue()
            except DatabaseError:
                # A DB hiccup must not kill the UI loop. The advance won't
                # re-fire: _playing_episode is already cleared, so polling
                # stops until the user starts something new.
                logger.exception("Queue auto-advance failed")
            return
        self._mark_played_if_past_threshold(state)
        # Only a playing elapsed value is trustworthy — MPD reports elapsed 0
        # when stopped, which would zero a good saved position.
        if state.is_playing:
            self._persist_position_throttled(state)

    def reload_feeds(self) -> None:
        """Rebuild the podcast list from the database after a background fetch."""
        try:
            feeds = self._feed_repository.get_all()
        except DatabaseError:
            logger.exception("Could not reload feeds after fetch")
            return
        self._podcast_screen = PodcastListScreen(feeds, self._podcast_screen.scroll_offset)
        logger.info("Podcast list reloaded (%d feeds)", len(feeds))
        if self._state is AppState.PODCAST_LIST:
            self._show(full_refresh=False)

    def _apply_side_effects(self, event: Event) -> None:
        match event:
            case HomeMenuSelected(item=HomeMenuItem.QUEUE):
                self._queue_screen = QueueListScreen(self._queue_repository.get_entries())
            case HomeMenuSelected(item=HomeMenuItem.BLUETOOTH):
                self._rebuild_bluetooth_screen()
            case BluetoothDeviceSelected(device) if not device.is_connected:
                self._show_bluetooth_connecting(device)
                self._bluetooth_command(
                    lambda: self._bluetooth.activate_device(device.mac), "activate device"
                )
                self._rebuild_bluetooth_screen()
            case BluetoothDeviceSelected(device):
                self._bluetooth_command(
                    lambda: self._bluetooth.disconnect_device(device.mac), "disconnect device"
                )
                self._rebuild_bluetooth_screen()
            case FeedSelected(feed):
                self._selected_feed = feed
                episodes = self._episode_repository.get_for_feed(feed.id)
                queued = self._queue_repository.queued_episode_ids()
                self._episode_screen = EpisodeListScreen(feed, episodes, queued)
            case EpisodeSelected(episode):
                self._start_episode(episode)
            case BackRequested() if self._state is AppState.NOW_PLAYING:
                state = self._read_player_state()
                if state is not None:
                    self._persist_position_now(state)
                self._player_command(self._player.stop, "stop")
                self._playing_episode = None
                self._last_playback_state = None
                # Rebuild whichever list Back returns to, so played markers
                # and queue membership are current.
                if self._now_playing_origin is AppState.QUEUE:
                    self._rebuild_queue_screen()
                else:
                    self._rebuild_episode_screen()
            case QueueToggled(episode):
                self._queue_command(lambda: self._toggle_queued(episode), "toggle queue")
            case QueueRemoveRequested(episode):
                self._queue_command(lambda: self._remove_queued(episode), "remove from queue")
            case PlayPauseToggled():
                self._toggle_play_pause()
            case SkipRequested(seconds) if seconds >= 0:
                self._player_command(lambda: self._player.skip_forward(seconds), "skip forward")
            case SkipRequested(seconds):
                self._player_command(lambda: self._player.skip_back(-seconds), "skip back")
            case _:
                pass

    def _read_player_state(self) -> PlaybackState | None:
        try:
            return self._player.get_state()
        except Exception:
            # Player exception types live above this layer (see layer hierarchy);
            # callers treat None as "playback state unavailable".
            logger.debug("Playback state unavailable", exc_info=True)
            return None

    def _is_natural_finish(
        self, previous: PlaybackState | None, current: PlaybackState
    ) -> bool:
        """A natural finish is a stop observed right after playing near the end.

        The near-the-end requirement filters out decode-failure stops (which
        land far from the end); user-initiated stops never reach here because
        Back clears _playing_episode before stopping the player.
        """
        if previous is None or not current.is_stopped or not previous.is_playing:
            return False
        episode = self._playing_episode
        # MPD usually knows the stream duration; fall back to the feed's value.
        duration = previous.duration_sec or (episode.duration_sec if episode else None)
        if not duration:
            return False
        return previous.elapsed_sec / duration >= _PLAYED_FRACTION_THRESHOLD

    def _advance_queue(self) -> None:
        """Handle a natural finish: pop the queue and start whatever is next.

        The finished episode's queue entry is dropped whether or not playback
        started from the queue, and any natural finish starts the queue head.
        """
        finished = self._playing_episode
        self._playing_episode = None
        self._last_playback_state = None
        if finished is not None:
            self._queue_command(
                lambda: self._queue_repository.remove(finished.id),
                "remove finished episode",
            )
            if not finished.played:
                # Normally the 90% threshold already fired; this catches a DB
                # hiccup there so a finished episode never stays unplayed.
                self._mark_episode_played(finished)
        next_entry = self._queue_repository.first_entry()
        if next_entry is not None:
            logger.info("Auto-advancing to queued episode: %s", next_entry.episode.title)
            self._start_episode(next_entry.episode)
        # Refresh whichever screen shows now-stale data. NOW_PLAYING needs no
        # rebuild here: _start_episode replaced it, and refresh_playback's
        # trailing _show redraws it either way.
        if self._state is AppState.QUEUE:
            self._rebuild_queue_screen()
            self._show(full_refresh=False)
        elif self._state is AppState.EPISODE_LIST:
            self._rebuild_episode_screen()
            self._show(full_refresh=False)

    def _mark_played_if_past_threshold(self, state: PlaybackState) -> None:
        episode = self._playing_episode
        if episode is None or episode.played:
            return
        # MPD usually knows the stream duration; fall back to the feed's value.
        duration = state.duration_sec or episode.duration_sec
        if not duration or state.elapsed_sec / duration < _PLAYED_FRACTION_THRESHOLD:
            return
        if self._mark_episode_played(episode):
            # Replace the cached copy so the check doesn't re-fire every refresh
            self._playing_episode = dataclasses.replace(episode, played=True)

    def _mark_episode_played(self, episode: Episode) -> bool:
        try:
            self._episode_repository.mark_played(episode.id)
            # A played episode restarts from the beginning next time.
            self._episode_repository.update_play_position(episode.id, 0)
        except DatabaseError:
            logger.exception("Could not mark episode %d as played", episode.id)
            return False
        logger.info("Episode marked played: %s", episode.title)
        return True

    def _persist_position_throttled(self, state: PlaybackState) -> None:
        if time.monotonic() - self._last_position_persist < _POSITION_PERSIST_INTERVAL_SEC:
            return
        self._persist_position_now(state)

    def _persist_position_now(self, state: PlaybackState) -> None:
        episode = self._playing_episode
        if episode is None or episode.played:
            return
        try:
            self._episode_repository.update_play_position(episode.id, int(state.elapsed_sec))
        except DatabaseError:
            logger.exception("Could not save play position for episode %d", episode.id)
            return
        self._last_position_persist = time.monotonic()

    def _start_episode(self, episode: Episode) -> None:
        """Begin playback and build the Now Playing screen.

        Feed name comes from the repository, not _selected_feed — playback can
        start from the queue, where no feed is selected.
        """
        feed = self._feed_repository.get_by_id(episode.feed_id)
        feed_name = feed.name if feed is not None else ""
        self._playing_episode = episode
        self._last_playback_state = None
        self._now_playing_screen = NowPlayingScreen(episode, feed_name, self._player)
        self._player_command(lambda: self._player.play(episode.audio_url), "play")
        if episode.play_position_sec > 0 and not episode.played:
            self._player_command(
                lambda: self._player.seek(float(episode.play_position_sec)),
                "resume from saved position",
            )
        self._last_position_persist = time.monotonic()

    def _toggle_queued(self, episode: Episode) -> None:
        if episode.id in self._queue_repository.queued_episode_ids():
            self._queue_repository.remove(episode.id)
        else:
            self._queue_repository.add(episode.id)
        self._rebuild_episode_screen()

    def _remove_queued(self, episode: Episode) -> None:
        self._queue_repository.remove(episode.id)
        self._rebuild_queue_screen()

    def _queue_command(self, command: Callable[[], None], description: str) -> None:
        try:
            command()
        except DatabaseError:
            # A transient DB failure must degrade to a log line, not kill the
            # UI loop — the list simply redraws with its previous contents.
            logger.exception("Queue update failed: %s", description)

    def _rebuild_episode_screen(self) -> None:
        """Re-query the selected feed so played markers and new episodes are current."""
        if self._selected_feed is None:
            return
        scroll_offset = self._episode_screen.scroll_offset if self._episode_screen else 0
        episodes = self._episode_repository.get_for_feed(self._selected_feed.id)
        queued = self._queue_repository.queued_episode_ids()
        self._episode_screen = EpisodeListScreen(
            self._selected_feed, episodes, queued, scroll_offset
        )

    def _rebuild_queue_screen(self) -> None:
        """Re-query the queue, preserving scroll position."""
        scroll_offset = self._queue_screen.scroll_offset if self._queue_screen else 0
        self._queue_screen = QueueListScreen(self._queue_repository.get_entries(), scroll_offset)

    def _toggle_play_pause(self) -> None:
        state = self._read_player_state()
        if state is None:
            # Without playback state there is nothing sensible to toggle.
            logger.warning("Cannot toggle play/pause: playback state unavailable")
            return
        if state.is_playing:
            # Save the position on pause so a crash or shutdown while paused
            # still resumes from the right place.
            self._persist_position_now(state)
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

    def _bluetooth_command(self, command: Callable[[], None], description: str) -> None:
        try:
            command()
        except Exception:
            # Bluetooth exception types live above this layer (see layer hierarchy);
            # a bluetooth failure must degrade to a log line, not kill the UI loop.
            logger.exception("Bluetooth command failed: %s", description)

    def _rebuild_bluetooth_screen(self) -> None:
        """Re-query paired devices; a fetch failure shows as an on-screen error."""
        scroll_offset = self._bluetooth_screen.scroll_offset if self._bluetooth_screen else 0
        try:
            devices = self._bluetooth.list_paired_devices()
        except Exception:
            # Bluetooth exception types live above this layer (see layer hierarchy).
            logger.exception("Could not list paired Bluetooth devices")
            devices = None
        self._bluetooth_screen = BluetoothScreen(devices, scroll_offset)

    def _show_bluetooth_connecting(self, device: BluetoothDevice) -> None:
        """Flash a 'Connecting…' frame before the blocking activate_device call."""
        scroll_offset = self._bluetooth_screen.scroll_offset if self._bluetooth_screen else 0
        self._bluetooth_screen = BluetoothScreen(
            None, scroll_offset, connecting_device_name=device.name
        )
        self._show(full_refresh=False)

    def _current_screen(self) -> Screen:
        match self._state:
            case AppState.HOME:
                return self._home_screen
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
            case AppState.QUEUE:
                if self._queue_screen is None:
                    raise DisplayError("QUEUE state reached without a queue screen")
                return self._queue_screen
            case AppState.BLUETOOTH:
                if self._bluetooth_screen is None:
                    raise DisplayError("BLUETOOTH state reached without a bluetooth screen")
                return self._bluetooth_screen

    def _show(self, full_refresh: bool) -> None:
        image = self._current_screen().render()
        if full_refresh:
            self._transitions_since_full_refresh += 1
            if self._transitions_since_full_refresh > _TRANSITIONS_BETWEEN_FULL_REFRESHES:
                self._transitions_since_full_refresh = 0
                self._driver.display(image)
                return
        self._driver.display_partial(image)
