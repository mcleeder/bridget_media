from __future__ import annotations

from typing import Protocol


class PlaybackState(Protocol):
    """Read-only view of playback status.

    Structurally matched by player.controller.PlaybackState — defined here so the
    display layer never imports the player layer (see layer hierarchy in CLAUDE.md).
    """

    @property
    def is_playing(self) -> bool: ...

    @property
    def elapsed_sec(self) -> float: ...

    @property
    def duration_sec(self) -> float | None: ...


class AudioPlayer(Protocol):
    """Playback commands the display layer may issue.

    Structurally matched by player.controller.PlayerController; main.py injects it.
    """

    def play(self, url: str) -> None: ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def stop(self) -> None: ...

    def seek(self, position_sec: float) -> None: ...

    def skip_forward(self, seconds: float) -> None: ...

    def skip_back(self, seconds: float) -> None: ...

    def get_state(self) -> PlaybackState: ...
