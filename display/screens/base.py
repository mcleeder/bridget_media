from __future__ import annotations

from typing import Protocol

from PIL import Image

from display.events import Event


class Screen(Protocol):
    """A screen renders itself and translates touches into events.

    Screens never navigate or command the player directly — they emit an Event
    (or None when a touch means nothing) and ScreenManager drives the state machine.
    """

    def render(self) -> Image.Image: ...

    def handle_touch(self, x: int, y: int) -> Event | None: ...
