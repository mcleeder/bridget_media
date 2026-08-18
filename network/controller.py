from __future__ import annotations

import logging
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from network.hotspot import HotspotCredentials, ensure_credentials, load_credentials

logger = logging.getLogger(__name__)

_NMCLI: Final[str] = "nmcli"

_STATUS_TIMEOUT_SEC: Final[float] = 10.0
_SCAN_TIMEOUT_SEC: Final[float] = 45.0
_JOIN_TIMEOUT_SEC: Final[float] = 60.0
_FORGET_TIMEOUT_SEC: Final[float] = 10.0
_HOTSPOT_TIMEOUT_SEC: Final[float] = 30.0

# NetworkManager's own words. "full" is the only one that means the internet is
# actually reachable — "limited" and "portal" are an associated Wi-Fi link with
# no working route, which the status screen reports differently.
_CONNECTIVITY_FULL: Final[str] = "full"

_WIFI_DEVICE_TYPE: Final[str] = "wifi"
_WIFI_CONNECTION_TYPE: Final[str] = "802-11-wireless"
_DEVICE_STATE_CONNECTED: Final[str] = "connected"

_SSID_PROPERTY: Final[str] = "802-11-wireless.ssid"
_MODE_PROPERTY: Final[str] = "802-11-wireless.mode"
_AP_MODE: Final[str] = "ap"

# The profile the hotspot is created under, so raising and dropping it always
# name the same connection rather than whatever NetworkManager would pick.
HOTSPOT_CONNECTION_NAME: Final[str] = "bridget-hotspot"

# nmcli prints "--" for an empty column in terse mode.
_TERSE_EMPTY: Final[str] = "--"

_REDACTED: Final[str] = "***"


class NetworkError(Exception):
    pass


@dataclass(frozen=True)
class NetworkStatus:
    is_online: bool
    ssid: str | None
    ip_address: str | None
    is_hotspot_active: bool


@dataclass(frozen=True)
class WifiNetwork:
    ssid: str
    signal: int
    is_secured: bool
    is_known: bool


def _split_terse(line: str) -> list[str]:
    r"""Split one `nmcli -t` line into fields.

    Terse output is colon-separated with `\:` and `\\` escapes, so an SSID
    containing a colon survives — a naive str.split(":") would tear it in half.
    """
    fields: list[str] = []
    current: list[str] = []
    is_escaped = False
    for character in line:
        if is_escaped:
            current.append(character)
            is_escaped = False
        elif character == "\\":
            is_escaped = True
        elif character == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    fields.append("".join(current))
    return fields


def _field(fields: Sequence[str], index: int) -> str:
    return fields[index].strip() if index < len(fields) else ""


def _parse_property_lines(output: str) -> dict[str, str]:
    """Parse `nmcli -t -f <props> connection show <name>` into {property: value}."""
    properties: dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        fields = _split_terse(line)
        if len(fields) >= 2:
            properties[fields[0].strip()] = ":".join(fields[1:]).strip()
    return properties


def _parse_first_ip4_address(output: str) -> str | None:
    """First address from `nmcli -t -f IP4.ADDRESS device show`, sans prefix.

    Lines look like `IP4.ADDRESS[1]:192.168.1.50/24`.
    """
    for line in output.splitlines():
        fields = _split_terse(line)
        value = _field(fields, 1)
        if value and value != _TERSE_EMPTY:
            return value.split("/", 1)[0]
    return None


def _parse_signal(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


def _parse_networks(output: str, known_ssids: frozenset[str]) -> list[WifiNetwork]:
    """Parse `nmcli -t -f SSID,SIGNAL,SECURITY device wifi list`.

    Hidden networks come back with an empty SSID and are dropped — there is
    nothing to show or tap, and reaching one needs the SSID typed in by hand.
    Duplicate SSIDs (one router on 2.4 and 5GHz) collapse to the strongest
    sighting, so the list doesn't read as two different networks.
    """
    strongest: dict[str, WifiNetwork] = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        fields = _split_terse(line)
        ssid = _field(fields, 0)
        if not ssid or ssid == _TERSE_EMPTY:
            continue
        security = _field(fields, 2)
        network = WifiNetwork(
            ssid=ssid,
            signal=_parse_signal(_field(fields, 1)),
            is_secured=bool(security) and security != _TERSE_EMPTY,
            is_known=ssid in known_ssids,
        )
        previous = strongest.get(ssid)
        if previous is None or network.signal > previous.signal:
            strongest[ssid] = network
    return sorted(strongest.values(), key=lambda network: network.signal, reverse=True)


def _redact(text: str, secrets: Sequence[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, _REDACTED)
    return text


class NetworkController:
    """Reads and changes Wi-Fi state through nmcli.

    A peer of bluetooth/controller.py: it shells out and knows nothing above
    it, so both entry points may use it. Read commands run unprivileged;
    anything that changes configuration goes through the passwordless sudo
    allowlist installed by deploy/setup_pi.sh, because NetworkManager needs
    root for it.
    """

    def __init__(self, hotspot_credentials_path: str) -> None:
        self._hotspot_credentials_path = hotspot_credentials_path

    def start_setup_hotspot(self) -> HotspotCredentials:
        """Raise the setup hotspot, generating credentials if this is the first time.

        Credential handling lives here rather than in the caller so the
        display layer never has to know where they are stored — it asks the
        network for a way in and gets back something it can draw.

        For callers running as the app user (the panel, the web app) only:
        see start_saved_hotspot for why root uses a different door.
        """
        credentials = ensure_credentials(self._hotspot_credentials_path)
        self.start_hotspot(credentials.ssid, credentials.password)
        return credentials

    def start_saved_hotspot(self) -> HotspotCredentials:
        """Raise the setup hotspot using credentials that already exist.

        The watchdog runs as root, and a credentials file *created* by root is
        unreadable by the app user that has to draw the QR — which would leave
        a hotspot up that the panel cannot describe. So this path never
        generates: a missing file means provisioning was skipped, and saying
        so loudly is the correct outcome.
        """
        credentials = load_credentials(self._hotspot_credentials_path)
        self.start_hotspot(credentials.ssid, credentials.password)
        return credentials

    def get_status(self) -> NetworkStatus:
        connectivity = self._run(
            ["-t", "-f", "CONNECTIVITY", "general", "status"], _STATUS_TIMEOUT_SEC
        ).strip()
        device, connection_name = self._active_wifi_connection()

        ssid: str | None = None
        is_hotspot_active = False
        if connection_name is not None:
            properties = _parse_property_lines(
                self._run(
                    [
                        "-t",
                        "-f",
                        f"{_SSID_PROPERTY},{_MODE_PROPERTY}",
                        "connection",
                        "show",
                        connection_name,
                    ],
                    _STATUS_TIMEOUT_SEC,
                )
            )
            # The profile name is usually the SSID, but not for a hotspot and
            # not for a profile someone renamed — ask for the SSID itself.
            ssid = properties.get(_SSID_PROPERTY) or connection_name
            is_hotspot_active = properties.get(_MODE_PROPERTY, "").lower() == _AP_MODE

        ip_address = None
        if device is not None:
            ip_address = _parse_first_ip4_address(
                self._run(
                    ["-t", "-f", "IP4.ADDRESS", "device", "show", device], _STATUS_TIMEOUT_SEC
                )
            )

        return NetworkStatus(
            is_online=connectivity == _CONNECTIVITY_FULL,
            ssid=ssid,
            ip_address=ip_address,
            is_hotspot_active=is_hotspot_active,
        )

    def scan_networks(self) -> list[WifiNetwork]:
        """List nearby networks, strongest first.

        Blocks for several seconds while NetworkManager rescans — callers run
        it off the UI thread, like the Bluetooth scan.

        Privileged because `--rescan yes` is *silently ignored* without root:
        nmcli exits 0 and returns whatever was already cached, which on this
        device was two rows (both bands of the network it was already on)
        against twelve for the same command under sudo. Read as an unprivileged
        call it looks like a working scan that finds nothing worth joining —
        exactly wrong in the house where the box has never been online.
        """
        known = self._known_ssids()
        output = self._run(
            ["-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes"],
            _SCAN_TIMEOUT_SEC,
            is_privileged=True,
        )
        networks = _parse_networks(output, known)
        logger.info("Wi-Fi scan found %d network(s)", len(networks))
        return networks

    def join_network(self, ssid: str, password: str, is_hidden: bool = False) -> None:
        """Associate with a network. A hidden one has to be named explicitly.

        WPA3 support depends on the Pi 3B+'s wpa_supplicant, which is patchy —
        nmcli's own failure is surfaced rather than a generic message.
        """
        args = ["device", "wifi", "connect", ssid]
        if password:
            args += ["password", password]
        if is_hidden:
            args += ["hidden", "yes"]
        self._run(args, _JOIN_TIMEOUT_SEC, secrets=(password,), is_privileged=True)
        logger.info("Joined Wi-Fi network %s", ssid)

    def forget_network(self, ssid: str) -> None:
        self._run(["connection", "delete", "id", ssid], _FORGET_TIMEOUT_SEC, is_privileged=True)
        logger.info("Forgot Wi-Fi network %s", ssid)

    def start_hotspot(self, ssid: str, password: str) -> None:
        self._run(
            [
                "device",
                "wifi",
                "hotspot",
                "con-name",
                HOTSPOT_CONNECTION_NAME,
                "ssid",
                ssid,
                "password",
                password,
            ],
            _HOTSPOT_TIMEOUT_SEC,
            secrets=(password,),
            is_privileged=True,
        )
        logger.info("Hotspot %s is up", ssid)

    def stop_hotspot(self) -> None:
        self._run(
            ["connection", "down", "id", HOTSPOT_CONNECTION_NAME],
            _HOTSPOT_TIMEOUT_SEC,
            is_privileged=True,
        )
        logger.info("Hotspot stopped")

    def reconnect_saved_network(self) -> None:
        """Put the Wi-Fi radio back on a saved network after the AP comes down.

        NetworkManager usually autoconnects on its own, but "usually" is doing
        real work there: the AP profile owns the radio until it is released,
        and a box that drops its hotspot without rejoining anything is exactly
        the brick this whole phase exists to prevent. Asking explicitly costs
        one command and removes the ambiguity.
        """
        device, _ = self._active_wifi_connection()
        if device is None:
            logger.warning("No Wi-Fi device to reconnect")
            return
        self._run(["device", "connect", device], _JOIN_TIMEOUT_SEC, is_privileged=True)
        logger.info("Reconnected %s to a saved network", device)

    def _active_wifi_connection(self) -> tuple[str | None, str | None]:
        """(device, active connection name) for the first Wi-Fi interface."""
        output = self._run(
            ["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"], _STATUS_TIMEOUT_SEC
        )
        for line in output.splitlines():
            fields = _split_terse(line)
            if _field(fields, 1) != _WIFI_DEVICE_TYPE:
                continue
            device = _field(fields, 0)
            if _field(fields, 2) != _DEVICE_STATE_CONNECTED:
                return device, None
            return device, _field(fields, 3) or None
        return None, None

    def _known_ssids(self) -> frozenset[str]:
        """SSIDs there is already a saved profile for.

        Approximated by the profile name: NetworkManager names a Wi-Fi profile
        after its SSID unless someone renames it by hand, and reading the real
        SSID out of every profile would cost one nmcli call per saved network.
        """
        output = self._run(["-t", "-f", "NAME,TYPE", "connection", "show"], _STATUS_TIMEOUT_SEC)
        return frozenset(
            _field(fields, 0)
            for fields in (_split_terse(line) for line in output.splitlines() if line.strip())
            if _field(fields, 1) == _WIFI_CONNECTION_TYPE and _field(fields, 0)
        )

    def _run(
        self,
        args: Sequence[str],
        timeout: float,
        secrets: Sequence[str] = (),
        is_privileged: bool = False,
    ) -> str:
        command = ["sudo", "-n", _NMCLI, *args] if is_privileged else [_NMCLI, *args]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=True,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            failure: Exception = exc
        else:
            return result.stdout

        # This message reaches both the journal and, through feed_manager, an
        # HTTP response — and a wrong password is the likeliest failure in the
        # whole join flow, so the secret never goes into it. (argv is still
        # visible in `ps` while the call runs — accepted on a single-user box;
        # see the Key Note in CLAUDE.md.)
        error = NetworkError(f"nmcli {_redact(' '.join(args), secrets)} failed")
        if not secrets:
            # Nothing sensitive in argv, so the raw nmcli exception is worth
            # keeping — it is what makes an unexpected failure debuggable.
            error.__cause__ = failure
        # Raised outside the except block on purpose. Inside it, Python would
        # attach the original exception to __context__ whatever `raise from`
        # says, and CalledProcessError/TimeoutExpired both carry the full argv
        # — password included — in their own repr.
        raise error
