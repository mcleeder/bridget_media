from __future__ import annotations

import threading
from typing import Any, Final

from PIL import Image

from config import DISPLAY_HEIGHT, DISPLAY_WIDTH
from display.errors import DisplayError

# Waveshare's init() polls the panel's BUSY line with no timeout of its own, so
# a missing or floating BUSY wire hangs it forever. A healthy panel finishes
# bring-up in well under a second; this only has to be generous enough to never
# fire on working hardware.
_BRING_UP_TIMEOUT_SEC: Final[float] = 15.0


class WaveshareDriver:
    """Hardware driver for the Waveshare 2.9" Touch E-Paper HAT.

    Wraps Waveshare's TP_lib (from the Touch_e-Paper_HAT repo, Pi-only):
    EPD_2IN9_V2 for the panel and the ICNT86 capacitive touch controller.
    ICNT_Scan already maps touch coordinates into the 296×128 landscape
    space our screens use.
    """

    # TP_lib ships no type information, so these are Any by necessity.
    _epd: Any
    _touch: Any
    _touch_current: Any
    _touch_previous: Any
    _rotate_180: bool

    def __init__(self, rotate_180: bool) -> None:
        # Import deferred to avoid import errors on non-Pi environments
        try:
            from TP_lib import epd2in9_V2, icnt86
        except ImportError as exc:
            raise DisplayError(
                "TP_lib is not installed — run deploy/setup_pi.sh on the Pi"
            ) from exc

        epd: Any = None
        touch: Any = None
        failure: Exception | None = None

        def bring_up() -> None:
            nonlocal epd, touch, failure
            try:
                epd = epd2in9_V2.EPD_2IN9_V2()
                epd.init()
                touch = icnt86.INCT86()  # sic — Waveshare's class-name typo
                touch.ICNT_Init()
            except Exception as exc:
                # Re-raised on the constructing thread below, so the caller
                # sees the failure rather than a dead background thread.
                failure = exc

        # Bring the hardware up on a daemon thread purely so the BUSY-line poll
        # can time out: a stuck bring-up would otherwise block the whole app
        # before its first frame with no log line at all. The thread can't be
        # killed, but as a daemon it dies with the process.
        thread = threading.Thread(target=bring_up, name="epd-bring-up", daemon=True)
        thread.start()
        thread.join(_BRING_UP_TIMEOUT_SEC)

        if thread.is_alive():
            raise DisplayError(
                f"e-paper panel did not respond within {_BRING_UP_TIMEOUT_SEC:.0f}s — "
                "check the BUSY, RST, DC and CS wiring"
            )
        if failure is not None:
            raise DisplayError("e-paper panel initialisation failed") from failure

        self._rotate_180 = rotate_180
        self._epd = epd
        self._touch = touch
        self._touch_current = icnt86.ICNT_Development()
        self._touch_previous = icnt86.ICNT_Development()

    def _orient(self, image: Image.Image) -> Image.Image:
        if not self._rotate_180:
            return image
        return image.transpose(Image.Transpose.ROTATE_180)

    def _orient_touch(self, x: int, y: int) -> tuple[int, int]:
        if not self._rotate_180:
            return (x, y)
        return (DISPLAY_WIDTH - 1 - x, DISPLAY_HEIGHT - 1 - y)

    def display(self, image: Image.Image) -> None:
        # display_Base (not display) so later partial refreshes diff against this frame
        self._epd.display_Base(self._epd.getbuffer(self._orient(image)))

    def display_partial(self, image: Image.Image) -> None:
        self._epd.display_Partial(self._epd.getbuffer(self._orient(image)))

    def read_touch(self) -> list[tuple[int, int]]:
        # INT pin low = touch data pending; ICNT_Scan is a no-op unless Touch == 1
        pin_active = self._touch.digital_read(self._touch.INT) == 0
        self._touch_current.Touch = 1 if pin_active else 0
        self._touch.ICNT_Scan(self._touch_current, self._touch_previous)

        count: int = self._touch_current.TouchCount
        if not count:
            return []
        self._touch_current.TouchCount = 0

        # Same primary coordinate as last scan = finger held still, not a new tap
        if (
            self._touch_previous.X[0] == self._touch_current.X[0]
            and self._touch_previous.Y[0] == self._touch_current.Y[0]
        ):
            return []

        # The panel and the touch grid are one physical part, so a rotated
        # frame needs its taps rotated too — otherwise every tap lands on the
        # row diagonally opposite the one the user pressed.
        return [
            self._orient_touch(self._touch_current.X[i], self._touch_current.Y[i])
            for i in range(count)
        ]

    def clear(self) -> None:
        self._epd.Clear(0xFF)

    def close(self) -> None:
        self._epd.sleep()
        self._epd.Dev_exit()
