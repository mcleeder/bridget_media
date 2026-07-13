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


@dataclass(frozen=True)
class FeedConfig:
    name: str
    url: str


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
