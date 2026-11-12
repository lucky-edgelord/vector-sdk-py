"""``Interaction``: what a button/select callback receives, shaped like discord.py's."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, Optional

from ..utils import MISSING

if TYPE_CHECKING:
    from ..client import Client
    from ..message import Message
    from .modal import Modal
    from .view import Item, View

__all__ = ("Interaction", "InteractionResponse", "Followup", "InteractionType")


class InteractionType:
    component = "component"
    modal_submit = "modal_submit"
    application_command = "application_command"


class InteractionResponse:
    """``interaction.response``: reply to a click (once), edit the view's message, or open a modal."""

    def __init__(self, interaction: "Interaction"):
        self._parent = interaction
        self._done = False

    def is_done(self) -> bool:
        return self._done

    async def defer(self, *, ephemeral: bool = False, thinking: bool = False) -> None:
        self._done = True
        if thinking:
            await self._parent.channel.trigger_typing()

    async def pong(self) -> None:
        self._done = True

    async def send_message(self, content: Optional[Any] = None, *, embed: Any = None, embeds: Any = None,
                           file: Any = None, files: Any = None, view: Any = None, ephemeral: bool = False,
                           delete_after: Optional[float] = None, **ignored: Any) -> "Message":
        """Reply in the channel. ``ephemeral=True`` sends it to the user's DMs instead (only they see it)."""
        self._done = True
        target = self._parent.user if ephemeral else self._parent.channel
        kwargs: Dict[str, Any] = dict(embed=embed, embeds=embeds, file=file, files=files, view=view, delete_after=delete_after)
        if not ephemeral and self._parent.message is not None:
            kwargs["reference"] = self._parent.message
        msg = await target.send(content, **kwargs)
        self._parent._original = msg
        return msg

    async def edit_message(self, *, content: Optional[Any] = MISSING, embed: Any = MISSING, embeds: Any = MISSING,
                           view: Any = MISSING, **ignored: Any) -> Optional["Message"]:
        """Edit the message the view lives on (bot's own messages only)."""
        self._done = True
        msg = self._parent.message
        if msg is None:
            return None
        if view is MISSING and self._parent.view is not None:
            view = self._parent.view
        return await msg.edit(content=content, embed=embed, embeds=embeds, view=view)

    async def send_modal(self, modal: "Modal", /) -> None:
        """Ask the modal's questions in chat, then call ``modal.on_submit``."""
        self._done = True
        await modal._run(self._parent)


class Followup:
    def __init__(self, interaction: "Interaction"):
        self._parent = interaction

    async def send(self, content: Optional[Any] = None, *, ephemeral: bool = False, wait: bool = True, **kwargs: Any) -> "Message":
        target = self._parent.user if ephemeral else self._parent.channel
        return await target.send(content, **kwargs)


class Interaction:
    """A click on a reaction-button or select option."""

    def __init__(self, *, client: "Client", user: Any, message: Optional["Message"], channel: Any,
                 view: Optional["View"] = None, item: Optional["Item"] = None, data: Optional[Dict[str, Any]] = None,
                 type: str = InteractionType.component):
        self.client = client
        self.user = user
        self.message = message
        self.channel = channel
        self.view = view
        self.item = item
        self.data: Dict[str, Any] = data or {}
        self.type = type
        self.response = InteractionResponse(self)
        self.followup = Followup(self)
        self.command = None
        self.namespace = None
        self.locale = "en-US"
        self.guild_locale = "en-US"
        self.extras: Dict[str, Any] = {}
        self._original: Optional["Message"] = None
        self.created_at = getattr(message, "created_at", None)

    @property
    def id(self) -> str:
        return f"{getattr(self.message, 'id', '')}:{getattr(self.user, 'npub', '')}"

    @property
    def guild(self) -> Any:
        return getattr(self.channel, "community", None)

    community = guild

    @property
    def guild_id(self) -> Optional[str]:
        g = self.guild
        return g.id if g else None

    @property
    def channel_id(self) -> Optional[str]:
        return getattr(self.channel, "id", None)

    @property
    def permissions(self) -> Any:
        from ..permissions import Permissions

        perms = getattr(self.channel, "permissions_for", None)
        return perms(self.user) if perms else Permissions.all()

    def is_expired(self) -> bool:
        return False

    async def original_response(self) -> Optional["Message"]:
        return self._original or self.message

    async def edit_original_response(self, **kwargs: Any) -> Optional["Message"]:
        msg = self._original or self.message
        return await msg.edit(**kwargs) if msg else None

    async def delete_original_response(self) -> None:
        if self._original is not None:
            await self._original.delete()

    def __repr__(self) -> str:
        return f"<Interaction user={getattr(self.user, 'name', None)!r} item={self.item!r}>"
