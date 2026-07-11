from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Feed:
    id: int
    name: str
    url: str
    last_fetched: datetime | None


@dataclass(frozen=True)
class Episode:
    id: int
    feed_id: int
    title: str
    audio_url: str
    published_at: datetime | None
    duration_sec: int | None
    played: bool
    play_position_sec: int
