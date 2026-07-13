from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Final

logger = logging.getLogger(__name__)

_BLUETOOTHCTL: Final[str] = "bluetoothctl"
_CONFIGURE_SPEAKER_PATH: Final[str] = "/usr/local/bin/configure-speaker"

_LIST_TIMEOUT_SEC: Final[float] = 10.0
_INFO_TIMEOUT_SEC: Final[float] = 5.0
_CONNECT_TIMEOUT_SEC: Final[float] = 20.0
_DISCONNECT_TIMEOUT_SEC: Final[float] = 10.0
_CONFIGURE_SPEAKER_TIMEOUT_SEC: Final[float] = 15.0

_DEVICE_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^Device (?P<mac>([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}) (?P<name>.+)$"
)


class BluetoothError(Exception):
    pass


@dataclass(frozen=True)
class BluetoothDevice:
    mac: str
    name: str
    is_connected: bool


class BluetoothController:
    def list_paired_devices(self) -> list[BluetoothDevice]:
        output = self._run(["devices", "Paired"], _LIST_TIMEOUT_SEC)
        if not output.strip():
            # Older bluetoothctl versions use this subcommand name instead.
            output = self._run(["paired-devices"], _LIST_TIMEOUT_SEC)

        devices = []
        for line in output.splitlines():
            match = _DEVICE_LINE_RE.match(line.strip())
            if match is None:
                continue
            mac = match.group("mac")
            devices.append(
                BluetoothDevice(
                    mac=mac, name=match.group("name"), is_connected=self._is_connected(mac)
                )
            )
        return devices

    def activate_device(self, mac: str) -> None:
        self._run(["connect", mac], _CONNECT_TIMEOUT_SEC)
        try:
            subprocess.run(
                ["sudo", "-n", _CONFIGURE_SPEAKER_PATH, mac],
                capture_output=True,
                text=True,
                timeout=_CONFIGURE_SPEAKER_TIMEOUT_SEC,
                check=True,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise BluetoothError(f"Could not configure speaker for {mac}") from exc
        logger.info("Activated Bluetooth device %s", mac)

    def disconnect_device(self, mac: str) -> None:
        self._run(["disconnect", mac], _DISCONNECT_TIMEOUT_SEC)
        logger.info("Disconnected Bluetooth device %s", mac)

    def _is_connected(self, mac: str) -> bool:
        output = self._run(["info", mac], _INFO_TIMEOUT_SEC)
        return "Connected: yes" in output

    def _run(self, args: list[str], timeout: float) -> str:
        try:
            result = subprocess.run(
                [_BLUETOOTHCTL, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=True,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise BluetoothError(f"bluetoothctl {' '.join(args)} failed") from exc
        return result.stdout
