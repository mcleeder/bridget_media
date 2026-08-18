from __future__ import annotations

from typing import Final

import segno
from PIL import Image, ImageDraw

import config
import display.copy as copy
import display.renderer as renderer
import display.screens.list_layout as layout
from display.events import BackRequested, Event
from display.network_control import HotspotCredentials

# The QR occupies the left of the body; instructions take the rest.
_QR_ZONE_WIDTH: Final[int] = 110
_TEXT_X: Final[int] = _QR_ZONE_WIDTH + 6

_SSID_FONT_SIZE: Final[int] = 12
_LABEL_FONT_SIZE: Final[int] = 9
_VALUE_FONT_SIZE: Final[int] = 11
_LINE_GAP: Final[int] = 2

# Mandatory by spec and not negotiable — a symbol without it is unreadable to
# a fair number of scanners, so if the QR cannot fit *with* the quiet zone the
# screen falls back to text rather than shrinking it.
_QUIET_ZONE_MODULES: Final[int] = 4
# Below this, a phone camera has nothing to lock onto at e-ink contrast.
_MIN_MODULE_PIXELS: Final[int] = 2


def _wifi_payload(ssid: str, password: str) -> str:
    """The WIFI: URI a phone camera turns into a one-tap join.

    Escaping matters: `;` `,` `:` and `\\` are field separators in this format,
    and an unescaped one in a password silently produces a QR that joins the
    wrong network or nothing at all.
    """
    def escape(value: str) -> str:
        for character in ("\\", ";", ",", ":", '"'):
            value = value.replace(character, f"\\{character}")
        return value

    return f"WIFI:T:WPA;S:{escape(ssid)};P:{escape(password)};;"


def _render_qr(payload: str, available: int) -> Image.Image | None:
    """Draw the QR at the largest whole-pixel module size that fits.

    Returns None when even the smallest legible size overflows, which is the
    caller's cue to show instructions only.
    """
    qr = segno.make(payload, error="l")
    modules = len(qr.matrix) + 2 * _QUIET_ZONE_MODULES
    scale = available // modules
    if scale < _MIN_MODULE_PIXELS:
        return None

    size = modules * scale
    image = Image.new("1", (size, size), renderer.WHITE)
    draw = ImageDraw.Draw(image)
    for row_index, row in enumerate(qr.matrix):
        for column_index, is_dark in enumerate(row):
            if not is_dark:
                continue
            x = (column_index + _QUIET_ZONE_MODULES) * scale
            y = (row_index + _QUIET_ZONE_MODULES) * scale
            draw.rectangle((x, y, x + scale - 1, y + scale - 1), fill=renderer.BLACK)
    return image


class WifiSetupScreen:
    """Shown while the setup hotspot is up: how to join it, and where to go.

    The QR is the fast path, but everything it encodes is also printed beside
    it — the panel is the one thing in this flow that cannot fail, so it never
    depends on a camera working or on a captive-portal sheet appearing.

    `credentials` is None when raising the hotspot failed: the transition is
    pure and always lands here, so this screen owns the failure banner rather
    than the state machine learning about outcomes (see CLAUDE.md Key Notes).
    """

    def __init__(self, credentials: HotspotCredentials | None) -> None:
        self._credentials = credentials

    def render(self) -> Image.Image:
        image, draw = renderer.new_canvas()
        layout.draw_header(
            draw,
            copy.HEADER_WIFI_SETUP,
            renderer.load_text_font(layout.HEADER_FONT_SIZE),
            show_back_icon=True,
            icon_font=renderer.load_icon_font(layout.HEADER_FONT_SIZE + 4),
        )

        if self._credentials is None:
            layout.draw_status_message(draw, copy.WIFI_HOTSPOT_FAILED, renderer.ICON_ERROR_OUTLINE)
            return image

        body_height = config.DISPLAY_HEIGHT - layout.HEADER_HEIGHT
        payload = _wifi_payload(self._credentials.ssid, self._credentials.password)
        qr = _render_qr(payload, min(_QR_ZONE_WIDTH, body_height))
        text_x = _TEXT_X
        if qr is None:
            # No usable QR: give the text the whole width rather than leaving
            # a hole where a symbol nobody can scan would have gone.
            text_x = 6
        else:
            image.paste(
                qr,
                (
                    (_QR_ZONE_WIDTH - qr.width) // 2,
                    layout.HEADER_HEIGHT + (body_height - qr.height) // 2,
                ),
            )

        self._draw_instructions(draw, text_x)
        return image

    def handle_touch(self, x: int, y: int) -> Event | None:
        if y < layout.HEADER_HEIGHT:
            return BackRequested()
        return None

    def _draw_instructions(self, draw: ImageDraw.ImageDraw, text_x: int) -> None:
        assert self._credentials is not None
        label_font = renderer.load_text_font(_LABEL_FONT_SIZE)
        value_font = renderer.load_text_font(_VALUE_FONT_SIZE)
        ssid_font = renderer.load_text_font(_SSID_FONT_SIZE)
        max_width = config.DISPLAY_WIDTH - text_x - 4

        y = layout.HEADER_HEIGHT + 6
        for label, value, font in (
            (copy.WIFI_SETUP_JOIN_LABEL, self._credentials.ssid, ssid_font),
            (copy.WIFI_SETUP_PASSWORD_LABEL, self._credentials.password, value_font),
            (copy.WIFI_SETUP_OPEN_LABEL, config.PORTAL_URL, value_font),
        ):
            draw.text((text_x, y), label, font=label_font, fill=renderer.BLACK)
            y += _LABEL_FONT_SIZE + _LINE_GAP
            renderer.draw_text_clipped(draw, value, (text_x, y), font, max_width=max_width)
            y += _SSID_FONT_SIZE + _LINE_GAP * 3
