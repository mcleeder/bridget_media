from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from PIL import Image, ImageDraw

import display.copy as copy
import display.renderer as renderer
import display.screens.list_layout as layout
from display.bluetooth_control import BluetoothDevice
from display.events import (
    BackRequested,
    BluetoothPairRequested,
    BluetoothScanRequested,
    Event,
    ListScrolled,
)

_NAME_FONT_SIZE: Final[int] = 12
_STATUS_FONT_SIZE: Final[int] = 9
_NAME_Y_OFFSET: Final[int] = 4
_STATUS_Y_OFFSET: Final[int] = 21


class BluetoothDiscoverScreen:
    """Nearby unpaired devices: tap a row to pair, header button to rescan.

    `devices` is None for the error state; `is_scanning` takes precedence over
    both, since a scan in flight has nothing meaningful to list yet.
    """

    def __init__(
        self,
        devices: Sequence[BluetoothDevice] | None,
        scroll_offset: int = 0,
        is_scanning: bool = False,
    ) -> None:
        self._devices = devices
        self._is_scanning = is_scanning
        self._scroller = layout.ListScroller(len(devices) if devices else 0)
        self._scroller.scroll_to(scroll_offset)

    @property
    def scroll_offset(self) -> int:
        return self._scroller.offset

    def render(self) -> Image.Image:
        image, draw = renderer.new_canvas()
        layout.draw_header(
            draw,
            copy.HEADER_ADD_DEVICE,
            renderer.load_text_font(layout.HEADER_FONT_SIZE),
            show_back_icon=True,
            icon_font=renderer.load_icon_font(layout.HEADER_FONT_SIZE + 4),
            # No rescan button mid-scan — the manager ignores it anyway.
            action_icon=None if self._is_scanning else renderer.ICON_BLUETOOTH_SEARCHING,
        )

        if self._is_scanning:
            layout.draw_status_message(
                draw, copy.BLUETOOTH_SCANNING, renderer.ICON_BLUETOOTH_SEARCHING
            )
        elif self._devices is None:
            layout.draw_status_message(
                draw, copy.BLUETOOTH_UNREACHABLE, renderer.ICON_ERROR_OUTLINE
            )
        elif not self._devices:
            layout.draw_status_message(
                draw, copy.BLUETOOTH_NOBODY_FOUND, renderer.ICON_BLUETOOTH_SEARCHING
            )
        else:
            self._draw_devices(draw)

        return image

    def handle_touch(self, x: int, y: int) -> Event | None:
        if y < layout.HEADER_HEIGHT:
            if self._is_scanning:
                # Back must stay live during a scan; rescan is suppressed.
                return BackRequested()
            return (
                BluetoothScanRequested()
                if layout.is_header_action_touch(x, y)
                else BackRequested()
            )
        if self._is_scanning or not self._devices:
            return None

        if layout.is_sidebar_touch(x, y):
            return ListScrolled() if self._scroller.handle_sidebar_touch(y) else None

        visible_row = layout.row_index_at(y)
        if visible_row is None:
            return None

        device_index = self._scroller.offset + visible_row
        if device_index >= len(self._devices):
            return None
        return BluetoothPairRequested(self._devices[device_index])

    def _draw_devices(self, draw: ImageDraw.ImageDraw) -> None:
        assert self._devices is not None
        name_font = renderer.load_text_font(_NAME_FONT_SIZE)
        status_font = renderer.load_text_font(_STATUS_FONT_SIZE)

        for index, device in enumerate(self._devices[self._scroller.visible_slice()]):
            y = layout.row_top(index)
            # Stop at the sidebar so row dividers don't cut through the chevrons
            renderer.draw_divider(draw, y, x_end=layout.SIDEBAR_X)
            renderer.draw_text_clipped(
                draw,
                device.name,
                (6, y + _NAME_Y_OFFSET),
                name_font,
                # No action zone here: the whole row is the pair target, so the
                # name may run all the way to the scroll sidebar.
                max_width=layout.SIDEBAR_X - 12,
            )
            draw.text(
                (6, y + _STATUS_Y_OFFSET),
                copy.DEVICE_TAP_TO_PAIR,
                font=status_font,
                fill=renderer.BLACK,
            )

        layout.draw_sidebar(draw, self._scroller)
