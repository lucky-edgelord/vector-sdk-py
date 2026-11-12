"""``Modal`` and ``TextInput``: Discord's forms, asked as a short chat conversation.

``await interaction.response.send_modal(MyModal())`` (or ``await modal.ask(ctx)``) posts each
field as a question and waits for the user's reply, then calls ``on_submit``. Replying
``cancel`` aborts. Optional fields can be skipped with ``skip``.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional

from .interaction import Interaction, InteractionType
from .view import Item

if TYPE_CHECKING:
    pass

_log = logging.getLogger("vector.ui")

__all__ = ("Modal", "TextInput", "TextStyle")


class TextStyle:
    short = 1
    paragraph = 2
    long = 2


class TextInput(Item):
    def __init__(self, *, label: str, style: int = TextStyle.short, custom_id: Optional[str] = None,
                 placeholder: Optional[str] = None, default: Optional[str] = None, required: bool = True,
                 min_length: Optional[int] = None, max_length: Optional[int] = None, row: Optional[int] = None):
        super().__init__()
        self.label = label
        self.style = style
        if custom_id:
            self.custom_id = custom_id
        self.placeholder = placeholder
        self.default = default
        self.required = required
        self.min_length = min_length
        self.max_length = max_length
        self._value: Optional[str] = default
        self._row = row

    @property
    def value(self) -> str:
        return self._value or ""

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"<TextInput label={self.label!r} value={self._value!r}>"


class Modal:
    title: str = ""
    __modal_items__: ClassVar[List[str]] = []

    def __init_subclass__(cls, *, title: Optional[str] = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if title is not None:
            cls.title = title
        names: List[str] = []
        for base in reversed(cls.__mro__):
            for name, member in base.__dict__.items():
                if isinstance(member, TextInput) and name not in names:
                    names.append(name)
        cls.__modal_items__ = names

    def __init__(self, *, title: Optional[str] = None, timeout: Optional[float] = 300.0, custom_id: Optional[str] = None):
        import copy

        if title is not None:
            self.title = title
        self.timeout = timeout
        self.custom_id = custom_id
        self._children: List[TextInput] = []
        for name in self.__modal_items__:
            item = copy.copy(getattr(type(self), name))
            setattr(self, name, item)
            self._children.append(item)

    @property
    def children(self) -> List[TextInput]:
        return list(self._children)

    def add_item(self, item: TextInput) -> "Modal":
        self._children.append(item)
        return self

    async def on_submit(self, interaction: Interaction, /) -> None:
        pass

    async def on_error(self, interaction: Interaction, error: Exception, /) -> None:
        _log.error("Ignoring exception in modal %r", self, exc_info=error)

    async def on_timeout(self) -> None:
        pass

    async def interaction_check(self, interaction: Interaction, /) -> bool:
        return True

    async def ask(self, ctx: Any) -> bool:
        """Run the modal from a command context. Returns True if submitted."""
        interaction = Interaction(client=ctx.bot, user=ctx.author, message=ctx.message, channel=ctx.channel)
        return await self._run(interaction)

    async def _run(self, interaction: Interaction) -> bool:
        client = interaction.client
        user = interaction.user
        channel = interaction.channel
        npub = getattr(user, "npub", None)
        header = f"**{self.title}**\n" if self.title else ""
        for i, field in enumerate(self._children):
            hint = []
            if field.placeholder:
                hint.append(f"*{field.placeholder}*")
            if not field.required:
                hint.append("reply `skip` to leave it empty")
            if field.max_length:
                hint.append(f"max {field.max_length} characters")
            prompt = f"{header if i == 0 else ''}{user.mention if hasattr(user, 'mention') else ''} **{field.label}**"
            if hint:
                prompt += "\n-# " + " · ".join(hint) + " · `cancel` to stop"
            await channel.send(prompt)

            def check(m: Any) -> bool:
                return getattr(m.author, "npub", None) == npub and getattr(m.channel, "id", None) == getattr(channel, "id", None)

            while True:
                try:
                    reply = await client.wait_for("message", check=check, timeout=self.timeout)
                except asyncio.TimeoutError:
                    await self.on_timeout()
                    return False
                text = reply.content.strip()
                if text.lower() == "cancel":
                    await channel.send("Cancelled.")
                    return False
                if text.lower() == "skip" and not field.required:
                    field._value = field.default or ""
                    break
                if field.min_length and len(text) < field.min_length:
                    await channel.send(f"That's too short (at least {field.min_length} characters). Try again:")
                    continue
                if field.max_length and len(text) > field.max_length:
                    await channel.send(f"That's too long (at most {field.max_length} characters). Try again:")
                    continue
                field._value = text
                break
        submit = Interaction(client=client, user=user, message=interaction.message, channel=channel,
                             data={"custom_id": self.custom_id, "components": {f.custom_id: f.value for f in self._children}},
                             type=InteractionType.modal_submit)
        try:
            if await self.interaction_check(submit):
                await self.on_submit(submit)
        except Exception as e:
            await self.on_error(submit, e)
        return True

    def __repr__(self) -> str:
        return f"<Modal title={self.title!r} fields={len(self._children)}>"
