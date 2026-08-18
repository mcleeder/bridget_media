from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
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


def _write_scan_cache(path: str, networks: Sequence[WifiNetwork]) -> None:
    try:
        Path(path).write_text(
            json.dumps([asdict(network) for network in networks]), encoding="utf-8"
        )
    except OSError:
        # A portal with an empty list still has manual SSID entry; failing the
        # hotspot over a cache write would be far worse.
        logger.warning("Could not write the scan cache to %s", path, exc_info=True)


def _read_scan_cache(path: str) -> list[WifiNetwork]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    networks = []
    for entry in raw:
        try:
            networks.append(
                WifiNetwork(
                    ssid=str(entry["ssid"]),
                    signal=int(entry["signal"]),
                    is_secured=bool(entry["is_secured"]),
                    is_known=bool(entry["is_known"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return networks


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

    def __init__(self, hotspot_credentials_path: str, scan_cache_path: str) -> None:
        self._hotspot_credentials_path = hotspot_credentials_path
        self._scan_cache_path = scan_cache_path

    def join_network_from_hotspot(
        self, ssid: str, password: str, is_hidden: bool = False
    ) -> None:
        """Drop the setup AP, then join the target network.

        The Pi has one radio. It cannot host an access point and associate
        with someone's router at the same time, so joining straight from the
        portal fails with "No network with SSID ... found" — the AP owns the
        radio, no scan list exists, and nmcli has nothing to match against.

        If the join then fails the box is left offline with no AP, which
        sounds alarming and is actually the recovery path working: the
        watchdog sees consecutive offline checks and raises the hotspot again
        a few minutes later, so a mistyped password costs a short wait rather
        than a stranded device.
        """
        try:
            self.stop_hotspot()
        except NetworkError:
            # Already down, or never up. Either way the radio is free, which
            # is all this step was for.
            logger.info("No hotspot to drop before joining", exc_info=True)
        self.join_network(ssid, password, is_hidden)

    def start_setup_hotspot(self) -> HotspotCredentials:
        """Raise the setup hotspot, generating credentials if this is the first time.

        Credential handling lives here rather than in the caller so the
        display layer never has to know where they are stored — it asks the
        network for a way in and gets back something it can draw.

        For callers running as the app user (the panel, the web app) only:
        see start_saved_hotspot for why root uses a different door.
        """
        credentials = ensure_credentials(self._hotspot_credentials_path)
        self._cache_scan_then_start(credentials)
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
        self._cache_scan_then_start(credentials)
        return credentials

    def _cache_scan_then_start(self, credentials: HotspotCredentials) -> None:
        """Scan the air *before* taking the radio, then raise the AP.

        One radio means the portal cannot scan while the hotspot is up — the
        whole point of the portal is choosing a network, so the list has to be
        captured in the last moment the radio is free and handed over.
        A failed scan is not worth abandoning the hotspot for: without the AP
        there is no way in at all, so this degrades to an empty list and the
        portal's manual-SSID entry.
        """
        try:
            networks = self.scan_networks()
        except NetworkError:
            logger.warning("Could not scan before raising the hotspot", exc_info=True)
            networks = []
        self.start_hotspot(credentials.ssid, credentials.password)
        _write_scan_cache(self._scan_cache_path, networks)

    def cached_networks(self) -> list[WifiNetwork]:
        """The last scan taken while the radio was free.

        What the portal serves: see _cache_scan_then_start.
        """
        return _read_scan_cache(self._scan_cache_path)

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
        # NetworkManager creates the profile with autoconnect on, which turns a
        # temporary setup AP into the device's permanent identity: it wins the
        # race against the home network on boot, and `device connect` picks it
        # instead of a saved network — so the box answers only to its own
        # hotspot forever and never rejoins anything. Off, always.
        self._run(
            ["connection", "modify", HOTSPOT_CONNECTION_NAME, "connection.autoconnect", "no"],
            _HOTSPOT_TIMEOUT_SEC,
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

        Names the target profile explicitly rather than running `device
        connect`, which picks by autoconnect priority and will happily choose
        the setup hotspot — leaving the box talking to itself. A box that
        drops its AP without rejoining anything is exactly the brick this
        phase exists to prevent, so this is worth being deterministic about.
        """
        candidates = [name for name in self._known_ssids() if name != HOTSPOT_CONNECTION_NAME]
        if not candidates:
            logger.warning("No saved Wi-Fi network to fall back to")
            return
        for name in candidates:
            try:
                self._run(["connection", "up", "id", name], _JOIN_TIMEOUT_SEC, is_privileged=True)
            except NetworkError:
                logger.warning("Could not bring up saved network %s", name, exc_info=True)
                continue
            logger.info("Reconnected to saved network %s", name)
            return
        logger.warning("None of the %d saved networks came up", len(candidates))

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
