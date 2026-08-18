from __future__ import annotations

from dataclasses import dataclass
from typing import Final

DISPLAY_WIDTH: Final[int] = 296
DISPLAY_HEIGHT: Final[int] = 128
SIMULATOR_SCALE: Final[int] = 3

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

    name: str
    stream_url: str


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
    Station(name="FIP", stream_url="https://icecast.radiofrance.fr/fip-midfi.mp3"),
    Station(name="FIP Rock", stream_url="https://icecast.radiofrance.fr/fiprock-midfi.mp3"),
    Station(name="FIP Jazz", stream_url="https://icecast.radiofrance.fr/fipjazz-midfi.mp3"),
    Station(name="FIP Groove", stream_url="https://icecast.radiofrance.fr/fipgroove-midfi.mp3"),
    Station(name="FIP Monde", stream_url="https://icecast.radiofrance.fr/fipworld-midfi.mp3"),
    Station(
        name="FIP Nouveautés",
        stream_url="https://icecast.radiofrance.fr/fipnouveautes-midfi.mp3",
    ),
    Station(name="FIP Reggae", stream_url="https://icecast.radiofrance.fr/fipreggae-midfi.mp3"),
    Station(
        name="FIP Électro", stream_url="https://icecast.radiofrance.fr/fipelectro-midfi.mp3"
    ),
]
