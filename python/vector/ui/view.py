"""``View``, ``Button``, ``Select``: Discord components rebuilt from reactions.

A view's items are listed under the message as a legend, and the bot adds one reaction per
clickable item. Reacting with that emoji "clicks" it; removing your reaction clicks it again,
so a button can be pressed repeatedly by toggling. Callbacks get an :class:`Interaction`.

    class Confirm(ui.View):
        @ui.button(label="Confirm", emoji="✅", style=ui.ButtonStyle.success)
        async def confirm(self, interaction, button):
            await interaction.response.send_message("Confirmed!")
            self.stop()

    await ctx.send("Are you sure?", view=Confirm())
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Coroutine, Dict, List, Optional, Sequence, Tuple, Type, TypeVar

from .interaction import Interaction

if TYPE_CHECKING:
    from ..message import Message

_log = logging.getLogger("vector.ui")

__all__ = ("View", "Item", "Button", "ButtonStyle", "Select", "SelectOption", "button", "select", "Paginator",
           "LETTER_EMOJI", "NUMBER_EMOJI")

LETTER_EMOJI = [chr(0x1F1E6 + i) for i in range(26)]  # 🇦 … 🇿
NUMBER_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


class ButtonStyle:
    primary = 1
    secondary = 2
    success = 3
    danger = 4
    link = 5
    premium = 6
    blurple = primary
    grey = secondary
    gray = secondary
    green = success
    red = danger
    url = link


_STYLE_COLOUR = {ButtonStyle.primary: "#5865f2", ButtonStyle.success: "#57f287", ButtonStyle.danger: "#ed4245"}


class Item:
    """Base for anything a View holds."""

    _view: Optional["View"]

    def __init__(self) -> None:
        self._view = None
        self._row: Optional[int] = None
        self.custom_id: str = os.urandom(8).hex()
        self.disabled: bool = False
        self._callback: Optional[Callable[..., Coroutine[Any, Any, Any]]] = None

    @property
    def view(self) -> Optional["View"]:
        return self._view

    @property
    def row(self) -> Optional[int]:
        return self._row

    @row.setter
    def row(self, value: Optional[int]) -> None:
        self._row = value

    @property
    def width(self) -> int:
        return 1

    def is_dispatchable(self) -> bool:
        return True

    def is_persistent(self) -> bool:
        return True

    def _emojis(self) -> List[str]:
        return []

    def _legend(self) -> str:
        return ""

    async def callback(self, interaction: Interaction) -> Any:
        if self._callback is not None:
            return await self._callback(interaction)

    async def _click(self, interaction: Interaction, emoji: str) -> None:
        await self.callback(interaction)


class Button(Item):
    def __init__(self, *, style: int = ButtonStyle.secondary, label: Optional[str] = None, disabled: bool = False,
                 custom_id: Optional[str] = None, url: Optional[str] = None, emoji: Optional[Any] = None,
                 row: Optional[int] = None, sku_id: Any = None, id: Any = None):
        super().__init__()
        self.style = ButtonStyle.link if url else style
        self.label = label
        self.disabled = disabled
        self.url = url
        self.emoji: Optional[str] = str(emoji) if emoji is not None else None
        if custom_id:
            self.custom_id = custom_id
        self._row = row

    def _emojis(self) -> List[str]:
        if self.url or self.disabled or not self.emoji:
            return []
        return [self.emoji]

    def _legend(self) -> str:
        label = self.label or ""
        if self.url:
            text = f"🔗 [{label or self.url}]({self.url})"
            return text
        body = f"**{label}**" if label else ""
        colour = _STYLE_COLOUR.get(self.style)
        if colour and body and not self.disabled:
            body = f"<color {colour}>{body}</color>"
        text = f"{self.emoji} {body}".strip()
        return f"~~{text}~~" if self.disabled else text

    def __repr__(self) -> str:
        return f"<Button label={self.label!r} emoji={self.emoji!r} style={self.style}>"


class SelectOption:
    def __init__(self, *, label: str, value: Optional[str] = None, description: Optional[str] = None,
                 emoji: Optional[Any] = None, default: bool = False):
        self.label = label
        self.value = value if value is not None else label
        self.description = description
        self.emoji: Optional[str] = str(emoji) if emoji is not None else None
        self.default = default

    def __repr__(self) -> str:
        return f"<SelectOption label={self.label!r} value={self.value!r}>"


class Select(Item):
    """A menu: each option is a numbered reaction (1️⃣ 2️⃣ 3️⃣ …) unless it has its own emoji."""

    def __init__(self, *, custom_id: Optional[str] = None, placeholder: Optional[str] = None, min_values: int = 1,
                 max_values: int = 1, options: Optional[Sequence[SelectOption]] = None, disabled: bool = False,
                 row: Optional[int] = None, **ignored: Any):
        super().__init__()
        if custom_id:
            self.custom_id = custom_id
        self.placeholder = placeholder
        self.min_values = min_values
        self.max_values = max_values
        self.options: List[SelectOption] = list(options or [])
        self.disabled = disabled
        self._row = row
        self._selected: Dict[str, List[str]] = {}
        self._last_user: Optional[str] = None

    def add_option(self, *, label: str, value: Optional[str] = None, description: Optional[str] = None,
                   emoji: Optional[Any] = None, default: bool = False) -> None:
        self.options.append(SelectOption(label=label, value=value, description=description, emoji=emoji, default=default))

    def append_option(self, option: SelectOption) -> None:
        self.options.append(option)

    def _option_emoji(self, i: int, opt: SelectOption) -> str:
        return opt.emoji or (NUMBER_EMOJI[i] if i < len(NUMBER_EMOJI) else LETTER_EMOJI[i - len(NUMBER_EMOJI)])

    def _emojis(self) -> List[str]:
        if self.disabled:
            return []
        return [self._option_emoji(i, o) for i, o in enumerate(self.options)]

    def _legend(self) -> str:
        lines = []
        if self.placeholder:
            lines.append(f"**{self.placeholder}**")
        for i, o in enumerate(self.options):
            line = f"{self._option_emoji(i, o)} {o.label}"
            if o.description:
                line += f" — *{o.description}*"
            lines.append(f"~~{line}~~" if self.disabled else line)
        return "\n".join(lines)

    @property
    def values(self) -> List[str]:
        """What the clicking user has selected (toggle reactions to add/remove with ``max_values > 1``)."""
        return list(self._selected.get(self._last_user or "", []))

    async def _click(self, interaction: Interaction, emoji: str) -> None:
        for i, o in enumerate(self.options):
            if self._option_emoji(i, o) == emoji:
                uid = getattr(interaction.user, "npub", "")
                chosen = self._selected.setdefault(uid, [])
                if self.max_values <= 1:
                    chosen[:] = [o.value]
                elif o.value in chosen:
                    chosen.remove(o.value)
                elif len(chosen) < self.max_values:
                    chosen.append(o.value)
                self._last_user = uid
                interaction.data = {"custom_id": self.custom_id, "values": list(chosen)}
                await self.callback(interaction)
                return

    def __repr__(self) -> str:
        return f"<Select placeholder={self.placeholder!r} options={len(self.options)}>"


# discord.py also has these; on Vector they're plain selects over what the bot can see.
UserSelect = RoleSelect = ChannelSelect = MentionableSelect = Select

V = TypeVar("V", bound="View")


def button(*, label: Optional[str] = None, custom_id: Optional[str] = None, disabled: bool = False,
           style: int = ButtonStyle.secondary, emoji: Optional[Any] = None, row: Optional[int] = None,
           **ignored: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate ``async def cb(self, interaction, button)`` in a View subclass."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("button function must be a coroutine function")
        func.__vector_ui_item__ = (Button, dict(label=label, custom_id=custom_id, disabled=disabled, style=style,  # type: ignore[attr-defined]
                                                emoji=emoji, row=row))
        return func

    return decorator


def select(*, cls: Type[Select] = Select, options: Sequence[SelectOption] = (), placeholder: Optional[str] = None,
           custom_id: Optional[str] = None, min_values: int = 1, max_values: int = 1, disabled: bool = False,
           row: Optional[int] = None, **ignored: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate ``async def cb(self, interaction, select)`` in a View subclass."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("select function must be a coroutine function")
        func.__vector_ui_item__ = (cls, dict(options=list(options), placeholder=placeholder, custom_id=custom_id,  # type: ignore[attr-defined]
                                             min_values=min_values, max_values=max_values, disabled=disabled, row=row))
        return func

    return decorator


class View:
    """A set of reaction-buttons and selects attached to one message."""

    __view_children_items__: ClassVar[List[Callable[..., Any]]] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        items: Dict[str, Callable[..., Any]] = {}
        for base in reversed(cls.__mro__):
            for name, member in base.__dict__.items():
                if hasattr(member, "__vector_ui_item__"):
                    items[name] = member
        cls.__view_children_items__ = list(items.values())

    def __init__(self, *, timeout: Optional[float] = 180.0):
        self.timeout = timeout
        self._children: List[Item] = []
        for func in self.__view_children_items__:
            item_cls, kwargs = func.__vector_ui_item__
            item = item_cls(**{k: v for k, v in kwargs.items()})
            bound = func.__get__(self, type(self))

            async def cb(interaction: Interaction, _bound=bound, _item=item) -> Any:
                return await _bound(interaction, _item)

            item._callback = cb
            item._view = self
            self._children.append(item)
            setattr(self, func.__name__, item)
        self._assign_default_emoji()
        self.message: Optional["Message"] = None
        self._stopped: Optional[asyncio.Future] = None
        self._timeout_task: Optional[asyncio.Task] = None
        self._deadline: Optional[float] = None

    # -- children --------------------------------------------------------------------------

    def _assign_default_emoji(self) -> None:
        used = {e for c in self._children for e in ([c.emoji] if isinstance(c, Button) and c.emoji else [])}
        letters = (e for e in LETTER_EMOJI if e not in used)
        for c in self._children:
            if isinstance(c, Button) and not c.emoji and not c.url:
                c.emoji = next(letters)

    @property
    def children(self) -> List[Item]:
        return list(self._children)

    def add_item(self, item: Item) -> "View":
        item._view = self
        self._children.append(item)
        self._assign_default_emoji()
        return self

    def remove_item(self, item: Item) -> "View":
        try:
            self._children.remove(item)
        except ValueError:
            pass
        return self

    def clear_items(self) -> "View":
        self._children.clear()
        return self

    def find_item(self, custom_id: str) -> Optional[Item]:
        return next((c for c in self._children if c.custom_id == custom_id), None)

    # -- rendering -------------------------------------------------------------------------

    def _legend(self) -> str:
        rows: Dict[int, List[str]] = {}
        blocks: List[str] = []
        for i, c in enumerate(self._children):
            text = c._legend()
            if not text:
                continue
            if isinstance(c, Select):
                blocks.append(text)
            else:
                rows.setdefault(c.row if c.row is not None else 0, []).append(text)
        lines = ["   ".join(rows[r]) for r in sorted(rows)]
        return "\n".join(lines + blocks)

    # -- lifecycle -------------------------------------------------------------------------

    async def _start(self, message: "Message", *, add_reactions: bool = True) -> None:
        self.message = message
        state = message._state
        state._views[message.id] = self
        if self._stopped is None or self._stopped.done():
            self._stopped = asyncio.get_running_loop().create_future()
        if add_reactions:
            existing = {r.emoji for r in getattr(message, "reactions", []) if r.me}
            for c in self._children:
                for e in c._emojis():
                    if e in existing:
                        continue
                    try:
                        await message.add_reaction(e)
                    except Exception:
                        _log.debug("could not add reaction %s", e, exc_info=True)
        self._refresh_timeout()

    def _refresh_timeout(self) -> None:
        if self.timeout is None:
            return
        self._deadline = time.monotonic() + self.timeout
        if self._timeout_task is None or self._timeout_task.done():
            self._timeout_task = asyncio.ensure_future(self._timeout_loop())

    async def _timeout_loop(self) -> None:
        while self._deadline is not None:
            delay = self._deadline - time.monotonic()
            if delay <= 0:
                break
            await asyncio.sleep(delay)
        if self.is_finished():
            return
        try:
            await self.on_timeout()
        except Exception as e:
            _log.exception("on_timeout failed", exc_info=e)
        self._finish()

    def _finish(self) -> None:
        if self.message is not None:
            self.message._state._views.pop(self.message.id, None)
        if self._stopped is not None and not self._stopped.done():
            self._stopped.set_result(self.is_finished_by_timeout())
        self._deadline = None

    def is_finished_by_timeout(self) -> bool:
        return self._deadline is not None and time.monotonic() >= self._deadline

    async def _dispatch_reaction(self, emoji: str, user: Any, message: "Message") -> None:
        for item in self._children:
            if emoji in item._emojis():
                client = message._state.client
                interaction = Interaction(client=client, user=user, message=message, channel=message.channel,
                                          view=self, item=item, data={"custom_id": item.custom_id})
                try:
                    allow = await self.interaction_check(interaction)
                    if not allow:
                        return
                    self._refresh_timeout()
                    await item._click(interaction, emoji)
                except Exception as e:
                    await self.on_error(interaction, e, item)
                return

    async def interaction_check(self, interaction: Interaction, /) -> bool:
        """Return False to ignore a click (e.g. from someone other than the command author)."""
        return True

    async def on_timeout(self) -> None:
        pass

    async def on_error(self, interaction: Interaction, error: Exception, item: Item, /) -> None:
        _log.error("Ignoring exception in view %r for item %r", self, item, exc_info=error)

    def stop(self) -> None:
        self._deadline = None
        if self._timeout_task is not None:
            self._timeout_task.cancel()
        if self.message is not None:
            self.message._state._views.pop(self.message.id, None)
        if self._stopped is not None and not self._stopped.done():
            self._stopped.set_result(False)

    def is_finished(self) -> bool:
        return self._stopped is not None and self._stopped.done()

    def is_dispatching(self) -> bool:
        return self.message is not None and not self.is_finished()

    def is_persistent(self) -> bool:
        return self.timeout is None

    async def wait(self) -> bool:
        """Wait until the view stops; True if it timed out."""
        if self._stopped is None:
            self._stopped = asyncio.get_running_loop().create_future()
        return await self._stopped

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} timeout={self.timeout} children={len(self._children)}>"


class Paginator(View):
    """Pages of text/embeds with ⏮ ◀ ▶ ⏭ ⏹ reaction controls.

        pages = [vector.Embed(title=f"Page {i}") for i in range(1, 6)]
        await ui.Paginator(pages, author=ctx.author).start(ctx)
    """

    def __init__(self, pages: Sequence[Any], *, timeout: Optional[float] = 180.0, author: Any = None,
                 show_page_numbers: bool = True):
        super().__init__(timeout=timeout)
        if not pages:
            raise ValueError("Paginator needs at least one page")
        self.pages = list(pages)
        self.index = 0
        self.author = author
        self.show_page_numbers = show_page_numbers
        for emoji, step in (("⏮️", "first"), ("◀️", "prev"), ("▶️", "next"), ("⏭️", "last"), ("⏹️", "stop")):
            b = Button(emoji=emoji)
            b._callback = self._make_cb(step)
            self.add_item(b)

    def _render(self) -> Dict[str, Any]:
        from ..embeds import Embed

        page = self.pages[self.index]
        counter = f"-# Page {self.index + 1}/{len(self.pages)}" if self.show_page_numbers and len(self.pages) > 1 else None
        if isinstance(page, Embed):
            return {"content": counter, "embed": page}
        text = str(page) + (f"\n\n{counter}" if counter else "")
        return {"content": text, "embed": None}

    def _legend(self) -> str:
        return ""

    def _make_cb(self, step: str):
        async def cb(interaction: Interaction) -> None:
            if step == "stop":
                self.stop()
                return
            last = len(self.pages) - 1
            self.index = {"first": 0, "prev": max(0, self.index - 1), "next": min(last, self.index + 1), "last": last}[step]
            await interaction.response.edit_message(**self._render())

        return cb

    async def interaction_check(self, interaction: Interaction, /) -> bool:
        return self.author is None or getattr(interaction.user, "npub", None) == getattr(self.author, "npub", self.author)

    async def start(self, destination: Any) -> "Message":
        r = self._render()
        return await destination.send(r["content"], embed=r["embed"], view=self)
