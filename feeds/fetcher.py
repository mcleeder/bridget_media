from __future__ import annotations

import calendar
import logging
import time
from datetime import UTC, datetime
from typing import Any

import feedparser

from db.models import Feed
from db.queries import EpisodeRepository, FeedRepository

logger = logging.getLogger(__name__)


class FeedFetchError(Exception):
    pass


class FeedFetcher:
    def __init__(
        self,
        feed_repository: FeedRepository,
        episode_repository: EpisodeRepository,
    ) -> None:
        self._feed_repository = feed_repository
        self._episode_repository = episode_repository

    def fetch_all(self) -> None:
        for feed in self._feed_repository.get_all():
            try:
                self.fetch_one(feed.name, feed.url)
            except FeedFetchError as exc:
                logger.error("Failed to fetch feed '%s': %s", feed.name, exc)

    def fetch_one(self, name: str, url: str) -> Feed:
        feed = self._feed_repository.upsert(name, url)

        result: Any = feedparser.parse(url)

        # bozo=True means a parse error; some feeds are bozo but still return entries
        if result.get("bozo") and not result.get("entries"):
            raise FeedFetchError(f"Failed to parse '{url}': {result.get('bozo_exception')}")

        for entry in result.entries:
            audio_url = _extract_audio_url(entry)
            if audio_url is None:
                logger.debug("No audio enclosure in entry '%s', skipping", entry.get("title"))
                continue

            self._episode_repository.upsert(
                feed_id=feed.id,
                title=entry.get("title", "Untitled"),
                audio_url=audio_url,
                published_at=_parse_struct_time(entry.get("published_parsed")),
                duration_sec=_parse_duration(entry.get("itunes_duration")),
            )

        self._feed_repository.update_last_fetched(feed.id, datetime.now(tz=UTC))
        logger.info("Fetched %d entries from '%s'", len(result.entries), name)
        return feed


def _extract_audio_url(entry: Any) -> str | None:
    # Standard RSS enclosures
    for enclosure in entry.get("enclosures", []):
        if enclosure.get("type", "").startswith("audio/"):
            return str(enclosure["url"])
    # Some feeds put the audio link in the links list instead
    for link in entry.get("links", []):
        if link.get("type", "").startswith("audio/"):
            return str(link["href"])
    return None


def _parse_struct_time(value: time.struct_time | None) -> datetime | None:
    if value is None:
        return None
    # calendar.timegm treats struct_time as UTC; time.mktime would assume local time
    return datetime.fromtimestamp(calendar.timegm(value), tz=UTC)


def _parse_duration(value: str | None) -> int | None:
    if not value:
        return None
    parts = value.strip().split(":")
    try:
        if len(parts) == 1:
            return int(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        pass
    return None
