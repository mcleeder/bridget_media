"""What is playing right now on a Radio France webradio.

A peer of `player/` and `network/`: it knows `config` and nothing above it, and
it reaches the outside world directly rather than through another layer.

Radio France's Icecast servers send **no ICY metadata** — a request with
`Icy-MetaData: 1` comes back with `icy-name` set to the filename and no
`icy-metaint` — so there is no `StreamTitle` for MPD to expose and nothing to
read from `currentsong()`. The only working source is this undocumented legacy
endpoint, which needs no API key.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Final

logger = logging.getLogger(__name__)

_ENDPOINT: Final[str] = "https://api.radiofrance.fr/livemeta/pull/{station_id}"
_TIMEOUT_SEC: Final[float] = 6.0
# Radio France 403s the default Python user agent on some paths, as the podcast
# trackers in player/controller.py do.
_USER_AGENT: Final[str] = "pi-media/1.0"

# A step that is not a song — a jingle, a talk break — carries no useful
# title/artist pair, so it reads as "nothing to show" rather than a bad guess.
_SONG_EMBED_TYPE: Final[str] = "song"


class RadioMetadataError(Exception):
    pass


@dataclass(frozen=True)
class TrackMetadata:
    """The track currently on air. Every field beyond the title is optional —
    the feed is inconsistent about albums, years and even artists."""

    title: str
    artist: str | None
    album: str | None
    year: int | None


class RadioMetadataClient:
    def get_current_track(self, station_id: int) -> TrackMetadata | None:
        """The track on air, or None when the station is not playing a song.

        Raises RadioMetadataError for anything that stopped us finding out;
        callers treat that and None the same way, but the distinction keeps a
        genuine outage out of the "it's a jingle" bucket in the logs.
        """
        payload = self._fetch(station_id)
        step = _current_step(payload)
        if step is None or step.get("embedType") != _SONG_EMBED_TYPE:
            return None
        return _to_track(step)

    def _fetch(self, station_id: int) -> dict[str, Any]:
        request = urllib.request.Request(
            _ENDPOINT.format(station_id=station_id), headers={"User-Agent": _USER_AGENT}
        )
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_SEC) as response:
                raw = response.read()
        except (urllib.error.URLError, OSError) as exc:
            raise RadioMetadataError(
                f"Could not reach live metadata for station {station_id}"
            ) from exc
        try:
            payload: dict[str, Any] = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise RadioMetadataError(
                f"Unreadable live metadata for station {station_id}"
            ) from exc
        return payload


def _current_step(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Pick the on-air step using the server's own cursor.

    `levels[0].position` indexes `levels[0].items`, which is deliberately used
    in preference to comparing the steps' `start`/`end` timestamps against our
    clock: the Pi 3B+ has no RTC, so after an offline boot the clock is stale
    until NTP lands and every window comparison would pick the wrong track — or
    none at all. The server's cursor needs no clock of ours to be right.
    """
    levels = payload.get("levels")
    steps = payload.get("steps")
    if not isinstance(levels, list) or not levels or not isinstance(steps, dict):
        return None
    level = levels[0]
    items = level.get("items")
    position = level.get("position")
    if not isinstance(items, list) or not isinstance(position, int):
        return None
    if not 0 <= position < len(items):
        return None
    step = steps.get(items[position])
    return step if isinstance(step, dict) else None


def _to_track(step: dict[str, Any]) -> TrackMetadata | None:
    title = _clean(step.get("title"))
    if title is None:
        return None
    return TrackMetadata(
        title=title,
        artist=_artist(step),
        album=_clean(step.get("titreAlbum")),
        year=_year(step.get("anneeEditionMusique")),
    )


def _artist(step: dict[str, Any]) -> str | None:
    """Prefer the curated artist list over the raw credits string.

    `authors` runs to every session player on a jazz or soul record — one
    observed value named five people and ran past 90 characters, which is
    three wrapped lines on a 296px panel. `highlightedArtists` is Radio
    France's own answer to "whose record is this".
    """
    highlighted = step.get("highlightedArtists")
    if isinstance(highlighted, list):
        names = [name for name in (_clean(item) for item in highlighted) if name is not None]
        if names:
            return ", ".join(names)
    return _clean(step.get("authors"))


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _year(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    return None
