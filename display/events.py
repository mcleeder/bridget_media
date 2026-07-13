from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TypeAlias

from db.models import Episode, Feed
from display.bluetooth_control import BluetoothDevice


class HomeMenuItem(Enum):
    BLUETOOTH = auto()
    PODCASTS = auto()
    QUEUE = auto()


@dataclass(frozen=True)
class HomeMenuSelected:
    item: HomeMenuItem


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


@dataclass(frozen=True)
class QueueToggled:
    episode: Episode


@dataclass(frozen=True)
class QueueRemoveRequested:
    episode: Episode


@dataclass(frozen=True)
class BluetoothDeviceSelected:
    device: BluetoothDevice


Event: TypeAlias = (
    HomeMenuSelected
    | FeedSelected
    | EpisodeSelected
    | BackRequested
    | ListScrolled
    | PlayPauseToggled
    | SkipRequested
    | QueueToggled
    | QueueRemoveRequested
    | BluetoothDeviceSelected
)
