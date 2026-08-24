from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TypeAlias

from config import Station
from db.models import Episode, Feed
from display.bluetooth_control import BluetoothDevice


class HomeMenuItem(Enum):
    BLUETOOTH = auto()
    PODCASTS = auto()
    QUEUE = auto()
    RADIO = auto()
    WIFI = auto()


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
class StationSelected:
    station: Station


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


@dataclass(frozen=True)
class BluetoothScanRequested:
    pass


@dataclass(frozen=True)
class HotspotRequested:
    """Raise the setup hotspot on demand, from the panel.

    The recovery path when the automatic watchdog misjudges, or when the
    router changed and waiting out a failure timeout is the wrong
    experience.
    """

    pass


@dataclass(frozen=True)
class SleepTimerRequested:
    """Open the duration screen from whichever player is on screen."""

    pass


@dataclass(frozen=True)
class SleepDurationSelected:
    """A duration in minutes, or None to cancel an armed timer.

    Cancelling is the selected duration being tapped again rather than a
    separate Off control: the active cell is drawn inverted, so tapping it
    to switch it back off needs no explaining.
    """

    minutes: int | None


@dataclass(frozen=True)
class BluetoothPairRequested:
    device: BluetoothDevice


@dataclass(frozen=True)
class BluetoothForgetRequested:
    device: BluetoothDevice


Event: TypeAlias = (
    HomeMenuSelected
    | FeedSelected
    | EpisodeSelected
    | StationSelected
    | BackRequested
    | ListScrolled
    | PlayPauseToggled
    | SkipRequested
    | QueueToggled
    | QueueRemoveRequested
    | BluetoothDeviceSelected
    | BluetoothScanRequested
    | HotspotRequested
    | SleepTimerRequested
    | SleepDurationSelected
    | BluetoothPairRequested
    | BluetoothForgetRequested
)
