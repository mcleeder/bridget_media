from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from db.models import Episode, Feed


@dataclass(frozen=True)
class FeedSelected:
    feed: Feed


@dataclass(frozen=True)
class EpisodeSelected:
    episode: Episode


@dataclass(frozen=True)
class BackRequested:
    pass


@dataclass(frozen=True)
class ListScrolled:
    pass


@dataclass(frozen=True)
class PlayPauseToggled:
    pass


@dataclass(frozen=True)
class SkipRequested:
    seconds: float


Event: TypeAlias = (
    FeedSelected | EpisodeSelected | BackRequested | ListScrolled | PlayPauseToggled | SkipRequested
)
