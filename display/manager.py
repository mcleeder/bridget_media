from __future__ import annotations

import dataclasses
import logging
import queue
import threading
import time
from collections.abc import Callable, Sequence
from typing import Final

import display.copy as copy
from config import RADIO_METADATA_POLL_SEC, Station
from db.database import DatabaseError
from db.models import Episode, Feed
from db.queries import EpisodeRepository, FeedRepository, QueueRepository
from display.bluetooth_control import BluetoothDevice, BluetoothService
from display.drivers.base import DisplayDriver
from display.errors import DisplayError
from display.events import (
    BackRequested,
    BluetoothDeviceSelected,
    BluetoothForgetRequested,
    BluetoothPairRequested,
    BluetoothScanRequested,
    EpisodeSelected,
    Event,
    FeedSelected,
    HomeMenuItem,
    HomeMenuSelected,
    HotspotRequested,
    ListScrolled,
    PlayPauseToggled,
    QueueRemoveRequested,
    QueueToggled,
    SkipRequested,
    SleepDurationSelected,
    SleepTimerRequested,
    StationSelected,
)
from display.network_control import HotspotCredentials, NetworkService, NetworkStatus
from display.playback import AudioPlayer, PlaybackState
from display.radio_metadata import RadioMetadataService, TrackMetadata
from display.screens.base import Screen
from display.screens.bluetooth_discover import BluetoothDiscoverScreen
from display.screens.bluetooth_list import BluetoothScreen
from display.screens.episode_list import EpisodeListScreen
from display.screens.home import HomeScreen
from display.screens.now_playing import NowPlayingScreen
from display.screens.podcast_list import PodcastListScreen
from display.screens.queue_list import QueueListScreen
from display.screens.radio_list import RadioListScreen
from display.screens.radio_playing import RadioPlayingScreen
from display.screens.sleep_timer import SleepTimerScreen
from display.screens.wifi_list import WifiScreen
from display.screens.wifi_setup import WifiSetupScreen
from display.sleep_timer import (
    DURATION_CHOICES,
    SleepTimer,
    is_expired,
    remaining_minutes,
    start,
)
from display.state_machine import AppState, NavigationContext, transition

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


def _track_identity(track: TrackMetadata | None) -> tuple[str, str | None] | None:
    """What makes two metadata reads "the same track" for redraw purposes."""
    return None if track is None else (track.title, track.artist)


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
        network: NetworkService,
        radio_metadata: RadioMetadataService,
        stations: Sequence[Station],
    ) -> None:
        self._driver = driver
        self._feed_repository = feed_repository
        self._episode_repository = episode_repository
        self._queue_repository = queue_repository
        self._player = player
        self._bluetooth = bluetooth
        self._network = network
        self._radio_metadata = radio_metadata

        self._state: AppState = AppState.HOME
        self._selected_feed: Feed | None = None
        self._playing_episode: Episode | None = None
        # Never set at the same time as _playing_episode: starting either one
        # releases the other, so the episode polling in _poll_playback can't
        # run against a live stream.
        self._playing_station: Station | None = None
        # Previous playback poll — natural-finish detection compares two
        # consecutive polls. Reset whenever playback (re)starts or stops.
        self._last_playback_state: PlaybackState | None = None
        # Where Back from Now Playing / the duration screen returns to — see
        # NavigationContext in display/state_machine.py
        self._now_playing_origin: AppState = AppState.EPISODE_LIST
        self._sleep_timer_origin: AppState = AppState.NOW_PLAYING
        # Session state, never persisted: a sleep timer that survived a restart
        # would stop playback at a deadline nobody set.
        self._sleep_timer: SleepTimer | None = None
        self._last_position_persist: float = 0.0
        self._last_touch_time: float = 0.0
        # Start at the threshold so the very first frame is a full refresh,
        # giving later partial refreshes a base frame to diff against.
        self._transitions_since_full_refresh: int = _TRANSITIONS_BETWEEN_FULL_REFRESHES
        self._home_screen = HomeScreen()
        self._podcast_screen = PodcastListScreen(feed_repository.get_all())
        self._radio_screen = RadioListScreen(stations)
        self._episode_screen: EpisodeListScreen | None = None
        self._queue_screen: QueueListScreen | None = None
        self._now_playing_screen: NowPlayingScreen | None = None
        self._radio_playing_screen: RadioPlayingScreen | None = None
        self._bluetooth_screen: BluetoothScreen | None = None
        self._discover_screen: BluetoothDiscoverScreen | None = None
        self._wifi_screen: WifiScreen | None = None
        self._wifi_setup_screen: WifiSetupScreen | None = None
        self._sleep_timer_screen: SleepTimerScreen | None = None

        # Device discovery is the one bluetooth call run off the UI thread: it
        # takes ~15s and, unlike pairing, the user may well want to back out of
        # it. The worker only shells out to bluetoothctl — it touches no sqlite
        # connection and never draws — so the result crosses back as a plain
        # list through this queue and all rendering stays on the UI thread.
        self._scan_results: queue.Queue[tuple[int, Sequence[BluetoothDevice] | None]] = (
            queue.Queue(maxsize=1)
        )
        self._scan_in_progress: bool = False
        # Bumped whenever a scan is abandoned, so a late result is discarded
        # instead of redrawing a screen the user already left.
        self._scan_generation: int = 0

        # The network status check qualifies for a background thread on the
        # same terms as the scan: it only shells out to nmcli, touches no
        # sqlite connection and never draws.
        self._status_results: queue.Queue[tuple[int, NetworkStatus | None]] = queue.Queue(
            maxsize=1
        )
        self._status_check_in_progress: bool = False
        self._status_generation: int = 0

        # What Radio France says is on air. Fetched on the same terms as the
        # scan and the status check — HTTP only, no sqlite, no drawing — and
        # only ever while the radio player is the screen being looked at, so a
        # box sitting on Home makes no requests at all.
        self._track_results: queue.Queue[tuple[int, TrackMetadata | None]] = queue.Queue(
            maxsize=1
        )
        self._current_track: TrackMetadata | None = None
        self._track_fetch_in_progress: bool = False
        self._track_generation: int = 0
        self._last_track_fetch: float = 0.0

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
        # Origins are recorded from the event that *enters* a screen, never
        # from "the next state happens to be it". Returning to Now Playing
        # from the sleep-timer screen is also a transition into NOW_PLAYING,
        # and recording that would set the origin to SLEEP_TIMER — leaving
        # Back bouncing between the two screens with no way out to the list.
        if isinstance(event, EpisodeSelected):
            self._now_playing_origin = self._state
        if isinstance(event, SleepTimerRequested):
            self._sleep_timer_origin = self._state

        context = NavigationContext(
            now_playing_origin=self._now_playing_origin,
            sleep_timer_origin=self._sleep_timer_origin,
        )
        next_state = transition(self._state, event, context)

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
            | BluetoothDeviceSelected
            | BluetoothScanRequested
            | BluetoothForgetRequested,
        ):
            self._show(full_refresh=False)

    def refresh_playback(self) -> None:
        """Poll playback and redraw progress. Called periodically by the main loop.

        Polling runs whenever an episode is active, whatever screen is showing —
        mark-played, position persistence, and queue auto-advance must not stop
        because the user navigated away — but only Now Playing is redrawn.
        """
        # First and unconditional. Someone can set a timer and navigate to Home
        # before dozing off, and radio runs with no polling at all, so anything
        # narrower silently never fires for half the cases.
        self._check_sleep_timer()
        if self._playing_episode is not None:
            self._poll_playback()
        # Radio needs no polling — nothing to persist, mark or advance — but the
        # screen is still redrawn so the play/pause icon follows a dropped stream.
        self._refresh_track_metadata()
        if self._state in (AppState.NOW_PLAYING, AppState.RADIO_PLAYING):
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
            case HomeMenuSelected(item=HomeMenuItem.WIFI):
                self._start_status_check()
            case HotspotRequested():
                self._start_hotspot()
            case BluetoothDeviceSelected(device) if not device.is_connected:
                self._show_bluetooth_connecting(device)
                self._bluetooth_command(
                    lambda: self._bluetooth.activate_device(device.mac), "activate device"
                )
                self._rebuild_bluetooth_screen()
                self._drain_touches()
            case BluetoothDeviceSelected(device):
                self._bluetooth_command(
                    lambda: self._bluetooth.disconnect_device(device.mac), "disconnect device"
                )
                self._rebuild_bluetooth_screen()
            case BluetoothScanRequested():
                self._start_scan()
            case BluetoothPairRequested(device):
                self._pair_device(device)
            case BluetoothForgetRequested(device):
                self._bluetooth_command(
                    lambda: self._bluetooth.forget_device(device.mac), "forget device"
                )
                self._rebuild_bluetooth_screen()
            case FeedSelected(feed):
                self._selected_feed = feed
                episodes = self._episode_repository.get_for_feed(feed.id)
                queued = self._queue_repository.queued_episode_ids()
                self._episode_screen = EpisodeListScreen(feed, episodes, queued)
            case EpisodeSelected(episode):
                self._start_episode(episode)
            case StationSelected(station):
                self._start_station(station)
            case SleepTimerRequested():
                self._sleep_timer_screen = SleepTimerScreen(self._armed_minutes())
            case SleepDurationSelected(minutes):
                self._set_sleep_timer(minutes)
            case BackRequested() if self._state is AppState.RADIO_PLAYING:
                self._playing_station = None
                self._abandon_track_fetch()
                self._player_command(self._player.stop, "stop")
            case BackRequested() if self._state is AppState.WIFI:
                self._abandon_status_check()
            case BackRequested() if self._state is AppState.WIFI_SETUP:
                # The hotspot changed what the status screen should say.
                self._start_status_check()
            case BackRequested() if self._state is AppState.BLUETOOTH_DISCOVER:
                # The paired list behind us is still current — nothing in this
                # screen changes it except pairing, which doesn't exit via Back.
                self._abandon_scan()
            case BackRequested() if self._state is AppState.NOW_PLAYING:
                self._release_playing_episode()
                self._player_command(self._player.stop, "stop")
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
        """Handle a natural finish: drop the finished entry, continue the queue.

        Auto-advance only fires when the finished episode was itself queued.
        Advancing after *any* natural finish meant one forgotten queue entry
        ambushed the user at the end of every episode they had started straight
        from the episode list — an unrelated podcast began playing unasked.
        The finished episode's entry is still dropped either way.
        """
        finished = self._playing_episode
        self._playing_episode = None
        self._last_playback_state = None
        was_queued = False
        if finished is not None:
            was_queued = self._is_queued(finished)
            self._queue_command(
                lambda: self._queue_repository.remove(finished.id),
                "remove finished episode",
            )
            if not finished.played:
                # Normally the 90% threshold already fired; this catches a DB
                # hiccup there so a finished episode never stays unplayed.
                self._mark_episode_played(finished)
        next_entry = self._queue_repository.first_entry() if was_queued else None
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

    def _is_queued(self, episode: Episode) -> bool:
        """Whether the episode is still in the queue — the gate on auto-advance.

        A read failure counts as not queued: skipping the advance is the safe
        wrong answer, since starting an unasked-for episode is what it guards.
        """
        try:
            return episode.id in self._queue_repository.queued_episode_ids()
        except DatabaseError:
            logger.exception("Could not read queue membership for episode %d", episode.id)
            return False

    def _read_current_track(self) -> TrackMetadata | None:
        """What the radio screen draws. Pulled at render time, like the
        playback state, so a screen built once never shows a stale track."""
        return self._current_track

    def _sleep_minutes_remaining(self) -> int | None:
        """Whole minutes left, or None when nothing is armed. Read by both players."""
        timer = self._sleep_timer
        if timer is None:
            return None
        return remaining_minutes(timer, time.monotonic())

    def _armed_minutes(self) -> int | None:
        """Which duration cell the grid draws as selected.

        Derived from what is left rather than remembered separately, so the
        two can never disagree; a timer with 28 minutes to run marks 30.
        """
        remaining = self._sleep_minutes_remaining()
        if remaining is None:
            return None
        return min(DURATION_CHOICES, key=lambda choice: (abs(choice - remaining), choice))

    def _set_sleep_timer(self, minutes: int | None) -> None:
        if minutes is None:
            self._sleep_timer = None
            logger.info("Sleep timer cleared")
            return
        self._sleep_timer = start(minutes, time.monotonic())
        logger.info("Sleep timer set for %d minutes", minutes)

    def _check_sleep_timer(self) -> None:
        """Stop playback once the deadline passes.

        Expiry must not look like a natural finish. If it landed while an
        episode happened to be past the played threshold, _is_natural_finish
        would see a stop right after playing near the end and _advance_queue
        would start the *next* episode — waking the owner with more audio,
        which is precisely inverted. Releasing the episode before stopping the
        player is what makes that structurally impossible, exactly as it
        already does for a user-initiated Back.

        The screen is deliberately not navigated away from: e-ink holds its
        last frame with no power, so a stopped player is fine to wake up to.
        """
        timer = self._sleep_timer
        if timer is None or not is_expired(timer, time.monotonic()):
            return
        self._sleep_timer = None
        logger.info("Sleep timer expired, stopping playback")
        self._release_playing_episode()
        self._playing_station = None
        self._abandon_track_fetch()
        self._player_command(self._player.stop, "stop at sleep timer")

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

    def _release_playing_episode(self) -> None:
        """Save the position and stop tracking the current episode.

        Clearing _playing_episode before the player is stopped is what keeps a
        user-initiated stop from looking like a natural finish.
        """
        if self._playing_episode is None:
            return
        state = self._read_player_state()
        if state is not None:
            self._persist_position_now(state)
        self._playing_episode = None
        self._last_playback_state = None

    def _start_station(self, station: Station) -> None:
        """Tune in to a live stream.

        Any episode is released first: it would otherwise keep being polled,
        and its saved position overwritten from the radio stream's elapsed time.
        """
        self._release_playing_episode()
        self._abandon_track_fetch()
        self._playing_station = station
        self._radio_playing_screen = RadioPlayingScreen(
            station, self._player, self._sleep_minutes_remaining, self._read_current_track
        )
        self._player_command(lambda: self._player.play(station.stream_url), "play station")

    def _start_episode(self, episode: Episode) -> None:
        """Begin playback and build the Now Playing screen.

        Feed name comes from the repository, not _selected_feed — playback can
        start from the queue, where no feed is selected.
        """
        feed = self._feed_repository.get_by_id(episode.feed_id)
        feed_name = feed.name if feed is not None else ""
        self._playing_station = None
        self._abandon_track_fetch()
        self._playing_episode = episode
        self._last_playback_state = None
        self._now_playing_screen = NowPlayingScreen(
            episode, feed_name, self._player, self._sleep_minutes_remaining
        )
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

    def _bluetooth_command(self, command: Callable[[], None], description: str) -> bool:
        """Run a bluetooth command. Returns False if it failed (pairing branches on it)."""
        try:
            command()
        except Exception:
            # Bluetooth exception types live above this layer (see layer hierarchy);
            # a bluetooth failure must degrade to a log line, not kill the UI loop.
            logger.exception("Bluetooth command failed: %s", description)
            return False
        return True

    def _rebuild_bluetooth_screen(self, status_message: str | None = None) -> None:
        """Re-query paired devices; a fetch failure shows as an on-screen error."""
        scroll_offset = self._bluetooth_screen.scroll_offset if self._bluetooth_screen else 0
        devices: Sequence[BluetoothDevice] | None
        try:
            devices = self._bluetooth.list_paired_devices()
        except Exception:
            # Bluetooth exception types live above this layer (see layer hierarchy).
            logger.exception("Could not list paired Bluetooth devices")
            devices = None
        self._bluetooth_screen = BluetoothScreen(
            devices,
            scroll_offset,
            status_message=status_message,
            is_status_error=status_message is not None,
        )

    def _rebuild_discover_screen(
        self, devices: Sequence[BluetoothDevice] | None, is_scanning: bool = False
    ) -> None:
        scroll_offset = self._discover_screen.scroll_offset if self._discover_screen else 0
        self._discover_screen = BluetoothDiscoverScreen(devices, scroll_offset, is_scanning)

    def _start_scan(self) -> None:
        """Kick off a background device scan and show the scanning frame.

        Deliberately does not draw: handle_touch redraws right after this,
        by which point _state has moved to BLUETOOTH_DISCOVER.
        """
        if self._scan_in_progress:
            logger.info("Ignoring scan request: a scan is already running")
            return

        self._scan_in_progress = True
        self._rebuild_discover_screen(None, is_scanning=True)
        generation = self._scan_generation
        # Daemon so Ctrl-C never waits out a 15s scan on shutdown.
        threading.Thread(
            target=self._run_scan, args=(generation,), name="bluetooth-scan", daemon=True
        ).start()

    def _run_scan(self, generation: int) -> None:
        """Scan worker. Runs off the UI thread — must not draw or touch the DB."""
        devices: Sequence[BluetoothDevice] | None
        try:
            devices = self._bluetooth.scan_for_devices()
        except Exception:
            # Bluetooth exception types live above this layer (see layer
            # hierarchy); None renders as the on-screen unreachable state.
            logger.exception("Bluetooth scan failed")
            devices = None
        self._scan_results.put((generation, devices))

    def poll_background_work(self) -> None:
        """Collect finished background work. Called every tick from the main loop."""
        self._poll_scan_result()
        self._poll_status_result()
        self._poll_track_result()

    def _poll_scan_result(self) -> None:
        try:
            generation, devices = self._scan_results.get_nowait()
        except queue.Empty:
            return

        self._scan_in_progress = False
        if generation != self._scan_generation:
            logger.info("Discarding stale Bluetooth scan result")
            return
        self._rebuild_discover_screen(devices)
        if self._state is AppState.BLUETOOTH_DISCOVER:
            self._show(full_refresh=False)

    def _poll_status_result(self) -> None:
        try:
            generation, status = self._status_results.get_nowait()
        except queue.Empty:
            return

        self._status_check_in_progress = False
        if generation != self._status_generation:
            logger.info("Discarding stale network status result")
            return
        self._wifi_screen = WifiScreen(status)
        if self._state is AppState.WIFI:
            self._show(full_refresh=False)

    def _poll_track_result(self) -> None:
        try:
            generation, track = self._track_results.get_nowait()
        except queue.Empty:
            return

        self._track_fetch_in_progress = False
        if generation != self._track_generation:
            logger.debug("Discarding stale radio metadata")
            return
        changed = _track_identity(track) != _track_identity(self._current_track)
        self._current_track = track
        # Only redraw when the track actually changed. The poll runs every
        # RADIO_METADATA_POLL_SEC but a track lasts minutes, so redrawing on
        # every result would flash the panel for nothing.
        if changed and self._state is AppState.RADIO_PLAYING:
            self._show(full_refresh=False)

    def _refresh_track_metadata(self) -> None:
        """Start a metadata fetch if one is due. Called from refresh_playback."""
        if self._state is not AppState.RADIO_PLAYING or self._playing_station is None:
            return
        if self._track_fetch_in_progress:
            return
        now = time.monotonic()
        if now - self._last_track_fetch < RADIO_METADATA_POLL_SEC:
            return
        self._last_track_fetch = now
        self._track_fetch_in_progress = True
        station_id = self._playing_station.metadata_id
        generation = self._track_generation
        # Daemon so Ctrl-C never waits out an HTTP timeout.
        threading.Thread(
            target=self._run_track_fetch,
            args=(generation, station_id),
            name="radio-metadata",
            daemon=True,
        ).start()

    def _run_track_fetch(self, generation: int, station_id: int) -> None:
        """Metadata worker. Runs off the UI thread — must not draw or touch the DB."""
        track: TrackMetadata | None
        try:
            track = self._radio_metadata.get_current_track(station_id)
        except Exception:
            # Radio exception types live above this layer (see layer hierarchy).
            # None renders as the station-name layout, which is also what an
            # offline box shows — there is nothing to say about the track.
            logger.debug("Could not read live radio metadata", exc_info=True)
            track = None
        self._track_results.put((generation, track))

    def _abandon_track_fetch(self) -> None:
        """Drop the current track and any in-flight fetch of it.

        Called when the station changes or the player is left, so a late
        result can never label one station's stream with another's track.
        """
        self._track_generation += 1
        self._track_fetch_in_progress = False
        self._current_track = None
        self._last_track_fetch = 0.0

    def _start_status_check(self) -> None:
        """Read the network status in the background and show the waiting frame.

        Deliberately does not draw: handle_touch redraws right after this, by
        which point _state has moved to WIFI.
        """
        self._wifi_screen = WifiScreen(None, status_message=copy.WIFI_CHECKING)
        if self._status_check_in_progress:
            logger.info("Ignoring status check: one is already running")
            return

        self._status_check_in_progress = True
        generation = self._status_generation
        # Daemon so Ctrl-C never waits out an nmcli timeout.
        threading.Thread(
            target=self._run_status_check, args=(generation,), name="wifi-status", daemon=True
        ).start()

    def _run_status_check(self, generation: int) -> None:
        """Status worker. Runs off the UI thread — must not draw or touch the DB."""
        status: NetworkStatus | None
        try:
            status = self._network.get_status()
        except Exception:
            # Network exception types live above this layer (see layer
            # hierarchy); None renders as the on-screen unreachable state,
            # which is also what Windows shows — there is no nmcli there.
            logger.exception("Could not read network status")
            status = None
        self._status_results.put((generation, status))

    def _start_hotspot(self) -> None:
        """Raise the setup hotspot, then show how to join it.

        Blocking on purpose, like pairing: it takes seconds, it drops the
        network the box is on, and a tap landing on something else halfway
        through would be worse than a frozen screen. A status frame goes up
        first and buffered taps are drained afterwards.
        """
        self._show_wifi_status(copy.WIFI_HOTSPOT_STARTING)
        credentials: HotspotCredentials | None
        try:
            credentials = self._network.start_setup_hotspot()
        except Exception:
            # Network exception types live above this layer (see layer
            # hierarchy). WifiSetupScreen renders the failure itself, which is
            # what keeps the outcome out of the pure transition function.
            logger.exception("Could not start the setup hotspot")
            credentials = None

        self._wifi_setup_screen = WifiSetupScreen(credentials)
        self._drain_touches()

    def _show_wifi_status(self, message: str) -> None:
        """Draw a transient frame on the Wi-Fi screen before a blocking call.

        Drawn directly rather than through _show(): the hotspot raise leaves
        _state on WIFI while the screen it is heading to is WIFI_SETUP.
        """
        screen = WifiScreen(None, status_message=message)
        self._wifi_screen = screen
        self._show_screen(screen, full_refresh=False)

    def _abandon_status_check(self) -> None:
        """Drop an in-flight status check, so its result can't redraw a screen
        the user has already left."""
        if self._status_check_in_progress:
            self._status_generation += 1
            self._status_check_in_progress = False

    def _abandon_scan(self) -> None:
        """Stop caring about an in-flight scan. The worker still finishes; its
        result is dropped by the generation check in poll_background_work."""
        if self._scan_in_progress:
            self._scan_generation += 1
            self._scan_in_progress = False

    def _pair_device(self, device: BluetoothDevice) -> None:
        """Pair, then connect. Both block, so a status frame goes up first."""
        self._show_bluetooth_status(copy.BLUETOOTH_PAIRING.format(name=device.name))
        paired = self._bluetooth_command(
            lambda: self._bluetooth.pair_device(device.mac), "pair device"
        )
        if not paired:
            self._rebuild_bluetooth_screen(
                status_message=copy.BLUETOOTH_PAIRING_FAILED.format(name=device.name)
            )
            self._drain_touches()
            return

        self._show_bluetooth_status(copy.BLUETOOTH_CONNECTING.format(name=device.name))
        self._bluetooth_command(
            lambda: self._bluetooth.activate_device(device.mac), "activate device"
        )
        self._rebuild_bluetooth_screen()
        self._drain_touches()

    def _show_bluetooth_connecting(self, device: BluetoothDevice) -> None:
        """Flash a 'Connecting…' frame before the blocking activate_device call."""
        self._show_bluetooth_status(copy.BLUETOOTH_CONNECTING.format(name=device.name))

    def _show_bluetooth_status(self, message: str) -> None:
        scroll_offset = self._bluetooth_screen.scroll_offset if self._bluetooth_screen else 0
        screen = BluetoothScreen(None, scroll_offset, status_message=message)
        self._bluetooth_screen = screen
        # Drawn directly: pairing arrives here from BLUETOOTH_DISCOVER, so
        # _current_screen() would still return the discover screen.
        self._show_screen(screen, full_refresh=False)

    def _drain_touches(self) -> None:
        """Discard taps buffered during a multi-second blocking bluetooth call.

        Without this they replay against whatever screen comes up next.
        """
        self._driver.read_touch()
        self._last_touch_time = time.monotonic()

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
            case AppState.BLUETOOTH_DISCOVER:
                if self._discover_screen is None:
                    raise DisplayError("BLUETOOTH_DISCOVER state reached without a screen")
                return self._discover_screen
            case AppState.WIFI:
                if self._wifi_screen is None:
                    raise DisplayError("WIFI state reached without a wifi screen")
                return self._wifi_screen
            case AppState.WIFI_SETUP:
                if self._wifi_setup_screen is None:
                    raise DisplayError("WIFI_SETUP state reached without a setup screen")
                return self._wifi_setup_screen
            case AppState.RADIO_LIST:
                return self._radio_screen
            case AppState.RADIO_PLAYING:
                if self._radio_playing_screen is None:
                    raise DisplayError("RADIO_PLAYING state reached without a radio screen")
                return self._radio_playing_screen
            case AppState.SLEEP_TIMER:
                if self._sleep_timer_screen is None:
                    raise DisplayError("SLEEP_TIMER state reached without a duration screen")
                return self._sleep_timer_screen

    def _show(self, full_refresh: bool) -> None:
        self._show_screen(self._current_screen(), full_refresh)

    def _show_screen(self, screen: Screen, full_refresh: bool) -> None:
        """Render a specific screen.

        Taken directly (rather than via _current_screen) by the modal status
        frames, which must draw the screen the transition is heading *to* while
        _state still points at the one being left.
        """
        image = screen.render()
        if full_refresh:
            self._transitions_since_full_refresh += 1
            if self._transitions_since_full_refresh > _TRANSITIONS_BETWEEN_FULL_REFRESHES:
                self._transitions_since_full_refresh = 0
                self._driver.display(image)
                return
        self._driver.display_partial(image)
