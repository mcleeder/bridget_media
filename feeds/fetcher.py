from __future__ import annotations

import calendar
import logging
import time
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import urlparse

import feedparser

from db.models import Feed
from db.queries import EpisodeRepository, FeedRepository

logger = logging.getLogger(__name__)

_ALLOWED_URL_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})


class FeedFetchError(Exception):
    pass


class InvalidFeedUrlError(FeedFetchError):
    """The caller supplied something that isn't a fetchable web URL.

    A subclass so fetch_all's existing handler still catches it, but the web app
    can answer 400 instead of 502 — it's the caller's mistake, not the feed's.
    """


def _validate_feed_url(url: str) -> None:
    """Reject anything feedparser would read as a local path or non-web URL.

    feedparser.parse() opens a filesystem path or file:// URL as readily as an
    http one, and this URL arrives from an unauthenticated web request — without
    this check the feed manager is a local-file-read and internal-port-scan
    primitive for anyone who can reach it.
    """
    if urlparse(url).scheme.lower() not in _ALLOWED_URL_SCHEMES:
        raise InvalidFeedUrlError(f"Feed URL must start with http:// or https:// — got '{url}'")


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
        # Before the upsert: a rejected URL must not leave a feed row behind.
        _validate_feed_url(url)

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
