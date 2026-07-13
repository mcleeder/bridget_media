from __future__ import annotations

import contextlib
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, TypeVar

from mpd import ConnectionError as MPDConnectionError
from mpd import MPDClient, MPDError

from config import MPD_HOST, MPD_PORT

logger = logging.getLogger(__name__)

T = TypeVar("T")

_RESOLVE_TIMEOUT_SEC: Final[float] = 10.0


def _resolve_stream_url(url: str) -> str:
    """Follow the redirect chain to the final audio URL before handing it to MPD.

    Podcast feeds wrap audio in ad/tracking redirects (podtrac, pscrb.fm, …) that
    can exceed MPD's hard limit of 5; urllib follows up to 10. On any failure the
    original URL is returned and MPD gets to try its own luck.
    """
    # A plain GET closed without reading the body. Not HEAD (podcast CDNs
    # mishandle it) and no Range header — WNYC's CDN bakes the probe's range
    # into the signed URL it redirects to (x-access-range=0-0), which breaks
    # MPD's seek on the stream. Some trackers (mgln.ai) 403 the default Python
    # user agent, so send a player-style one.
    request = urllib.request.Request(url, headers={"User-Agent": "pi-media/1.0 (MPD)"})
    try:
        with urllib.request.urlopen(request, timeout=_RESOLVE_TIMEOUT_SEC) as response:
            resolved: str = response.geturl()
    except urllib.error.HTTPError as exc:
        # The redirect hops before the failing response still resolved.
        resolved = exc.geturl() or url
        exc.close()
    except (urllib.error.URLError, OSError):
        logger.warning("Could not resolve redirects for %s", url, exc_info=True)
        return url
    if resolved != url:
        logger.info("Resolved stream URL to %s", resolved)
    return resolved


class PlayerError(Exception):
    pass


@dataclass(frozen=True)
class PlaybackState:
    is_playing: bool
    is_stopped: bool
    current_url: str | None
    elapsed_sec: float
    duration_sec: float | None


class PlayerController:
    def __init__(self) -> None:
        self._client = MPDClient()
        self._connected = False

    def connect(self) -> None:
        try:
            self._client.connect(MPD_HOST, MPD_PORT)
            self._connected = True
            logger.info("Connected to MPD at %s:%d", MPD_HOST, MPD_PORT)
        except (MPDError, OSError) as exc:
            raise PlayerError(f"Could not connect to MPD at {MPD_HOST}:{MPD_PORT}") from exc

    def disconnect(self) -> None:
        if self._connected:
            try:
                self._client.close()
                self._client.disconnect()
            except (MPDError, OSError):
                pass
            finally:
                self._connected = False

    def play(self, url: str) -> None:
        stream_url = _resolve_stream_url(url)

        def start(client: MPDClient) -> None:
            client.clear()
            client.add(stream_url)
            client.play(0)

        self._execute(f"start playback of '{url}'", start)
        logger.info("Playing: %s", url)

    def pause(self) -> None:
        self._execute("pause playback", lambda client: client.pause(1))

    def resume(self) -> None:
        def do_resume(client: MPDClient) -> None:
            # After a decode failure or end of queue MPD is stopped, not paused,
            # and pause(0) would be a silent no-op — restart the queued song.
            if client.status().get("state") == "stop":
                client.play()
            else:
                client.pause(0)

        self._execute("resume playback", do_resume)

    def stop(self) -> None:
        self._execute("stop playback", lambda client: client.stop())

    def seek(self, position_sec: float) -> None:
        self._execute(f"seek to {position_sec}s", lambda client: client.seekcur(position_sec))

    def skip_forward(self, seconds: float = 30.0) -> None:
        state = self.get_state()
        if state.is_playing or state.current_url is not None:
            self.seek(state.elapsed_sec + seconds)

    def skip_back(self, seconds: float = 30.0) -> None:
        state = self.get_state()
        self.seek(max(0.0, state.elapsed_sec - seconds))

    def get_state(self) -> PlaybackState:
        def read(client: MPDClient) -> PlaybackState:
            status = client.status()
            current_song = client.currentsong()

            is_playing = status.get("state") == "play"
            is_stopped = status.get("state") == "stop"
            current_url = current_song.get("file") if current_song else None
            elapsed_sec = float(status.get("elapsed", 0.0))
            raw_duration = status.get("duration")
            duration_sec = float(raw_duration) if raw_duration is not None else None

            return PlaybackState(
                is_playing=is_playing,
                is_stopped=is_stopped,
                current_url=current_url,
                elapsed_sec=elapsed_sec,
                duration_sec=duration_sec,
            )

        return self._execute("get playback state", read)

    def _execute(self, description: str, action: Callable[[MPDClient], T]) -> T:
        """Run an MPD command, reconnecting once if the connection was dropped.

        MPD closes idle client connections after its connection_timeout (60s by
        default), and it restarts when the speaker is reconfigured — both would
        otherwise leave this client permanently dead.
        """
        self._require_connected()
        try:
            return action(self._client)
        except (MPDConnectionError, OSError):
            logger.info("MPD connection lost, reconnecting")
            self._reconnect()
            try:
                return action(self._client)
            except MPDError as exc:
                raise PlayerError(f"Failed to {description}") from exc
        except MPDError as exc:
            raise PlayerError(f"Failed to {description}") from exc

    def _reconnect(self) -> None:
        # The old connection is already dead; disconnect only resets client state.
        with contextlib.suppress(MPDError, OSError):
            self._client.disconnect()
        try:
            self._client.connect(MPD_HOST, MPD_PORT)
        except (MPDError, OSError) as exc:
            self._connected = False
            raise PlayerError("Lost connection to MPD and could not reconnect") from exc
        self._connected = True
        logger.info("Reconnected to MPD at %s:%d", MPD_HOST, MPD_PORT)

    def _require_connected(self) -> None:
        if not self._connected:
            raise PlayerError("PlayerController is not connected to MPD")

    def __enter__(self) -> PlayerController:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.disconnect()
