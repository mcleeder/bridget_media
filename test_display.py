"""Quick hardware test — clears the screen then draws text and a border."""
from __future__ import annotations

from PIL import Image, ImageDraw
from waveshare_epd import epd2in9_V2

WIDTH = 296
HEIGHT = 128


def main() -> None:
    print("Init display...")
    epd = epd2in9_V2.EPD()
    epd.init()

    print("Clearing screen...")
    epd.Clear(0xFF)

    print("Drawing test image...")
    image = Image.new("1", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(image)

    draw.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=0)
    draw.text((10, 10), "Hello Pi!", fill=0)
    draw.text((10, 30), "Display OK", fill=0)
    draw.line([10, 60, WIDTH - 10, 60], fill=0, width=2)
    draw.text((10, 70), f"{WIDTH}x{HEIGHT}  2.9in V2", fill=0)

    print("Sending to display...")
    epd.display(epd.getbuffer(image))

    print("Done. Press Ctrl+C to clear and exit, or just Ctrl+C to leave image.")
    try:
        import time
        time.sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        print("Clearing and closing...")
        epd.Clear(0xFF)
        epd2in9_V2.epdconfig.module_exit()
        print("Closed.")


if __name__ == "__main__":
    main()
