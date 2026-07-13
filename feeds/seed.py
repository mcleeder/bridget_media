from __future__ import annotations

from config import FEEDS
from db.queries import FeedRepository


def seed_default_feeds(feed_repository: FeedRepository) -> None:
    if feed_repository.get_all():
        return
    for feed_config in FEEDS:
        feed_repository.upsert(feed_config.name, feed_config.url)
