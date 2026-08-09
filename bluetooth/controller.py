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
_POWER_ON_TIMEOUT_SEC: Final[float] = 10.0
_RFKILL_TIMEOUT_SEC: Final[float] = 5.0
_PAIR_TIMEOUT_SEC: Final[float] = 30.0
_TRUST_TIMEOUT_SEC: Final[float] = 10.0
_REMOVE_TIMEOUT_SEC: Final[float] = 10.0

# How long bluetoothctl discovers for. The subprocess timeout needs headroom on
# top so the process is never killed just as it is printing its results.
_SCAN_DURATION_SEC: Final[int] = 15
_SCAN_TIMEOUT_HEADROOM_SEC: Final[float] = 10.0

_RFKILL_PATH: Final[str] = "/usr/sbin/rfkill"

_DEVICE_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^Device (?P<mac>([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}) (?P<name>.+)$"
)


class BluetoothError(Exception):
    pass


def _parse_device_lines(output: str) -> list[tuple[str, str]]:
    """Extract (mac, name) pairs from `bluetoothctl devices` style output."""
    pairs = []
    for line in output.splitlines():
        match = _DEVICE_LINE_RE.match(line.strip())
        if match is not None:
            pairs.append((match.group("mac"), match.group("name")))
    return pairs


def _is_placeholder_name(mac: str, name: str) -> bool:
    """True when bluetoothctl fell back to the MAC as the device name.

    Unidentified devices are listed as `AA-BB-CC-DD-EE-FF`. Without this filter a
    scan is mostly stray BLE beacons with unreadable names.
    """
    return name.strip().upper() == mac.replace(":", "-").upper()


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

        return [
            BluetoothDevice(mac=mac, name=name, is_connected=self._is_connected(mac))
            for mac, name in _parse_device_lines(output)
        ]

    def scan_for_devices(self) -> list[BluetoothDevice]:
        """Discover nearby devices that are not paired yet.

        Blocks for roughly _SCAN_DURATION_SEC — callers run it off the UI thread.
        """
        self._power_on()
        self._run(
            ["--timeout", str(_SCAN_DURATION_SEC), "scan", "on"],
            _SCAN_DURATION_SEC + _SCAN_TIMEOUT_HEADROOM_SEC,
        )

        paired_macs = {device.mac for device in self.list_paired_devices()}
        output = self._run(["devices"], _LIST_TIMEOUT_SEC)
        discovered = [
            BluetoothDevice(mac=mac, name=name, is_connected=False)
            for mac, name in _parse_device_lines(output)
            if mac not in paired_macs and not _is_placeholder_name(mac, name)
        ]
        logger.info("Bluetooth scan found %d unpaired device(s)", len(discovered))
        return discovered

    def pair_device(self, mac: str) -> None:
        """Pair and trust a device. Connecting is a separate step (activate_device).

        Only "Just Works" pairing is supported: bluetoothctl runs non-interactively
        here, so a device demanding a PIN or numeric confirmation fails instead of
        hanging. deploy/pair_speaker.sh is the fallback for those.
        """
        self._run(["pair", mac], _PAIR_TIMEOUT_SEC)
        self._run(["trust", mac], _TRUST_TIMEOUT_SEC)
        logger.info("Paired Bluetooth device %s", mac)

    def forget_device(self, mac: str) -> None:
        self._run(["remove", mac], _REMOVE_TIMEOUT_SEC)
        logger.info("Removed Bluetooth device %s", mac)

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

    def _power_on(self) -> None:
        """Bring the adapter up before scanning.

        The Pi's controller ships rfkill soft-blocked, and `power on` fails while
        it is. Unblocking needs root, so it goes through passwordless sudo; a
        failure here is not fatal (the adapter is already unblocked in the normal
        case) and is left for `power on` to report if it really is down.
        """
        try:
            subprocess.run(
                ["sudo", "-n", _RFKILL_PATH, "unblock", "bluetooth"],
                capture_output=True,
                text=True,
                timeout=_RFKILL_TIMEOUT_SEC,
                check=True,
            )
        except (subprocess.SubprocessError, OSError):
            logger.debug("rfkill unblock failed; assuming already unblocked", exc_info=True)
        self._run(["power", "on"], _POWER_ON_TIMEOUT_SEC)

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
