from __future__ import annotations

from typing import Final

from PIL import Image, ImageDraw, ImageFont

import config
import display.copy as copy
import display.renderer as renderer
import display.screens.list_layout as layout
from display.events import BackRequested, Event
from display.network_control import NetworkStatus

_NAME_FONT_SIZE: Final[int] = 13
_DETAIL_FONT_SIZE: Final[int] = 12
_STATUS_FONT_SIZE: Final[int] = 9

_NAME_Y_OFFSET: Final[int] = 4
_STATUS_Y_OFFSET: Final[int] = 21
_DETAIL_Y_OFFSET: Final[int] = 10

_ICON_ZONE_WIDTH: Final[int] = 34
_ROW_ICON_SIZE: Final[int] = 16
_TEXT_X: Final[int] = _ICON_ZONE_WIDTH + 4


class WifiScreen:
    """Read-only network status: which network, which address, which URL.

    Three rows rather than a list: the network name with a one-word state under
    it (the Bluetooth row idiom), the device's address, and the name to type
    into a browser — which is the only thing on here anyone is meant to act on.

    `status` is None for both "still asking" and "no NetworkManager here";
    `is_loading` tells those two apart.
    """

    def __init__(self, status: NetworkStatus | None, is_loading: bool = False) -> None:
        self._status = status
        self._is_loading = is_loading

    def render(self) -> Image.Image:
        image, draw = renderer.new_canvas()
        layout.draw_header(
            draw,
            copy.HEADER_WIFI,
            renderer.load_text_font(layout.HEADER_FONT_SIZE),
            show_back_icon=True,
            icon_font=renderer.load_icon_font(layout.HEADER_FONT_SIZE + 4),
        )

        if self._is_loading:
            layout.draw_status_message(draw, copy.WIFI_CHECKING, renderer.ICON_WIFI)
        elif self._status is None:
            layout.draw_status_message(draw, copy.WIFI_UNREACHABLE, renderer.ICON_ERROR_OUTLINE)
        elif self._status.ssid is None:
            layout.draw_status_message(draw, copy.WIFI_OFFLINE, renderer.ICON_WIFI_OFF)
        else:
            self._draw_details(draw, self._status)

        return image

    def handle_touch(self, x: int, y: int) -> Event | None:
        if y < layout.HEADER_HEIGHT:
            return BackRequested()
        return None

    def _draw_details(self, draw: ImageDraw.ImageDraw, status: NetworkStatus) -> None:
        assert status.ssid is not None
        icon_font = renderer.load_icon_font(_ROW_ICON_SIZE)

        network_row = layout.row_top(0)
        self._draw_row_icon(draw, self._network_icon(status), network_row, icon_font)
        renderer.draw_text_clipped(
            draw,
            status.ssid,
            (_TEXT_X, network_row + _NAME_Y_OFFSET),
            renderer.load_text_font(_NAME_FONT_SIZE),
            max_width=layout.SIDEBAR_X - _TEXT_X,
        )
        draw.text(
            (_TEXT_X, network_row + _STATUS_Y_OFFSET),
            self._connection_label(status),
            font=renderer.load_text_font(_STATUS_FONT_SIZE),
            fill=renderer.BLACK,
        )

        detail_font = renderer.load_text_font(_DETAIL_FONT_SIZE)
        for index, (icon, text) in enumerate(
            (
                (renderer.ICON_LAN, status.ip_address or copy.WIFI_NO_ADDRESS),
                (renderer.ICON_PUBLIC, config.FEED_MANAGER_HOST),
            ),
            start=1,
        ):
            y = layout.row_top(index)
            renderer.draw_divider(draw, y)
            self._draw_row_icon(draw, icon, y, icon_font)
            renderer.draw_text_clipped(
                draw,
                text,
                (_TEXT_X, y + _DETAIL_Y_OFFSET),
                detail_font,
                max_width=layout.SIDEBAR_X - _TEXT_X,
            )

    @staticmethod
    def _draw_row_icon(
        draw: ImageDraw.ImageDraw, icon: str, row_y: int, icon_font: ImageFont.FreeTypeFont
    ) -> None:
        renderer.draw_icon_centered(
            draw, icon, (0, row_y, _ICON_ZONE_WIDTH, row_y + layout.ROW_HEIGHT), icon_font
        )

    @staticmethod
    def _network_icon(status: NetworkStatus) -> str:
        if status.is_hotspot_active:
            return renderer.ICON_WIFI_TETHERING
        return renderer.ICON_WIFI if status.is_online else renderer.ICON_WIFI_OFF

    @staticmethod
    def _connection_label(status: NetworkStatus) -> str:
        """Associated is not the same as online — a router with a dead uplink
        still hands out an address, and that is worth saying out loud."""
        if status.is_hotspot_active:
            return copy.WIFI_HOTSPOT_ACTIVE
        return copy.WIFI_CONNECTED if status.is_online else copy.WIFI_NO_INTERNET
