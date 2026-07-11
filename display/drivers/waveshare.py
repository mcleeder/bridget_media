from __future__ import annotations

from PIL import Image


class WaveshareDriver:
    """Hardware driver for the Waveshare 2.9" Touch E-Paper HAT.

    Wraps Waveshare's TP_lib (from the Touch_e-Paper_HAT repo, Pi-only):
    EPD_2IN9_V2 for the panel and the ICNT86 capacitive touch controller.
    ICNT_Scan already maps touch coordinates into the 296×128 landscape
    space our screens use.
    """

    def __init__(self) -> None:
        # Import deferred to avoid import errors on non-Pi environments
        from TP_lib import epd2in9_V2, icnt86

        self._epd = epd2in9_V2.EPD_2IN9_V2()
        self._epd.init()
        self._touch = icnt86.INCT86()  # sic — Waveshare's class-name typo
        self._touch.ICNT_Init()
        self._touch_current = icnt86.ICNT_Development()
        self._touch_previous = icnt86.ICNT_Development()

    def display(self, image: Image.Image) -> None:
        # display_Base (not display) so later partial refreshes diff against this frame
        self._epd.display_Base(self._epd.getbuffer(image))

    def display_partial(self, image: Image.Image) -> None:
        self._epd.display_Partial(self._epd.getbuffer(image))

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

        return [
            (self._touch_current.X[i], self._touch_current.Y[i]) for i in range(count)
        ]

    def clear(self) -> None:
        self._epd.Clear(0xFF)

    def close(self) -> None:
        self._epd.sleep()
        self._epd.Dev_exit()
