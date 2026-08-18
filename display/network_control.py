from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class NetworkStatus(Protocol):
    """What the display knows about the network.

    Structurally matched by network.controller.NetworkStatus — defined here so
    the display layer never imports the network layer (see layer hierarchy in
    CLAUDE.md).
    """

    @property
    def is_online(self) -> bool: ...

    @property
    def ssid(self) -> str | None: ...

    @property
    def ip_address(self) -> str | None: ...

    @property
    def is_hotspot_active(self) -> bool: ...


class WifiNetwork(Protocol):
    """A network seen by a scan."""

    @property
    def ssid(self) -> str: ...

    @property
    def signal(self) -> int: ...

    @property
    def is_secured(self) -> bool: ...

    @property
    def is_known(self) -> bool: ...


class HotspotCredentials(Protocol):
    """What a phone needs to join the setup hotspot."""

    @property
    def ssid(self) -> str: ...

    @property
    def password(self) -> str: ...


class NetworkService(Protocol):
    """Network operations the display layer may issue.

    Structurally matched by network.controller.NetworkController; main.py
    injects it. Returns Sequence rather than list for the same invariance
    reason as BluetoothService in display/bluetooth_control.py.

    Nearly read-only: the panel reports the network and can raise the setup
    hotspot, but *joining* one stays with the feed manager. That split is
    deliberate — the panel has no keyboard, and the recovery path it does own
    (hand out a hotspot) is the one that works when everything else is wrong.
    """

    def get_status(self) -> NetworkStatus: ...
    def scan_networks(self) -> Sequence[WifiNetwork]: ...
    def start_setup_hotspot(self) -> HotspotCredentials: ...
