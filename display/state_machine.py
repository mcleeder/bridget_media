from __future__ import annotations

from dataclasses import dataclass
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
    SleepDurationSelected,
    SleepTimerRequested,
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
    SLEEP_TIMER = auto()


@dataclass(frozen=True)
class NavigationContext:
    """Where Back returns to, for the states reachable from more than one screen.

    Both are tracked by the caller and passed in, so transition() stays pure.
    Grouping them became worthwhile at the second origin: the next one costs
    a field here instead of another positional argument at every call site.

    Note this is navigation *input*, not an outcome — event outcomes such as
    pairing success still belong in side effects, never in this function.
    """

    now_playing_origin: AppState
    sleep_timer_origin: AppState


def transition(state: AppState, event: Event, context: NavigationContext) -> AppState:
    """Pure state-transition function: everything else about an event is a side effect.

    NOW_PLAYING and SLEEP_TIMER are each reachable from more than one screen,
    so Back from them returns to the matching origin in `context`.
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
            return context.now_playing_origin
        # Reachable from either player, because the moment anyone wants a
        # sleep timer is while the thing they are falling asleep to is playing.
        case (AppState.NOW_PLAYING | AppState.RADIO_PLAYING), SleepTimerRequested():
            return AppState.SLEEP_TIMER
        # Picking a duration returns to the player, so the badge showing the
        # new value is the confirmation. Same for cancelling and for Back.
        case AppState.SLEEP_TIMER, (SleepDurationSelected() | BackRequested()):
            return context.sleep_timer_origin
        case _:
            return state
