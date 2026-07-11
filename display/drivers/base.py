from __future__ import annotations

from typing import Protocol

from PIL import Image


class DisplayDriver(Protocol):
    def display(self, image: Image.Image) -> None:
        """Full refresh — use for screen transitions."""
        ...

    def display_partial(self, image: Image.Image) -> None:
        """Partial refresh — use for in-place updates on the now-playing screen."""
        ...

    def read_touch(self) -> list[tuple[int, int]]:
        """Return a list of (x, y) touch points in device coordinates (296×128)."""
        ...

    def clear(self) -> None:
        ...

    def close(self) -> None:
        ...
