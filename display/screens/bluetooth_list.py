from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from PIL import Image, ImageDraw, ImageFont

import display.copy as copy
import display.renderer as renderer
import display.screens.list_layout as layout
from display.bluetooth_control import BluetoothDevice
from display.events import (
    BackRequested,
    BluetoothDeviceSelected,
    BluetoothForgetRequested,
    BluetoothScanRequested,
    Event,
    ListScrolled,
)

_NAME_FONT_SIZE: Final[int] = 12
_STATUS_FONT_SIZE: Final[int] = 9
_NAME_Y_OFFSET: Final[int] = 4
_STATUS_Y_OFFSET: Final[int] = 21
_STATUS_ICON_SIZE: Final[int] = 11
_STATUS_ICON_WIDTH: Final[int] = 13
_FORGET_ICON_SIZE: Final[int] = 18


class BluetoothScreen:
    """Paired devices: tap a row to connect/disconnect, action zone to forget.

    `status_message` takes over the whole body for transient states (connecting,
    pairing failed) — `devices` is ignored while it is set.
    """

    def __init__(
        self,
        devices: Sequence[BluetoothDevice] | None,
        scroll_offset: int = 0,
        status_message: str | None = None,
        is_status_error: bool = False,
    ) -> None:
        self._devices = devices
        self._status_message = status_message
        self._status_icon = (
            renderer.ICON_ERROR_OUTLINE if is_status_error else renderer.ICON_BLUETOOTH
        )
        self._scroller = layout.ListScroller(len(devices) if devices else 0)
        self._scroller.scroll_to(scroll_offset)

    @property
    def scroll_offset(self) -> int:
        """Current scroll position, so a rebuilt screen can restore it."""
        return self._scroller.offset

    def render(self) -> Image.Image:
        image, draw = renderer.new_canvas()
        layout.draw_header(
            draw,
            copy.HEADER_BLUETOOTH,
            renderer.load_text_font(layout.HEADER_FONT_SIZE),
            show_back_icon=True,
            icon_font=renderer.load_icon_font(layout.HEADER_FONT_SIZE + 4),
            action_icon=renderer.ICON_ADD_BLUETOOTH,
        )

        if self._status_message is not None:
            layout.draw_status_message(draw, self._status_message, self._status_icon)
        elif self._devices is None:
            layout.draw_status_message(
                draw, copy.BLUETOOTH_UNREACHABLE, renderer.ICON_ERROR_OUTLINE
            )
        elif not self._devices:
            layout.draw_status_message(
                draw, copy.BLUETOOTH_NO_PAIRED, renderer.ICON_BLUETOOTH_SEARCHING
            )
        else:
            self._draw_devices(draw)

        return image

    def handle_touch(self, x: int, y: int) -> Event | None:
        if y < layout.HEADER_HEIGHT:
            return (
                BluetoothScanRequested()
                if layout.is_header_action_touch(x, y)
                else BackRequested()
            )
        if self._devices is None or self._status_message is not None:
            return None

        if layout.is_sidebar_touch(x, y):
            return ListScrolled() if self._scroller.handle_sidebar_touch(y) else None

        visible_row = layout.row_index_at(y)
        if visible_row is None:
            return None

        device_index = self._scroller.offset + visible_row
        if device_index >= len(self._devices):
            return None

        device = self._devices[device_index]
        if layout.is_action_zone_touch(x, y):
            return BluetoothForgetRequested(device)
        return BluetoothDeviceSelected(device)

    def _draw_devices(self, draw: ImageDraw.ImageDraw) -> None:
        assert self._devices is not None
        name_font = renderer.load_text_font(_NAME_FONT_SIZE)
        status_font = renderer.load_text_font(_STATUS_FONT_SIZE)
        status_icon_font = renderer.load_icon_font(_STATUS_ICON_SIZE)
        forget_font = renderer.load_icon_font(_FORGET_ICON_SIZE)

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
            self._draw_connection_status(draw, device, y, status_font, status_icon_font)
            renderer.draw_icon_centered(
                draw,
                renderer.ICON_LINK_OFF,
                (layout.ACTION_X, y, layout.SIDEBAR_X, y + layout.ROW_HEIGHT),
                forget_font,
            )

        layout.draw_sidebar(draw, self._scroller)

    @staticmethod
    def _draw_connection_status(
        draw: ImageDraw.ImageDraw,
        device: BluetoothDevice,
        row_y: int,
        status_font: ImageFont.FreeTypeFont,
        icon_font: ImageFont.FreeTypeFont,
    ) -> None:
        """Connected devices are marked in the status line — the action zone now
        belongs to the forget button, so the icon can't live there any more."""
        text_x = 6
        if device.is_connected:
            renderer.draw_icon_centered(
                draw,
                renderer.ICON_BLUETOOTH_CONNECTED,
                (
                    6,
                    row_y + _STATUS_Y_OFFSET,
                    6 + _STATUS_ICON_WIDTH,
                    row_y + _STATUS_Y_OFFSET + _STATUS_ICON_SIZE,
                ),
                icon_font,
            )
            text_x = 6 + _STATUS_ICON_WIDTH
        status_text = (
            copy.DEVICE_CONNECTED if device.is_connected else copy.DEVICE_TAP_TO_CONNECT
        )
        draw.text(
            (text_x, row_y + _STATUS_Y_OFFSET), status_text, font=status_font, fill=renderer.BLACK
        )
