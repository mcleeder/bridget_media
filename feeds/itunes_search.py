from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import requests

_SEARCH_URL: Final[str] = "https://itunes.apple.com/search"
_REQUEST_TIMEOUT_SEC: Final[float] = 10.0


class ItunesSearchError(Exception):
    pass


@dataclass(frozen=True)
class PodcastSearchResult:
    name: str
    artist_name: str
    feed_url: str
    artwork_url: str | None


class ItunesSearchClient:
    def search(self, term: str, limit: int = 20, offset: int = 0) -> list[PodcastSearchResult]:
        params: dict[str, str | int] = {
            "term": term,
            "media": "podcast",
            "entity": "podcast",
            "limit": limit,
            "offset": offset,
        }
        try:
            response = requests.get(_SEARCH_URL, params=params, timeout=_REQUEST_TIMEOUT_SEC)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ItunesSearchError(f"iTunes search failed for '{term}'") from exc

        data: Any = response.json()
        results: list[PodcastSearchResult] = []
        for item in data.get("results", []):
            feed_url = item.get("feedUrl")
            if not feed_url:
                continue
            results.append(
                PodcastSearchResult(
                    name=item.get("collectionName", "Untitled"),
                    artist_name=item.get("artistName", ""),
                    feed_url=feed_url,
                    artwork_url=item.get("artworkUrl100"),
                )
            )
        return results
