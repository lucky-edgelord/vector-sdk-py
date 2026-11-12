"""Help commands: ``HelpCommand``, ``DefaultHelpCommand``, ``MinimalHelpCommand``, ``EmbedHelpCommand``.

The default renders with Vector markdown (bold names, code-formatted signatures) instead of
discord.py's code-block paginator, since Vector shows formatting natively.
"""

from __future__ import annotations

import copy
import functools
import inspect
import itertools
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from ...embeds import Embed
from ...utils import MISSING
from .core import Command, Group, GroupMixin
from .errors import CommandError

if TYPE_CHECKING:
    from .bot import BotBase
    from .cog import Cog
    from .context import Context

__all__ = ("HelpCommand", "DefaultHelpCommand", "MinimalHelpCommand", "EmbedHelpCommand", "Paginator")


class Paginator:
    """Splits long text into pages (kept for discord.py code that uses it)."""

    def __init__(self, prefix: Optional[str] = "```", suffix: Optional[str] = "```", max_size: int = 4000,
                 linesep: str = "\n"):
        self.prefix, self.suffix, self.max_size, self.linesep = prefix, suffix, max_size, linesep
        self.clear()

    def clear(self) -> None:
        self._current_page = [self.prefix] if self.prefix is not None else []
        self._count = len(self.prefix or "") + len(self.linesep) if self.prefix is not None else 0
        self._pages: List[str] = []

    def add_line(self, line: str = "", *, empty: bool = False) -> None:
        if self._count + len(line) + len(self.linesep) > self.max_size - len(self.suffix or ""):
            self.close_page()
        self._count += len(line) + len(self.linesep)
        self._current_page.append(line)
        if empty:
            self._current_page.append("")
            self._count += len(self.linesep)

    def close_page(self) -> None:
        if self.suffix is not None:
            self._current_page.append(self.suffix)
        self._pages.append(self.linesep.join(self._current_page))
        self._current_page = [self.prefix] if self.prefix is not None else []
        self._count = len(self.prefix or "") + len(self.linesep) if self.prefix is not None else 0

    @property
    def pages(self) -> List[str]:
        if len(self._current_page) > (0 if self.prefix is None else 1):
            current = list(self._current_page)
            if self.suffix is not None:
                current.append(self.suffix)
            return self._pages + [self.linesep.join(current)]
        return list(self._pages)


class _HelpCommandImpl(Command):
    def __init__(self, inject: "HelpCommand", *args: Any, **kwargs: Any):
        super().__init__(inject.command_callback, *args, **kwargs)
        self._original = inject
        self._injected = inject

    async def prepare(self, ctx: "Context", native_args: Any = None) -> None:
        self._injected = injected = self._original.copy()
        injected.context = ctx
        self.callback = injected.command_callback
        await super().prepare(ctx, native_args)

    async def _parse_native(self, ctx: "Context", native_args: Dict[str, Any]) -> None:
        ctx.args = [ctx]
        value = native_args.get("command")
        ctx.kwargs = {"command": value} if value else {}

    @property
    def params(self):  # type: ignore[override]
        return {k: v for k, v in list(self._raw_params.items())[1:]}

    @property
    def clean_params(self):  # type: ignore[override]
        return self.params

    async def __call__(self, context: "Context", /, *args: Any, **kwargs: Any) -> Any:
        return await self.callback(context, *args, **kwargs)


class HelpCommand:
    """Base help command. Override ``send_bot_help`` etc. exactly like discord.py."""

    MENTION_TRANSFORMS: Dict[str, str] = {}

    def __new__(cls, *args: Any, **kwargs: Any) -> "HelpCommand":
        self = super().__new__(cls)
        self.__original_kwargs__ = {k: copy.deepcopy(v) for k, v in kwargs.items()}
        self.__original_args__ = copy.deepcopy(args)
        return self

    def __init__(self, **options: Any):
        self.show_hidden: bool = options.pop("show_hidden", False)
        self.verify_checks: Optional[bool] = options.pop("verify_checks", True)
        self.command_attrs = attrs = options.pop("command_attrs", {})
        attrs.setdefault("name", "help")
        attrs.setdefault("help", "Shows this message")
        self.context: "Context" = MISSING
        self._command_impl = _HelpCommandImpl(self, **self.command_attrs)

    def copy(self) -> "HelpCommand":
        obj = self.__class__(*self.__original_args__, **self.__original_kwargs__)
        obj._command_impl = self._command_impl
        return obj

    def _add_to_bot(self, bot: "BotBase") -> None:
        command = _HelpCommandImpl(self, **self.command_attrs)
        bot.add_command(command)
        self._command_impl = command

    def _remove_from_bot(self, bot: "BotBase") -> None:
        bot.remove_command(self._command_impl.name)

    @property
    def cog(self) -> Optional["Cog"]:
        return self._command_impl.cog

    @cog.setter
    def cog(self, cog: Optional["Cog"]) -> None:
        self._command_impl.cog = cog

    @property
    def invoked_with(self) -> Optional[str]:
        return self.context.invoked_with if self.context is not MISSING else None

    def get_bot_mapping(self) -> Dict[Optional["Cog"], List[Command]]:
        bot = self.context.bot
        mapping: Dict[Optional["Cog"], List[Command]] = {cog: cog.get_commands() for cog in bot.cogs.values()}
        mapping[None] = [c for c in bot.commands if c.cog is None]
        return mapping

    def get_command_signature(self, command: Command, /) -> str:
        parent = command.full_parent_name
        alias = command.name if not command.aliases else f"[{command.name}|{'|'.join(command.aliases)}]"
        alias = f"{parent} {alias}" if parent else alias
        return f"{self.context.clean_prefix}{alias} {command.signature}".rstrip()

    def remove_mentions(self, string: str, /) -> str:
        return string

    async def filter_commands(self, commands: Iterable[Command], /, *, sort: bool = False,
                              key: Optional[Callable[[Command], Any]] = None) -> List[Command]:
        if sort and key is None:
            key = lambda c: c.name  # noqa: E731
        iterator = commands if self.show_hidden else filter(lambda c: not c.hidden, commands)
        if self.verify_checks is False:
            return sorted(iterator, key=key) if sort else list(iterator)  # type: ignore[arg-type]
        ret = []
        for cmd in iterator:
            try:
                if await cmd.can_run(self.context):
                    ret.append(cmd)
            except CommandError:
                pass
        if sort:
            ret.sort(key=key)  # type: ignore[arg-type]
        return ret

    def get_max_size(self, commands: Sequence[Command], /) -> int:
        return max((len(c.name) for c in commands), default=0)

    def get_destination(self) -> Any:
        return self.context.channel

    async def send_error_message(self, error: str, /) -> None:
        await self.get_destination().send(error)

    async def on_help_command_error(self, ctx: "Context", error: CommandError, /) -> None:
        pass

    def command_not_found(self, string: str, /) -> str:
        return f'No command called "{string}" found.'

    def subcommand_not_found(self, command: Command, string: str, /) -> str:
        if isinstance(command, Group) and len(command.all_commands) > 0:
            return f'Command "{command.qualified_name}" has no subcommand named {string}'
        return f'Command "{command.qualified_name}" has no subcommands.'

    async def send_bot_help(self, mapping: Mapping[Optional["Cog"], List[Command]], /) -> None:
        return None

    async def send_cog_help(self, cog: "Cog", /) -> None:
        return None

    async def send_group_help(self, group: Group, /) -> None:
        return None

    async def send_command_help(self, command: Command, /) -> None:
        return None

    async def prepare_help_command(self, ctx: "Context", command: Optional[str] = None, /) -> None:
        pass

    async def command_callback(self, ctx: "Context", /, *, command: Optional[str] = None) -> Any:
        await self.prepare_help_command(ctx, command)
        bot = ctx.bot
        if command is None:
            return await self.send_bot_help(self.get_bot_mapping())
        cog = bot.get_cog(command)
        if cog is not None:
            return await self.send_cog_help(cog)
        keys = command.split(" ")
        cmd = bot.all_commands.get(keys[0])
        if cmd is None:
            return await self.send_error_message(self.command_not_found(keys[0]))
        for key in keys[1:]:
            try:
                found = cmd.all_commands.get(key)  # type: ignore[union-attr]
            except AttributeError:
                return await self.send_error_message(self.subcommand_not_found(cmd, key))
            if found is None:
                return await self.send_error_message(self.subcommand_not_found(cmd, key))
            cmd = found
        if isinstance(cmd, Group):
            return await self.send_group_help(cmd)
        return await self.send_command_help(cmd)


class DefaultHelpCommand(HelpCommand):
    """Markdown help: commands grouped by cog, with signatures in code formatting."""

    def __init__(self, **options: Any):
        self.width: int = options.pop("width", 80)
        self.indent: int = options.pop("indent", 2)
        self.sort_commands: bool = options.pop("sort_commands", True)
        self.dm_help: Optional[bool] = options.pop("dm_help", False)
        self.dm_help_threshold: int = options.pop("dm_help_threshold", 1000)
        self.arguments_heading: str = options.pop("arguments_heading", "Arguments")
        self.commands_heading: str = options.pop("commands_heading", "Commands")
        self.default_argument_description: str = options.pop("default_argument_description", "No description given")
        self.no_category: str = options.pop("no_category", "No Category")
        self.show_parameter_descriptions: bool = options.pop("show_parameter_descriptions", True)
        self.paginator: Paginator = options.pop("paginator", None) or Paginator(prefix=None, suffix=None)
        super().__init__(**options)

    def get_ending_note(self) -> str:
        name = self.invoked_with
        p = self.context.clean_prefix
        return f"-# Type `{p}{name} command` for more info on a command."

    def _line(self, c: Command) -> str:
        doc = c.short_doc
        return f"`{self.context.clean_prefix}{c.qualified_name}` {('— ' + doc) if doc else ''}".rstrip()

    def add_command_arguments(self, command: Command, /) -> None:
        params = command.params.values()
        if not params:
            return
        self.paginator.add_line(f"**{self.arguments_heading}**")
        for p in params:
            desc = p.description or self.default_argument_description
            dd = p.displayed_default
            extra = f" (default: {dd})" if dd else ""
            self.paginator.add_line(f"• `{p.displayed_name}` — {desc}{extra}")

    async def send_pages(self) -> None:
        dest = self.get_destination()
        for page in self.paginator.pages:
            await dest.send(page)

    def get_destination(self) -> Any:
        ctx = self.context
        if self.dm_help is True:
            return ctx.author
        if self.dm_help is None and len(self.paginator.pages) > 0 and sum(len(p) for p in self.paginator.pages) > self.dm_help_threshold:
            return ctx.author
        return ctx.channel

    async def prepare_help_command(self, ctx: "Context", command: Optional[str] = None, /) -> None:
        self.paginator.clear()
        await super().prepare_help_command(ctx, command)

    async def send_bot_help(self, mapping: Mapping[Optional["Cog"], List[Command]], /) -> None:
        bot = self.context.bot
        if bot.description:
            self.paginator.add_line(bot.description, empty=True)

        def get_category(command: Command) -> str:
            cog = command.cog
            return cog.qualified_name if cog is not None else self.no_category

        filtered = await self.filter_commands(bot.commands, sort=True, key=lambda c: (get_category(c), c.name))
        for category, cmds in itertools.groupby(filtered, key=get_category):
            cmds = sorted(cmds, key=lambda c: c.name) if self.sort_commands else list(cmds)
            self.paginator.add_line(f"**{category}**")
            for c in cmds:
                self.paginator.add_line(self._line(c))
            self.paginator.add_line()
        self.paginator.add_line(self.get_ending_note())
        await self.send_pages()

    def add_command_formatting(self, command: Command, /) -> None:
        if command.description:
            self.paginator.add_line(command.description, empty=True)
        self.paginator.add_line(f"`{self.get_command_signature(command)}`", empty=True)
        if command.help:
            for line in command.help.splitlines():
                self.paginator.add_line(line)
            self.paginator.add_line()
        if self.show_parameter_descriptions:
            self.add_command_arguments(command)

    async def send_command_help(self, command: Command, /) -> None:
        self.add_command_formatting(command)
        self.paginator.close_page()
        await self.send_pages()

    async def send_group_help(self, group: Group, /) -> None:
        self.add_command_formatting(group)
        filtered = await self.filter_commands(group.commands, sort=self.sort_commands)
        if filtered:
            self.paginator.add_line(f"**{self.commands_heading}**")
            for c in filtered:
                self.paginator.add_line(self._line(c))
            self.paginator.add_line()
            self.paginator.add_line(self.get_ending_note())
        await self.send_pages()

    async def send_cog_help(self, cog: "Cog", /) -> None:
        if cog.description:
            self.paginator.add_line(cog.description, empty=True)
        filtered = await self.filter_commands(cog.get_commands(), sort=self.sort_commands)
        self.paginator.add_line(f"**{cog.qualified_name} {self.commands_heading}**")
        for c in filtered:
            self.paginator.add_line(self._line(c))
        self.paginator.add_line()
        self.paginator.add_line(self.get_ending_note())
        await self.send_pages()


class MinimalHelpCommand(DefaultHelpCommand):
    """A compact one-line-per-category variant."""

    async def send_bot_help(self, mapping: Mapping[Optional["Cog"], List[Command]], /) -> None:
        bot = self.context.bot
        p = self.context.clean_prefix
        filtered = await self.filter_commands(bot.commands, sort=True)
        groups: Dict[str, List[str]] = {}
        for c in filtered:
            groups.setdefault(c.cog.qualified_name if c.cog else self.no_category, []).append(f"`{c.name}`")
        for cat, names in sorted(groups.items()):
            self.paginator.add_line(f"**{cat}** {' '.join(names)}")
        self.paginator.add_line()
        self.paginator.add_line(self.get_ending_note())
        await self.send_pages()


class EmbedHelpCommand(DefaultHelpCommand):
    """Help as an :class:`vector.Embed`, one field per category."""

    def __init__(self, *, colour: Any = 0x5865F2, **options: Any):
        self.colour = colour
        super().__init__(**options)

    async def send_bot_help(self, mapping: Mapping[Optional["Cog"], List[Command]], /) -> None:
        bot = self.context.bot
        embed = Embed(title="Help", description=bot.description or None, colour=self.colour)
        filtered = await self.filter_commands(bot.commands, sort=True)
        groups: Dict[str, List[Command]] = {}
        for c in filtered:
            groups.setdefault(c.cog.qualified_name if c.cog else self.no_category, []).append(c)
        for cat, cmds in sorted(groups.items()):
            embed.add_field(name=cat, value="\n".join(self._line(c) for c in cmds), inline=False)
        embed.set_footer(text=f"{self.context.clean_prefix}{self.invoked_with} <command> for more")
        await self.get_destination().send(embed=embed)

    async def send_command_help(self, command: Command, /) -> None:
        embed = Embed(title=self.get_command_signature(command), description=command.help or command.description or None,
                      colour=self.colour)
        for p in command.params.values():
            embed.add_field(name=p.displayed_name, value=p.description or self.default_argument_description, inline=True)
        await self.get_destination().send(embed=embed)
