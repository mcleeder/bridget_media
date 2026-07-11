from __future__ import annotations

from PIL import Image


class WaveshareDriver:
    """Hardware driver for the Waveshare 2.9" Touch E-Paper HAT.

    Depends on the Waveshare EPD library which is only available on the Pi.
    Import and instantiate this only when running on hardware.
    """

    def __init__(self) -> None:
        # Import deferred to avoid import errors on non-Pi environments
        from waveshare_epd import epd2in9_V2

        self._epd = epd2in9_V2.EPD()
        self._epd.init()

    def display(self, image: Image.Image) -> None:
        self._epd.display(self._epd.getbuffer(image))

    def display_partial(self, image: Image.Image) -> None:
        self._epd.displayPartial(self._epd.getbuffer(image))

    def read_touch(self) -> list[tuple[int, int]]:
        # GT1151 touch controller — returns up to 5 touch points
        from waveshare_epd import gt1151

        touch = gt1151.GT1151()
        data = touch.GT1151_Scan(gt1151.GT_Dev, gt1151.GT_Old)
        if not data:
            return []
        return [(p.x, p.y) for p in gt1151.GT_Dev.Track[: gt1151.GT_Dev.TouchpointFlag]]

    def clear(self) -> None:
        self._epd.Clear(0xFF)

    def close(self) -> None:
        from waveshare_epd import epd2in9_V2

        epd2in9_V2.epdconfig.module_exit()
