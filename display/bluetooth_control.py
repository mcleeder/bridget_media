from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class BluetoothDevice(Protocol):
    """A paired Bluetooth device.

    Structurally matched by bluetooth.controller.BluetoothDevice — defined here
    so the display layer never imports the bluetooth layer (see layer hierarchy
    in CLAUDE.md).
    """

    @property
    def mac(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def is_connected(self) -> bool: ...


class BluetoothService(Protocol):
    """Bluetooth commands the display layer may issue.

    Structurally matched by bluetooth.controller.BluetoothController; main.py
    injects it. Returns Sequence rather than list — list is invariant, so a
    concrete list[bluetooth.controller.BluetoothDevice] wouldn't satisfy a
    method typed to return list[BluetoothDevice] under mypy --strict.
    """

    def list_paired_devices(self) -> Sequence[BluetoothDevice]: ...
    def activate_device(self, mac: str) -> None: ...
    def disconnect_device(self, mac: str) -> None: ...
