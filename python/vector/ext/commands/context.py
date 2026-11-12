"""``Context``: everything about one command invocation."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from ...abc import Messageable
from ...utils import MISSING
from .core import StringView

if TYPE_CHECKING:
    from ...community import Community
    from ...message import Message
    from ...user import Member, User
    from .bot import Bot
    from .cog import Cog
    from .core import Command, Parameter

__all__ = ("Context",)


class Context(Messageable):
    """Passed as the first argument to every command, exactly like discord.py's ``ctx``."""

    def __init__(self, *, message: "Message", bot: "Bot", view: StringView, args: List[Any] = MISSING,
                 kwargs: Dict[str, Any] = MISSING, prefix: Optional[str] = None, command: Optional["Command"] = None,
                 invoked_with: Optional[str] = None, invoked_parents: List[str] = MISSING,
                 invoked_subcommand: Optional["Command"] = None, subcommand_passed: Optional[str] = None,
                 command_failed: bool = False, current_parameter: Optional["Parameter"] = None,
                 native_args: Optional[Dict[str, Any]] = None):
        self.message = message
        self.bot = bot
        self.args = args or []
        self.kwargs = kwargs or {}
        self.prefix = prefix
        self.command = command
        self.view = view
        self.invoked_with = invoked_with
        self.invoked_parents = invoked_parents or []
        self.invoked_subcommand = invoked_subcommand
        self.subcommand_passed = subcommand_passed
        self.command_failed = command_failed
        self.current_parameter = current_parameter
        self.current_argument: Optional[str] = None
        self.interaction = None
        self._native_args = native_args
        self._attachment_cursor = 0
        self._state = message._state

    # -- discord.py surface ---------------------------------------------------------------

    async def _get_channel_target(self):
        return await self.channel._get_channel_target()

    @property
    def is_slash(self) -> bool:
        """True when invoked through Vector's native ``/`` command picker."""
        return self.prefix == "/" and self.command is not None and self.command.slash

    @property
    def valid(self) -> bool:
        return self.prefix is not None and self.command is not None

    @property
    def clean_prefix(self) -> str:
        return self.prefix or ""

    @property
    def cog(self) -> Optional["Cog"]:
        return self.command.cog if self.command is not None else None

    @property
    def author(self) -> Union["User", "Member"]:
        return self.message.author

    @property
    def channel(self) -> Any:
        return self.message.channel

    @property
    def community(self) -> Optional["Community"]:
        return self.message.community

    guild = community

    @property
    def me(self) -> Any:
        c = self.community
        return c.me if c is not None else self.bot.user

    @property
    def voice_client(self) -> Any:
        c = self.community
        return c.voice_client if c is not None else None

    @property
    def permissions(self) -> Any:
        perms = getattr(self.channel, "permissions_for", None)
        return perms(self.author) if perms else None

    @property
    def bot_permissions(self) -> Any:
        perms = getattr(self.channel, "permissions_for", None)
        return perms(self.me) if perms else None

    @property
    def filesize_limit(self) -> int:
        return 100 * 1024 * 1024

    async def reply(self, content: Optional[Any] = None, **kwargs: Any) -> "Message":
        return await self.send(content, reference=self.message, **kwargs)

    async def defer(self, *, ephemeral: bool = False) -> None:
        await self.trigger_typing()

    async def react(self, emoji: Any) -> None:
        """Vector extra: react to the invoking message."""
        await self.message.add_reaction(emoji)

    async def invoke(self, command: "Command", /, *args: Any, **kwargs: Any) -> Any:
        return await command(self, *args, **kwargs)

    async def reinvoke(self, *, call_hooks: bool = False, restart: bool = True) -> None:
        cmd = self.command
        view = self.view
        if cmd is None:
            raise ValueError("This context is not valid.")
        index, previous = view.index, view.previous
        invoked_with = self.invoked_with
        invoked_subcommand = self.invoked_subcommand
        invoked_parents = self.invoked_parents
        subcommand_passed = self.subcommand_passed
        if restart:
            to_call = cmd.root_parent or cmd
            view.index = len(self.prefix or "")
            view.previous = 0
            self.invoked_parents = []
            self.invoked_with = view.get_word()
        else:
            to_call = cmd
        try:
            await to_call.reinvoke(self, call_hooks=call_hooks)
        finally:
            self.command = cmd
            view.index, view.previous = index, previous
            self.invoked_with = invoked_with
            self.invoked_subcommand = invoked_subcommand
            self.invoked_parents = invoked_parents
            self.subcommand_passed = subcommand_passed

    async def send_help(self, *args: Any) -> Any:
        bot = self.bot
        cmd = bot.help_command
        if cmd is None:
            return None
        cmd = cmd.copy()
        cmd.context = self
        if len(args) == 0:
            await cmd.prepare_help_command(self, None)
            mapping = cmd.get_bot_mapping()
            injected = cmd.send_bot_help
            try:
                return await injected(mapping)
            except Exception as e:
                await cmd.on_help_command_error(self, e)
                return None
        entity = args[0]
        if isinstance(entity, str):
            entity = bot.get_cog(entity) or bot.get_command(entity)
        if entity is None:
            return None
        from .cog import Cog
        from .core import Group

        await cmd.prepare_help_command(self, getattr(entity, "qualified_name", None))
        try:
            if isinstance(entity, Cog):
                return await cmd.send_cog_help(entity)
            if isinstance(entity, Group):
                return await cmd.send_group_help(entity)
            return await cmd.send_command_help(entity)
        except Exception as e:
            await cmd.on_help_command_error(self, e)
            return None

    def __repr__(self) -> str:
        return f"<Context command={getattr(self.command, 'qualified_name', None)!r} author={getattr(self.author, 'name', None)!r}>"
