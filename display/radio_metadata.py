"""What the display layer may know about the track on air.

Structurally matched by radio.metadata — defined here so the display layer
never imports the radio layer, exactly as playback.py, bluetooth_control.py
and network_control.py do for theirs.
"""

from __future__ import annotations

from typing import Protocol


class TrackMetadata(Protocol):
    @property
    def title(self) -> str: ...

    @property
    def artist(self) -> str | None: ...

    @property
    def album(self) -> str | None: ...

    @property
    def year(self) -> int | None: ...


class RadioMetadataService(Protocol):
    """Read-only, like the network service: the panel reports what is on air
    and has no way to influence it."""

    def get_current_track(self, station_id: int) -> TrackMetadata | None: ...
