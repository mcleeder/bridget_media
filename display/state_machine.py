from __future__ import annotations

from enum import Enum, auto

from display.events import BackRequested, EpisodeSelected, Event, FeedSelected


class AppState(Enum):
    PODCAST_LIST = auto()
    EPISODE_LIST = auto()
    NOW_PLAYING = auto()


def transition(state: AppState, event: Event) -> AppState:
    """Pure state-transition function: everything else about an event is a side effect."""
    match state, event:
        case AppState.PODCAST_LIST, FeedSelected():
            return AppState.EPISODE_LIST
        case AppState.EPISODE_LIST, EpisodeSelected():
            return AppState.NOW_PLAYING
        case AppState.EPISODE_LIST, BackRequested():
            return AppState.PODCAST_LIST
        case AppState.NOW_PLAYING, BackRequested():
            return AppState.EPISODE_LIST
        case _:
            return state
