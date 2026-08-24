"""Regenerate touch_zones.png — the on-device tap-target reference.

Run from the repo root:

    python tools/make_touch_zones.py

Every zone below is derived from the real layout constants and drawn over a
real screen render, so the diagram cannot drift from the code the way a
hand-made image does. Re-run it whenever a screen gains or moves a tap target.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import display.renderer as renderer  # noqa: E402
import display.screens.list_layout as layout  # noqa: E402
import display.screens.sleep_badge as sleep_badge  # noqa: E402
from config import DISPLAY_HEIGHT, DISPLAY_WIDTH, Station  # noqa: E402
from db.models import Episode, Feed, QueueEntry  # noqa: E402
from display.playback import AudioPlayer  # noqa: E402
from display.screens.bluetooth_discover import BluetoothDiscoverScreen  # noqa: E402
from display.screens.bluetooth_list import BluetoothScreen  # noqa: E402
from display.screens.episode_list import EpisodeListScreen  # noqa: E402
from display.screens.home import HomeScreen  # noqa: E402
from display.screens.now_playing import NowPlayingScreen  # noqa: E402
from display.screens.podcast_list import PodcastListScreen  # noqa: E402
from display.screens.queue_list import QueueListScreen  # noqa: E402
from display.screens.radio_list import RadioListScreen  # noqa: E402
from display.screens.radio_playing import RadioPlayingScreen  # noqa: E402
from display.screens.sleep_timer import SleepTimerScreen, cell_rect  # noqa: E402
from display.screens.wifi_list import WifiScreen  # noqa: E402
from display.screens.wifi_setup import WifiSetupScreen  # noqa: E402
from display.sleep_timer import DURATION_CHOICES  # noqa: E402

SCALE: Final[int] = 3
MARGIN: Final[int] = 20
TITLE_HEIGHT: Final[int] = 26
GAP: Final[int] = 18

# Panel is 2.9" diagonal at 296x128 → 0.227mm per pixel.
MM_PER_PIXEL: Final[float] = 0.227

ROW = (60, 130, 246)
ACTION = (232, 140, 40)
SCROLL_UP = (40, 160, 90)
SCROLL_DOWN = (232, 140, 40)
BACK = (214, 55, 55)
ADD = (150, 70, 200)
PRIMARY = (120, 40, 160)
SKIP = (40, 170, 180)
SLEEP = (90, 90, 200)
DEAD = (150, 150, 150)


@dataclass(frozen=True)
class Zone:
    rect: tuple[int, int, int, int]  # device px, x0 y0 x1 y1 (exclusive)
    label: str
    color: tuple[int, int, int]
    show_aim: bool = True

    @property
    def aim(self) -> tuple[int, int]:
        x0, y0, x1, y1 = self.rect
        return ((x0 + x1) // 2, (y0 + y1) // 2)


def row_zones(
    label: str, color: tuple[int, int, int], x_end: int
) -> list[Zone]:
    return [
        Zone(
            (0, layout.row_top(i), x_end, layout.row_top(i) + layout.ROW_HEIGHT),
            f"{label} (row {i})",
            color,
        )
        for i in range(layout.VISIBLE_ROWS)
    ]


def action_zones(label: str) -> list[Zone]:
    return [
        Zone(
            (
                layout.ACTION_X,
                layout.row_top(i),
                layout.SIDEBAR_X,
                layout.row_top(i) + layout.ROW_HEIGHT,
            ),
            f"{label} (row {i})",
            ACTION,
        )
        for i in range(layout.VISIBLE_ROWS)
    ]


def sidebar_zones() -> list[Zone]:
    middle = (layout.HEADER_HEIGHT + DISPLAY_HEIGHT) // 2
    return [
        Zone(
            (layout.SIDEBAR_X, layout.HEADER_HEIGHT, DISPLAY_WIDTH, middle),
            "scroll UP",
            SCROLL_UP,
        ),
        Zone(
            (layout.SIDEBAR_X, middle, DISPLAY_WIDTH, DISPLAY_HEIGHT),
            "scroll DOWN",
            SCROLL_DOWN,
        ),
    ]


def radio_zones(controls_top: int, button_w: int) -> list[Zone]:
    """Both radio-player layouts have identical targets — only the body differs."""
    return [
        Zone((0, 0, DISPLAY_WIDTH, controls_top), "no action", DEAD, show_aim=False),
        sleep_zone(),
        Zone((0, controls_top, button_w, DISPLAY_HEIGHT), "BACK (stops)", BACK),
        Zone((button_w, controls_top, DISPLAY_WIDTH, DISPLAY_HEIGHT), "PLAY / PAUSE", PRIMARY),
    ]


def sleep_zone() -> Zone:
    """The badge's tap target — deliberately larger than its ink."""
    return Zone(
        (sleep_badge.TOUCH_LEFT, 0, DISPLAY_WIDTH, sleep_badge.TOUCH_BOTTOM),
        "SLEEP TIMER",
        SLEEP,
    )


def sleep_cell_zones() -> list[Zone]:
    zones = []
    for index, minutes in enumerate(DURATION_CHOICES):
        rect = cell_rect(index)
        label = f"set {minutes}m (tap again to clear)"
        zones.append(Zone(rect, label, SLEEP if minutes != 30 else PRIMARY))
    return zones


def header_back(x_end: int = DISPLAY_WIDTH) -> Zone:
    return Zone((0, 0, x_end, layout.HEADER_HEIGHT), "BACK — whole header", BACK)


def build_screens() -> list[tuple[str, Image.Image, list[Zone]]]:
    feed = Feed(id=1, name="Darknet Diaries", url="x", last_fetched=None)
    episodes = [
        Episode(id=i, feed_id=1, title=t, audio_url="x", published_at=datetime(2026, 7, day),
                duration_sec=1800, played=False, play_position_sec=0)
        for i, (t, day) in enumerate(
            [("The NSO Dilemma", 10), ("Bayrob", 9), ("Mini Stories Vol. 12", 8)], start=1
        )
    ]
    feeds = [Feed(id=i, name=n, url="x", last_fetched=None)
             for i, n in enumerate(["99% Invisible", "Darknet Diaries", "Radiolab"], start=1)]
    entries = [QueueEntry(id=i, episode=e, feed_name="Darknet Diaries", added_at=datetime.now())
               for i, e in enumerate(episodes, start=1)]

    @dataclass(frozen=True)
    class Device:
        mac: str
        name: str
        is_connected: bool

    paired = [Device("A", "EarFun UBOOM L", True), Device("B", "ACCENTUM TW", False),
              Device("C", "LinkBuds Fit", False)]
    nearby = [Device("D", "Pixel 8", False), Device("E", "Sony WH-1000XM4", False),
              Device("F", "Bose SoundLink", False)]

    @dataclass(frozen=True)
    class State:
        is_playing: bool = True
        is_stopped: bool = False
        elapsed_sec: float = 754.0
        duration_sec: float | None = 2613.0

    class Player:
        """Static state — the diagram only needs one representative frame."""

        def get_state(self) -> State:
            return State()

        def play(self, url: str) -> None: ...
        def pause(self) -> None: ...
        def resume(self) -> None: ...
        def stop(self) -> None: ...
        def seek(self, seconds: float) -> None: ...
        def skip_forward(self, seconds: float) -> None: ...
        def skip_back(self, seconds: float) -> None: ...

    player: AudioPlayer = Player()
    stations = [Station(name=n, full_name=f"France Inter Paris {n[4:]}".strip(),
                        stream_url="x", metadata_id=i)
                for i, n in enumerate(["FIP", "FIP Rock", "FIP Jazz", "FIP Groove"])]

    @dataclass(frozen=True)
    class Track:
        title: str
        artist: str | None
        album: str | None
        year: int | None

    track = Track("Wish you were here", "Pink Floyd", "Wish you were here", 1975)

    @dataclass(frozen=True)
    class Status:
        is_online: bool = True
        ssid: str | None = "Ravenwood"
        ip_address: str | None = "192.168.1.50"
        is_hotspot_active: bool = False

    status = Status()

    @dataclass(frozen=True)
    class Credentials:
        ssid: str = "Bridget-Setup-ab12"
        password: str = "swordfish123"
    header_no_action = layout.HEADER_ACTION_X
    button_w = DISPLAY_WIDTH // 4
    controls_top = 95

    return [
        (
            "Home — root menu (no back button; scrolls, 5 items)",
            HomeScreen().render(),
            [Zone((0, 0, DISPLAY_WIDTH, layout.HEADER_HEIGHT), "no action", DEAD, show_aim=False),
             *row_zones("open", ROW, layout.SIDEBAR_X), *sidebar_zones()],
        ),
        (
            "Podcast List",
            PodcastListScreen(feeds).render(),
            [header_back(), *row_zones("open podcast", ROW, layout.SIDEBAR_X), *sidebar_zones()],
        ),
        (
            "Episode List — action zone toggles the queue (+ / ✓)",
            EpisodeListScreen(feed, episodes, set()).render(),
            [header_back(), *row_zones("play episode", ROW, layout.ACTION_X),
             *action_zones("queue toggle"), *sidebar_zones()],
        ),
        (
            "Next (queue) — action zone removes the entry",
            QueueListScreen(entries).render(),
            [header_back(), *row_zones("play episode", ROW, layout.ACTION_X),
             *action_zones("remove"), *sidebar_zones()],
        ),
        (
            "Bluetooth — header right is ADD DEVICE; action zone forgets",
            BluetoothScreen(paired).render(),
            [header_back(header_no_action),
             Zone((layout.HEADER_ACTION_X, 0, DISPLAY_WIDTH, layout.HEADER_HEIGHT),
                  "ADD DEVICE (scan)", ADD),
             *row_zones("connect / disconnect", ROW, layout.ACTION_X),
             *action_zones("forget"), *sidebar_zones()],
        ),
        (
            "Add device — whole row pairs; header right rescans",
            BluetoothDiscoverScreen(nearby).render(),
            [header_back(header_no_action),
             Zone((layout.HEADER_ACTION_X, 0, DISPLAY_WIDTH, layout.HEADER_HEIGHT),
                  "RESCAN", ADD),
             *row_zones("pair", ROW, layout.SIDEBAR_X), *sidebar_zones()],
        ),
        (
            "Wi-Fi — status only; header right raises the setup hotspot",
            WifiScreen(status).render(),
            [header_back(header_no_action),
             Zone((layout.HEADER_ACTION_X, 0, DISPLAY_WIDTH, layout.HEADER_HEIGHT),
                  "START SETUP HOTSPOT", ADD),
             Zone((0, layout.HEADER_HEIGHT, DISPLAY_WIDTH, DISPLAY_HEIGHT),
                  "no action", DEAD, show_aim=False)],
        ),
        (
            "Setup mode — join QR + instructions; header is the only tap target",
            WifiSetupScreen(Credentials()).render(),
            [header_back(),
             Zone((0, layout.HEADER_HEIGHT, DISPLAY_WIDTH, DISPLAY_HEIGHT),
                  "no action", DEAD, show_aim=False)],
        ),
        (
            "Radio — whole row tunes in (live streams, no queue or action zone)",
            RadioListScreen(stations).render(),
            [header_back(), *row_zones("play station", ROW, layout.SIDEBAR_X), *sidebar_zones()],
        ),
        (
            "Radio playing — track known: title in guillemets is the headline, "
            "station name shrinks to a label. Body has no tap targets",
            RadioPlayingScreen(stations[2], player, lambda: 30, lambda: track).render(),
            radio_zones(controls_top, button_w),
        ),
        (
            "Radio playing — nothing nameable on air (jingle, talk break, or the "
            "metadata call failed): the station name takes the screen back",
            RadioPlayingScreen(stations[2], player, lambda: None, lambda: None).render(),
            radio_zones(controls_top, button_w),
        ),
        (
            "Now Playing — controls are bottom-anchored",
            NowPlayingScreen(episodes[0], "Darknet Diaries", player, lambda: 30).render(),
            [Zone((0, 0, DISPLAY_WIDTH, controls_top), "no action", DEAD, show_aim=False),
             sleep_zone(),
             Zone((0, controls_top, button_w, DISPLAY_HEIGHT), "BACK (stops)", BACK),
             Zone((button_w, controls_top, button_w * 2, DISPLAY_HEIGHT), "-30s", SKIP),
             Zone((button_w * 2, controls_top, button_w * 3, DISPLAY_HEIGHT),
                  "PLAY / PAUSE", PRIMARY),
             Zone((button_w * 3, controls_top, DISPLAY_WIDTH, DISPLAY_HEIGHT), "+30s", SKIP)],
        ),
        (
            "Sleep timer — a grid, not a list: every choice is one tap, and "
            "tapping the selected cell clears it",
            SleepTimerScreen(30).render(),
            [header_back(), *sleep_cell_zones()],
        ),
    ]


def load_label_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(renderer.TEXT_FONT_PATH, size)


def draw_screen(
    canvas: Image.Image, top: int, title: str, screen: Image.Image, zones: list[Zone]
) -> int:
    draw = ImageDraw.Draw(canvas)
    draw.text((MARGIN, top), title, font=load_label_font(15), fill=(0, 0, 0))

    panel_top = top + TITLE_HEIGHT
    panel = screen.convert("RGB").resize(
        (DISPLAY_WIDTH * SCALE, DISPLAY_HEIGHT * SCALE), Image.Resampling.NEAREST
    )
    overlay = Image.new("RGBA", panel.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)

    for zone in zones:
        x0, y0, x1, y1 = (v * SCALE for v in zone.rect)
        odraw.rectangle(
            (x0, y0, x1 - 1, y1 - 1), fill=(*zone.color, 60), outline=zone.color, width=2
        )
        if zone.show_aim:
            ax, ay = (v * SCALE for v in zone.aim)
            odraw.line((ax - 9, ay, ax + 9, ay), fill=zone.color, width=3)
            odraw.line((ax, ay - 9, ax, ay + 9), fill=zone.color, width=3)

    panel = Image.alpha_composite(panel.convert("RGBA"), overlay).convert("RGB")
    canvas.paste(panel, (MARGIN, panel_top))
    draw.rectangle(
        (MARGIN, panel_top, MARGIN + panel.width, panel_top + panel.height),
        outline=(30, 30, 30), width=2,
    )

    legend_x = MARGIN + panel.width + 16
    y = panel_top
    font = load_label_font(13)
    seen: set[str] = set()
    for zone in zones:
        if not zone.show_aim or zone.label in seen:
            continue
        seen.add(zone.label)
        draw.rectangle((legend_x, y + 3, legend_x + 11, y + 14), fill=zone.color)
        draw.text(
            (legend_x + 18, y), f"{zone.label}  →  aim {zone.aim}", font=font, fill=(20, 20, 20)
        )
        y += 19

    return panel_top + panel.height + GAP


def main() -> None:
    screens = build_screens()
    width = MARGIN * 2 + DISPLAY_WIDTH * SCALE + 330
    notes_height = 150
    height = MARGIN * 2 + notes_height + sum(
        TITLE_HEIGHT + DISPLAY_HEIGHT * SCALE + GAP for _ in screens
    )

    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    top = MARGIN
    for title, screen, zones in screens:
        top = draw_screen(canvas, top, title, screen, zones)

    draw = ImageDraw.Draw(canvas)
    font = load_label_font(13)
    notes = [
        "Coordinates are device pixels, origin top-left, screen "
        f"{DISPLAY_WIDTH}x{DISPLAY_HEIGHT}. 1px = {MM_PER_PIXEL}mm.",
        "Crosshairs mark each zone's centre — the safest place to tap. Grey = dead area.",
        "",
        f"header {layout.HEADER_HEIGHT}px = {layout.HEADER_HEIGHT * MM_PER_PIXEL:.1f}mm tall  ·  "
        f"list row {layout.ROW_HEIGHT}px = {layout.ROW_HEIGHT * MM_PER_PIXEL:.1f}mm tall  ·  "
        f"scroll sidebar {DISPLAY_WIDTH - layout.SIDEBAR_X}px = "
        f"{(DISPLAY_WIDTH - layout.SIDEBAR_X) * MM_PER_PIXEL:.1f}mm wide",
        f"row action zone {layout.SIDEBAR_X - layout.ACTION_X}px = "
        f"{(layout.SIDEBAR_X - layout.ACTION_X) * MM_PER_PIXEL:.1f}mm wide  ·  "
        f"header action button {DISPLAY_WIDTH - layout.HEADER_ACTION_X}px = "
        f"{(DISPLAY_WIDTH - layout.HEADER_ACTION_X) * MM_PER_PIXEL:.1f}mm wide  ·  "
        f"transport button {DISPLAY_WIDTH // 4}px = "
        f"{(DISPLAY_WIDTH // 4) * MM_PER_PIXEL:.1f}mm wide",
        "",
        "Scroll chevrons only draw when that direction can scroll, "
        "but the tap zones are always live.",
        "Taps within 300ms of the previous one are ignored (capacitive double-fire debounce).",
        "Regenerate with:  python tools/make_touch_zones.py",
    ]
    for line in notes:
        draw.text((MARGIN, top), line, font=font, fill=(40, 40, 40))
        top += 17

    out = Path(__file__).resolve().parents[1] / "touch_zones.png"
    canvas.save(out)
    print(f"wrote {out}  ({canvas.width}x{canvas.height})")


if __name__ == "__main__":
    main()
