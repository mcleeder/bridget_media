from __future__ import annotations

import logging
from dataclasses import dataclass

from mpd import MPDClient, MPDError

from config import MPD_HOST, MPD_PORT

logger = logging.getLogger(__name__)


class PlayerError(Exception):
    pass


@dataclass(frozen=True)
class PlaybackState:
    is_playing: bool
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
        except MPDError as exc:
            raise PlayerError(f"Could not connect to MPD at {MPD_HOST}:{MPD_PORT}") from exc

    def disconnect(self) -> None:
        if self._connected:
            try:
                self._client.close()
                self._client.disconnect()
            except MPDError:
                pass
            finally:
                self._connected = False

    def play(self, url: str) -> None:
        self._require_connected()
        try:
            self._client.clear()
            self._client.add(url)
            self._client.play(0)
            logger.info("Playing: %s", url)
        except MPDError as exc:
            raise PlayerError(f"Failed to start playback of '{url}'") from exc

    def pause(self) -> None:
        self._require_connected()
        try:
            self._client.pause(1)
        except MPDError as exc:
            raise PlayerError("Failed to pause playback") from exc

    def resume(self) -> None:
        self._require_connected()
        try:
            self._client.pause(0)
        except MPDError as exc:
            raise PlayerError("Failed to resume playback") from exc

    def stop(self) -> None:
        self._require_connected()
        try:
            self._client.stop()
        except MPDError as exc:
            raise PlayerError("Failed to stop playback") from exc

    def seek(self, position_sec: float) -> None:
        self._require_connected()
        try:
            self._client.seekcur(position_sec)
        except MPDError as exc:
            raise PlayerError(f"Failed to seek to {position_sec}s") from exc

    def skip_forward(self, seconds: float = 30.0) -> None:
        state = self.get_state()
        if state.is_playing or state.current_url is not None:
            self.seek(state.elapsed_sec + seconds)

    def skip_back(self, seconds: float = 30.0) -> None:
        state = self.get_state()
        self.seek(max(0.0, state.elapsed_sec - seconds))

    def get_state(self) -> PlaybackState:
        self._require_connected()
        try:
            status = self._client.status()
            current_song = self._client.currentsong()

            is_playing = status.get("state") == "play"
            current_url = current_song.get("file") if current_song else None
            elapsed_sec = float(status.get("elapsed", 0.0))
            raw_duration = status.get("duration")
            duration_sec = float(raw_duration) if raw_duration is not None else None

            return PlaybackState(
                is_playing=is_playing,
                current_url=current_url,
                elapsed_sec=elapsed_sec,
                duration_sec=duration_sec,
            )
        except MPDError as exc:
            raise PlayerError("Failed to get playback state") from exc

    def _require_connected(self) -> None:
        if not self._connected:
            raise PlayerError("PlayerController is not connected to MPD")

    def __enter__(self) -> PlayerController:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.disconnect()
