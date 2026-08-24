from __future__ import annotations

from dataclasses import dataclass
from typing import Final

DISPLAY_WIDTH: Final[int] = 296
DISPLAY_HEIGHT: Final[int] = 128
SIMULATOR_SCALE: Final[int] = 3

# The HAT is mounted upside down where the box sits, so the hardware driver
# flips both the rendered frame and the incoming touch coordinates.
# Everything above the driver keeps working in one unrotated 296x128 space.
DISPLAY_ROTATE_180: Final[bool] = True

MPD_HOST: Final[str] = "localhost"
MPD_PORT: Final[int] = 6600

DB_PATH: Final[str] = "pi_media.db"

FEED_REFRESH_INTERVAL_HOURS: Final[int] = 4

# The device answers to <MDNS_HOSTNAME>.local via avahi (set by setup_pi.sh).
# "Open bridget.local" is a sentence a non-engineer can follow; an IP is not.
MDNS_HOSTNAME: Final[str] = "bridget"
FEED_MANAGER_HOST: Final[str] = f"{MDNS_HOSTNAME}.local"

# Port 80 so the URL carries no port suffix, and because the Phase 10 captive
# portal has to answer on it anyway. The service gets CAP_NET_BIND_SERVICE
# rather than running as root. Local dev overrides it: python -m
# feed_manager.app --port 8000 (which is what the Vite proxy expects).
FEED_MANAGER_PORT: Final[int] = 80


# --- Setup hotspot (Phase 10) -------------------------------------------
# Generated once per device by deploy/setup_pi.sh and read by the panel (to
# draw the join QR), the watchdog (to raise the AP) and nothing else.
HOTSPOT_CREDENTIALS_PATH: Final[str] = "hotspot_credentials.json"
# Words the setup-hotspot password is built from. EFF Short Wordlist #1,
# CC BY 3.0 US — see the file header.
HOTSPOT_WORDLIST_PATH: Final[str] = "assets/wordlist.txt"
NETWORK_WATCHDOG_STATE_PATH: Final[str] = "network_watchdog_state.json"
# The last scan taken while the radio was free. The Pi has one Wi-Fi radio,
# so the portal cannot scan while it is hosting the setup AP — the list is
# captured just before the hotspot goes up and served from here.
NETWORK_SCAN_CACHE_PATH: Final[str] = "network_scan_cache.json"

# NetworkManager's shared mode always puts the Pi here, handing clients the
# rest of the /24. The subnet is how the web app tells a phone sitting on the
# setup hotspot from a guest on the home LAN, without shelling out to nmcli on
# every request.
HOTSPOT_ADDRESS: Final[str] = "10.42.0.1"
HOTSPOT_SUBNET: Final[str] = "10.42.0.0/24"
PORTAL_URL: Final[str] = f"http://{HOTSPOT_ADDRESS}"

# With a 60s watchdog timer this is ~3 minutes offline before the AP goes up.
# A count, not a single sample, so a router rebooting doesn't raise a hotspot.
OFFLINE_CHECKS_BEFORE_HOTSPOT: Final[int] = 3

# A hard cap, not a nicety: the portal takes a Wi-Fi password over plain HTTP,
# so an AP nobody is watching must not stay up indefinitely. Expiry is
# recoverable — the panel can raise it again on demand.
HOTSPOT_MAX_LIFETIME_SEC: Final[int] = 20 * 60

# Join attempts accepted while the AP is up, before the portal starts
# refusing. The owner needs a handful of retries for a mistyped password;
# nobody needs hundreds.
MAX_JOIN_ATTEMPTS: Final[int] = 10


@dataclass(frozen=True)
class FeedConfig:
    name: str
    url: str


@dataclass(frozen=True)
class Station:
    """A live radio stream.

    Deliberately not a Feed: a station has no episodes, no duration and no
    position to resume from, so it never goes in the database and the feed
    fetcher never sees it (every row in `feeds` is fetched every refresh cycle).
    """

    # Short form, for the station list — every full name starts with the same
    # three words, so a list of them would be unscannable at a glance.
    name: str
    # Expanded, for the player, where there is one name on screen and room to
    # say it properly. FIP has been branded as the acronym since long before
    # it stopped being Paris-only, but the box is a French radio on a shelf
    # and the full name is the nicer thing to read.
    full_name: str
    stream_url: str
    # Radio France's own id for the station on the live-metadata endpoint.
    # Confirmed one by one against what each was playing (see radio/metadata.py).
    metadata_id: int


FEEDS: Final[list[FeedConfig]] = [
    FeedConfig(
        name="Radiolab",
        url="https://feeds.simplecast.com/EmVW7VGp",
    ),
    FeedConfig(
        name="Dear Hank and John",
        url="https://rss.art19.com/dear-hank-john",
    ),
    FeedConfig(
        name="The Universe (Crash Course Pods)",
        url="https://rss.art19.com/crash-course-the-universe",
    ),
]

# Radio France's Icecast MP3 endpoints. MP3 on purpose, not the HLS (.m3u8)
# variants: mp3 is decoded by ffmpeg, which deploy/mpd.conf already forces as
# the only mp3 decoder. Unlike FEEDS these are not a one-time seed — there is
# no database table behind them, so editing this list is how stations change.
STATIONS: Final[list[Station]] = [
    Station(
        name="FIP",
        full_name="France Inter Paris",
        stream_url="https://icecast.radiofrance.fr/fip-midfi.mp3",
        metadata_id=7,
    ),
    Station(
        name="FIP Rock",
        full_name="France Inter Paris Rock",
        stream_url="https://icecast.radiofrance.fr/fiprock-midfi.mp3",
        metadata_id=64,
    ),
    Station(
        name="FIP Jazz",
        full_name="France Inter Paris Jazz",
        stream_url="https://icecast.radiofrance.fr/fipjazz-midfi.mp3",
        metadata_id=65,
    ),
    Station(
        name="FIP Groove",
        full_name="France Inter Paris Groove",
        stream_url="https://icecast.radiofrance.fr/fipgroove-midfi.mp3",
        metadata_id=66,
    ),
    Station(
        name="FIP Monde",
        full_name="France Inter Paris Monde",
        stream_url="https://icecast.radiofrance.fr/fipworld-midfi.mp3",
        metadata_id=69,
    ),
    Station(
        name="FIP Nouveautés",
        full_name="France Inter Paris Nouveautés",
        stream_url="https://icecast.radiofrance.fr/fipnouveautes-midfi.mp3",
        metadata_id=70,
    ),
    Station(
        name="FIP Reggae",
        full_name="France Inter Paris Reggae",
        stream_url="https://icecast.radiofrance.fr/fipreggae-midfi.mp3",
        metadata_id=71,
    ),
    Station(
        name="FIP Électro",
        full_name="France Inter Paris Électro",
        stream_url="https://icecast.radiofrance.fr/fipelectro-midfi.mp3",
        metadata_id=74,
    ),
]

# How often the player asks Radio France what is on air. Only ever while the
# radio player is the screen being looked at (see ScreenManager), so a box
# sitting on Home — or playing a podcast — makes no requests at all. That
# bound is the whole reason this is acceptable on a device meant to run
# unattended.
RADIO_METADATA_POLL_SEC: Final[float] = 20.0
