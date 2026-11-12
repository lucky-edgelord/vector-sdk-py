"""A port of the most used parts of ``discord.ext.menus``: ``ListPageSource`` and ``MenuPages``.

    class Pages(menus.ListPageSource):
        def __init__(self, data):
            super().__init__(data, per_page=10)

        async def format_page(self, menu, entries):
            return vector.Embed(title=f"Page {menu.current_page + 1}", description="\\n".join(entries))

    await menus.MenuPages(Pages(items), timeout=60.0).start(ctx)

Controls are reactions (⏮ ◀ ▶ ⏭ ⏹), exactly like :class:`vector.ui.Paginator`.
"""
from __future__ import annotations

import inspect
import math
from typing import Any, Dict, Optional, Sequence

from ...ui.view import Button, View
from ...ui.interaction import Interaction

__all__ = ("PageSource", "ListPageSource", "Menu", "MenuPages", "MenuError", "CannotAddReactions",
           "CannotEmbedLinks", "CannotReadMessageHistory", "First", "Last")


class MenuError(Exception):
    pass


class CannotAddReactions(MenuError):
    pass


class CannotEmbedLinks(MenuError):
    pass


class CannotReadMessageHistory(MenuError):
    pass


class First:
    def __init__(self, number: int):
        self.number = number


class Last:
    def __init__(self, number: int = 0):
        self.number = number


class PageSource:
    async def _prepare_once(self) -> None:
        if not getattr(self, "_prepared", False):
            await self.prepare()
            self._prepared = True

    async def prepare(self) -> None:
        return

    def is_paginating(self) -> bool:
        raise NotImplementedError

    def get_max_pages(self) -> Optional[int]:
        return None

    async def get_page(self, page_number: int) -> Any:
        raise NotImplementedError

    async def format_page(self, menu: "Menu", page: Any) -> Any:
        raise NotImplementedError


class ListPageSource(PageSource):
    def __init__(self, entries: Sequence[Any], *, per_page: int):
        self.entries = entries
        self.per_page = per_page
        pages, left_over = divmod(len(entries), per_page)
        if left_over:
            pages += 1
        self._max_pages = pages

    def is_paginating(self) -> bool:
        return len(self.entries) > self.per_page

    def get_max_pages(self) -> int:
        return self._max_pages

    async def get_page(self, page_number: int) -> Any:
        if self.per_page == 1:
            return self.entries[page_number]
        base = page_number * self.per_page
        return self.entries[base:base + self.per_page]


class Menu(View):
    def __init__(self, *, timeout: Optional[float] = 180.0, delete_message_after: bool = False,
                 clear_reactions_after: bool = False, check_embeds: bool = False, message: Any = None):
        super().__init__(timeout=timeout)
        self.delete_message_after = delete_message_after
        self.clear_reactions_after = clear_reactions_after
        self.check_embeds = check_embeds
        self.message = message
        self.ctx: Any = None
        self.bot: Any = None
        self._author: Any = None

    def should_add_reactions(self) -> bool:
        return True

    async def interaction_check(self, interaction: Interaction, /) -> bool:
        return self.ctx is None or getattr(interaction.user, "npub", None) == getattr(self._author, "npub", None)

    async def send_initial_message(self, ctx: Any, channel: Any) -> Any:
        raise NotImplementedError

    async def start(self, ctx: Any, *, channel: Any = None, wait: bool = False) -> None:
        self.ctx = ctx
        self.bot = ctx.bot
        self._author = ctx.author
        channel = channel or ctx.channel
        self.message = await self.send_initial_message(ctx, channel)
        if wait:
            await self.wait()

    async def on_timeout(self) -> None:
        if self.delete_message_after and self.message is not None:
            try:
                await self.message.delete()
            except Exception:
                pass


class MenuPages(Menu):
    def __init__(self, source: PageSource, **kwargs: Any):
        super().__init__(**kwargs)
        self._source = source
        self.current_page = 0
        for emoji, name in (("⏮️", "go_to_first_page"), ("◀️", "go_to_previous_page"),
                            ("▶️", "go_to_next_page"), ("⏭️", "go_to_last_page"), ("⏹️", "stop_pages")):
            b = Button(emoji=emoji)
            b._callback = self._make_cb(name)
            self.add_item(b)

    @property
    def source(self) -> PageSource:
        return self._source

    async def change_source(self, source: PageSource) -> None:
        self._source = source
        self.current_page = 0
        if self.message is not None:
            await source._prepare_once()
            await self.show_page(0)

    async def _render(self, page_number: int) -> Dict[str, Any]:
        page = await self._source.get_page(page_number)
        value = await self._source.format_page(self, page)
        if inspect.isawaitable(value):
            value = await value
        return _kwargs_from(value)

    async def show_page(self, page_number: int) -> None:
        kwargs = await self._render(page_number)
        self.current_page = page_number
        await self.message.edit(**kwargs)

    async def show_checked_page(self, page_number: int) -> None:
        max_pages = self._source.get_max_pages()
        try:
            if max_pages is None or max_pages > page_number >= 0:
                await self.show_page(page_number)
        except IndexError:
            pass

    async def send_initial_message(self, ctx: Any, channel: Any) -> Any:
        await self._source._prepare_once()
        kwargs = await self._render(0)
        self.current_page = 0
        if self._source.is_paginating():
            kwargs["view"] = self
        return await channel.send(**kwargs)

    def _make_cb(self, name: str):
        async def cb(interaction: Interaction) -> None:
            if name == "stop_pages":
                self.stop()
                if self.delete_message_after and self.message is not None:
                    await self.message.delete()
                return
            last = (self._source.get_max_pages() or 1) - 1
            target = {"go_to_first_page": 0, "go_to_previous_page": self.current_page - 1,
                      "go_to_next_page": self.current_page + 1, "go_to_last_page": last}[name]
            if 0 <= target <= last:
                kwargs = await self._render(target)
                self.current_page = target
                await interaction.response.edit_message(**kwargs)

        return cb

    async def go_to_first_page(self, payload: Any = None) -> None:
        await self.show_page(0)

    async def go_to_previous_page(self, payload: Any = None) -> None:
        await self.show_checked_page(self.current_page - 1)

    async def go_to_next_page(self, payload: Any = None) -> None:
        await self.show_checked_page(self.current_page + 1)

    async def go_to_last_page(self, payload: Any = None) -> None:
        await self.show_page((self._source.get_max_pages() or 1) - 1)

    async def stop_pages(self, payload: Any = None) -> None:
        self.stop()


def _kwargs_from(value: Any) -> Dict[str, Any]:
    from ...embeds import Embed

    if isinstance(value, dict):
        return value
    if isinstance(value, Embed):
        return {"content": None, "embed": value}
    return {"content": str(value), "embed": None}
