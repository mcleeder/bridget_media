from __future__ import annotations

from enum import Enum, auto

from display.events import (
    BackRequested,
    EpisodeSelected,
    Event,
    FeedSelected,
    HomeMenuItem,
    HomeMenuSelected,
)


class AppState(Enum):
    HOME = auto()
    PODCAST_LIST = auto()
    EPISODE_LIST = auto()
    NOW_PLAYING = auto()
    QUEUE = auto()
    BLUETOOTH = auto()


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
        case AppState.BLUETOOTH, BackRequested():
            return AppState.HOME
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
