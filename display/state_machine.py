from __future__ import annotations

from enum import Enum, auto

from display.events import (
    BackRequested,
    BluetoothPairRequested,
    BluetoothScanRequested,
    EpisodeSelected,
    Event,
    FeedSelected,
    HomeMenuItem,
    HomeMenuSelected,
    HotspotRequested,
    StationSelected,
)


class AppState(Enum):
    HOME = auto()
    PODCAST_LIST = auto()
    EPISODE_LIST = auto()
    NOW_PLAYING = auto()
    QUEUE = auto()
    BLUETOOTH = auto()
    BLUETOOTH_DISCOVER = auto()
    RADIO_LIST = auto()
    RADIO_PLAYING = auto()
    WIFI = auto()
    WIFI_SETUP = auto()


def transition(state: AppState, event: Event, now_playing_origin: AppState) -> AppState:
    """Pure state-transition function: everything else about an event is a side effect.

    NOW_PLAYING is reachable from more than one screen, so Back from it returns
    to now_playing_origin — tracked by the caller, passed in to keep this pure.
    """
    match state, event:
        case AppState.HOME, HomeMenuSelected(item=HomeMenuItem.PODCASTS):
            return AppState.PODCAST_LIST
        case AppState.HOME, HomeMenuSelected(item=HomeMenuItem.QUEUE):
            return AppState.QUEUE
        case AppState.HOME, HomeMenuSelected(item=HomeMenuItem.BLUETOOTH):
            return AppState.BLUETOOTH
        case AppState.HOME, HomeMenuSelected(item=HomeMenuItem.RADIO):
            return AppState.RADIO_LIST
        case AppState.HOME, HomeMenuSelected(item=HomeMenuItem.WIFI):
            return AppState.WIFI
        # Read-only apart from raising the setup hotspot: the panel reports the
        # network and can hand out a way in, but only the web app joins one.
        case AppState.WIFI, BackRequested():
            return AppState.HOME
        case AppState.WIFI, HotspotRequested():
            return AppState.WIFI_SETUP
        case AppState.WIFI_SETUP, BackRequested():
            return AppState.WIFI
        # Radio has its own player state rather than reusing NOW_PLAYING: a live
        # stream has no duration, position or queue, so keeping it separate is
        # what stops the episode machinery (resume, mark-played, auto-advance)
        # from ever running against it. It is only reachable from RADIO_LIST,
        # so Back needs no origin tracking.
        case AppState.RADIO_LIST, StationSelected():
            return AppState.RADIO_PLAYING
        case AppState.RADIO_LIST, BackRequested():
            return AppState.HOME
        case AppState.RADIO_PLAYING, BackRequested():
            return AppState.RADIO_LIST
        case AppState.BLUETOOTH, BackRequested():
            return AppState.HOME
        case AppState.BLUETOOTH, BluetoothScanRequested():
            return AppState.BLUETOOTH_DISCOVER
        case AppState.BLUETOOTH_DISCOVER, BackRequested():
            return AppState.BLUETOOTH
        # Pairing always returns to the paired list: success shows the device
        # there as connected, failure shows a banner the manager sets. Keeping
        # the outcome out of the transition is what keeps this function pure.
        case AppState.BLUETOOTH_DISCOVER, BluetoothPairRequested():
            return AppState.BLUETOOTH
        case AppState.QUEUE, EpisodeSelected():
            return AppState.NOW_PLAYING
        case AppState.QUEUE, BackRequested():
            return AppState.HOME
        case AppState.PODCAST_LIST, FeedSelected():
            return AppState.EPISODE_LIST
        case AppState.PODCAST_LIST, BackRequested():
            return AppState.HOME
        case AppState.EPISODE_LIST, EpisodeSelected():
            return AppState.NOW_PLAYING
        case AppState.EPISODE_LIST, BackRequested():
            return AppState.PODCAST_LIST
        case AppState.NOW_PLAYING, BackRequested():
            return now_playing_origin
        case _:
            return state
