from __future__ import annotations

from typing import Final

from PIL import Image

import display.renderer as renderer
import display.screens.list_layout as layout
from db.models import Episode, Feed
from display.events import BackRequested, EpisodeSelected, Event, ListScrolled, QueueToggled

_TITLE_FONT_SIZE: Final[int] = 12
_META_FONT_SIZE: Final[int] = 9
_TITLE_Y_OFFSET: Final[int] = 4
_META_Y_OFFSET: Final[int] = 21
_UNPLAYED_MARKER: Final[str] = "● "
_ACTION_ICON_SIZE: Final[int] = 18


class EpisodeListScreen:
    def __init__(
        self,
        feed: Feed,
        episodes: list[Episode],
        queued_episode_ids: set[int],
        scroll_offset: int = 0,
    ) -> None:
        self._feed = feed
        self._episodes = episodes
        self._queued_episode_ids = queued_episode_ids
        self._scroller = layout.ListScroller(len(episodes))
        self._scroller.scroll_to(scroll_offset)

    @property
    def scroll_offset(self) -> int:
        """Current scroll position, so a rebuilt screen can restore it."""
        return self._scroller.offset

    def render(self) -> Image.Image:
        image, draw = renderer.new_canvas()
        header_font = renderer.load_text_font(layout.HEADER_FONT_SIZE)
        title_font = renderer.load_text_font(_TITLE_FONT_SIZE)
        meta_font = renderer.load_text_font(_META_FONT_SIZE)
        action_font = renderer.load_icon_font(_ACTION_ICON_SIZE)

        layout.draw_header(
            draw,
            self._feed.name,
            header_font,
            show_back_icon=True,
            icon_font=renderer.load_icon_font(layout.HEADER_FONT_SIZE + 4),
        )

        if not self._episodes:
            draw.text(
                (6, layout.row_top(0) + _TITLE_Y_OFFSET),
                "No episodes",
                font=title_font,
                fill=renderer.BLACK,
            )
            return image

        visible = self._episodes[self._scroller.visible_slice()]
        for index, episode in enumerate(visible):
            y = layout.row_top(index)
            # Stop at the sidebar so row dividers don't cut through the chevrons
            renderer.draw_divider(draw, y, x_end=layout.SIDEBAR_X)

            marker = "" if episode.played else _UNPLAYED_MARKER
            renderer.draw_text_clipped(
                draw,
                marker + episode.title,
                (6, y + _TITLE_Y_OFFSET),
                title_font,
                max_width=layout.ACTION_X - 12,
            )
            if episode.published_at is not None:
                date_text = episode.published_at.strftime("%d %b %Y").lstrip("0")
                draw.text((6, y + _META_Y_OFFSET), date_text, font=meta_font, fill=renderer.BLACK)

            is_queued = episode.id in self._queued_episode_ids
            renderer.draw_icon_centered(
                draw,
                renderer.ICON_PLAYLIST_ADD_CHECK if is_queued else renderer.ICON_PLAYLIST_ADD,
                (layout.ACTION_X, y, layout.SIDEBAR_X, y + layout.ROW_HEIGHT),
                action_font,
            )

        layout.draw_sidebar(draw, self._scroller)
        return image

    def handle_touch(self, x: int, y: int) -> Event | None:
        if y < layout.HEADER_HEIGHT:
            return BackRequested()

        if layout.is_sidebar_touch(x, y):
            return ListScrolled() if self._scroller.handle_sidebar_touch(y) else None

        visible_row = layout.row_index_at(y)
        if visible_row is None:
            return None

        episode_index = self._scroller.offset + visible_row
        if episode_index >= len(self._episodes):
            return None

        episode = self._episodes[episode_index]
        if layout.is_action_zone_touch(x, y):
            return QueueToggled(episode)
        return EpisodeSelected(episode)
