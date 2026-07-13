from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from PIL import Image, ImageDraw

import display.renderer as renderer
import display.screens.list_layout as layout
from config import DISPLAY_WIDTH
from display.bluetooth_control import BluetoothDevice
from display.events import BackRequested, BluetoothDeviceSelected, Event, ListScrolled

_NAME_FONT_SIZE: Final[int] = 12
_STATUS_FONT_SIZE: Final[int] = 9
_NAME_Y_OFFSET: Final[int] = 4
_STATUS_Y_OFFSET: Final[int] = 21
_CONNECTED_ICON_SIZE: Final[int] = 18

_STATUS_MESSAGE_FONT_SIZE: Final[int] = 10
_STATUS_MESSAGE_ICON_SIZE: Final[int] = 14
_STATUS_MESSAGE_ICON_GAP: Final[int] = 5
_STATUS_MESSAGE_ICON_TOP: Final[int] = 58
_STATUS_MESSAGE_TEXT_Y: Final[int] = 61

_ERROR_TEXT: Final[str] = "Bluetooth unreachable"
_EMPTY_TEXT: Final[str] = "No paired devices — run deploy/pair_speaker.sh"


class BluetoothScreen:
    def __init__(
        self,
        devices: Sequence[BluetoothDevice] | None,
        scroll_offset: int = 0,
        connecting_device_name: str | None = None,
    ) -> None:
        self._devices = devices
        self._connecting_device_name = connecting_device_name
        self._scroller = layout.ListScroller(len(devices) if devices else 0)
        self._scroller.scroll_to(scroll_offset)

    @property
    def scroll_offset(self) -> int:
        """Current scroll position, so a rebuilt screen can restore it."""
        return self._scroller.offset

    def render(self) -> Image.Image:
        image, draw = renderer.new_canvas()
        header_font = renderer.load_text_font(layout.HEADER_FONT_SIZE)
        layout.draw_header(
            draw,
            "Bluetooth",
            header_font,
            show_back_icon=True,
            icon_font=renderer.load_icon_font(layout.HEADER_FONT_SIZE + 4),
        )

        if self._connecting_device_name is not None:
            self._draw_status_message(
                draw, f"Connecting to {self._connecting_device_name}…", renderer.ICON_BLUETOOTH
            )
        elif self._devices is None:
            self._draw_status_message(draw, _ERROR_TEXT, renderer.ICON_ERROR_OUTLINE)
        elif not self._devices:
            self._draw_empty_state(draw)
        else:
            self._draw_devices(draw)

        return image

    def handle_touch(self, x: int, y: int) -> Event | None:
        if y < layout.HEADER_HEIGHT:
            return BackRequested()
        if self._devices is None or self._connecting_device_name is not None:
            return None

        if layout.is_sidebar_touch(x, y):
            return ListScrolled() if self._scroller.handle_sidebar_touch(y) else None

        visible_row = layout.row_index_at(y)
        if visible_row is None:
            return None

        device_index = self._scroller.offset + visible_row
        if device_index >= len(self._devices):
            return None
        return BluetoothDeviceSelected(self._devices[device_index])

    def _draw_devices(self, draw: ImageDraw.ImageDraw) -> None:
        assert self._devices is not None
        name_font = renderer.load_text_font(_NAME_FONT_SIZE)
        status_font = renderer.load_text_font(_STATUS_FONT_SIZE)
        icon_font = renderer.load_icon_font(_CONNECTED_ICON_SIZE)

        visible = self._devices[self._scroller.visible_slice()]
        for index, device in enumerate(visible):
            y = layout.row_top(index)
            # Stop at the sidebar so row dividers don't cut through the chevrons
            renderer.draw_divider(draw, y, x_end=layout.SIDEBAR_X)

            renderer.draw_text_clipped(
                draw,
                device.name,
                (6, y + _NAME_Y_OFFSET),
                name_font,
                max_width=layout.ACTION_X - 12,
            )
            status_text = "Connected" if device.is_connected else "Tap to connect"
            draw.text(
                (6, y + _STATUS_Y_OFFSET), status_text, font=status_font, fill=renderer.BLACK
            )
            if device.is_connected:
                renderer.draw_icon_centered(
                    draw,
                    renderer.ICON_BLUETOOTH_CONNECTED,
                    (layout.ACTION_X, y, layout.SIDEBAR_X, y + layout.ROW_HEIGHT),
                    icon_font,
                )

        layout.draw_sidebar(draw, self._scroller)

    def _draw_empty_state(self, draw: ImageDraw.ImageDraw) -> None:
        text_font = renderer.load_text_font(_NAME_FONT_SIZE)
        renderer.draw_text_wrapped(
            draw,
            _EMPTY_TEXT,
            (6, layout.row_top(0) + _NAME_Y_OFFSET),
            text_font,
            max_width=DISPLAY_WIDTH - 12,
            max_lines=3,
            line_height=15,
        )

    @staticmethod
    def _draw_status_message(draw: ImageDraw.ImageDraw, text: str, icon: str) -> None:
        """Centered icon + single-line text — the transient/error states."""
        message_font = renderer.load_text_font(_STATUS_MESSAGE_FONT_SIZE)
        icon_font = renderer.load_icon_font(_STATUS_MESSAGE_ICON_SIZE)

        text_width = int(draw.textlength(text, font=message_font))
        total_width = _STATUS_MESSAGE_ICON_SIZE + _STATUS_MESSAGE_ICON_GAP + text_width
        x = max(6, (DISPLAY_WIDTH - total_width) // 2)

        renderer.draw_icon_centered(
            draw,
            icon,
            (
                x,
                _STATUS_MESSAGE_ICON_TOP,
                x + _STATUS_MESSAGE_ICON_SIZE,
                _STATUS_MESSAGE_ICON_TOP + _STATUS_MESSAGE_ICON_SIZE,
            ),
            icon_font,
        )
        draw.text(
            (x + _STATUS_MESSAGE_ICON_SIZE + _STATUS_MESSAGE_ICON_GAP, _STATUS_MESSAGE_TEXT_Y),
            text,
            font=message_font,
            fill=renderer.BLACK,
        )
