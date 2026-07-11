from __future__ import annotations

import queue
import threading
import tkinter as tk
from typing import Final

from PIL import Image, ImageTk

from config import DISPLAY_HEIGHT, DISPLAY_WIDTH, SIMULATOR_SCALE

_WINDOW_W: Final[int] = DISPLAY_WIDTH * SIMULATOR_SCALE
_WINDOW_H: Final[int] = DISPLAY_HEIGHT * SIMULATOR_SCALE


class SimulatorDriver:
    """tkinter-based display simulator for local development.

    Renders the e-ink canvas scaled up for visibility. Mouse clicks are
    translated back to device coordinates and queued as touch events.
    """

    def __init__(self) -> None:
        self._touch_queue: queue.Queue[tuple[int, int]] = queue.Queue()
        self._tk_image: ImageTk.PhotoImage | None = None
        self._root: tk.Tk | None = None
        self._canvas: tk.Canvas | None = None
        self._ready = threading.Event()

        self._thread = threading.Thread(target=self._run_tk, daemon=True)
        self._thread.start()
        self._ready.wait()

    def display(self, image: Image.Image) -> None:
        self._render(image)

    def display_partial(self, image: Image.Image) -> None:
        self._render(image)

    def read_touch(self) -> list[tuple[int, int]]:
        points: list[tuple[int, int]] = []
        while not self._touch_queue.empty():
            try:
                points.append(self._touch_queue.get_nowait())
            except queue.Empty:
                break
        return points

    def clear(self) -> None:
        blank = Image.new("1", (DISPLAY_WIDTH, DISPLAY_HEIGHT), 1)
        self._render(blank)

    def close(self) -> None:
        if self._root is not None:
            self._root.after(0, self._root.destroy)

    def _render(self, image: Image.Image) -> None:
        if self._root is None or self._canvas is None:
            return
        scaled = image.resize((_WINDOW_W, _WINDOW_H), Image.Resampling.NEAREST).convert("RGB")
        # Schedule on the tk thread — ImageTk must be created there
        self._root.after(0, self._update_canvas, scaled)

    def _update_canvas(self, image: Image.Image) -> None:
        if self._canvas is None:
            return
        self._tk_image = ImageTk.PhotoImage(image)
        self._canvas.create_image(0, 0, anchor=tk.NW, image=self._tk_image)

    def _on_click(self, event: tk.Event[tk.Canvas]) -> None:
        device_x = int(event.x / SIMULATOR_SCALE)
        device_y = int(event.y / SIMULATOR_SCALE)
        device_x = max(0, min(device_x, DISPLAY_WIDTH - 1))
        device_y = max(0, min(device_y, DISPLAY_HEIGHT - 1))
        self._touch_queue.put((device_x, device_y))

    def _run_tk(self) -> None:
        self._root = tk.Tk()
        self._root.title("Pi Media Simulator")
        self._root.resizable(False, False)

        self._canvas = tk.Canvas(
            self._root, width=_WINDOW_W, height=_WINDOW_H, bg="white", cursor="crosshair"
        )
        self._canvas.pack()
        self._canvas.bind("<Button-1>", self._on_click)

        self._ready.set()
        self._root.mainloop()
