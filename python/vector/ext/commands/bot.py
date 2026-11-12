"""``commands.Bot``: a :class:`vector.Client` with commands, cogs, extensions and checks."""

from __future__ import annotations

import asyncio
import collections
import importlib
import importlib.util
import inspect
import logging
import sys
import traceback
import types
from typing import (
    TYPE_CHECKING, Any, Callable, Coroutine, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Type, TypeVar,
    Union,
)

from ...client import Client
from ...utils import MISSING
from .cog import Cog
from .context import Context
from .core import Command, Group, GroupMixin, StringView
from .errors import (
    CheckFailure, CommandError, CommandNotFound, CommandRegistrationError, ExtensionAlreadyLoaded, ExtensionFailed,
    ExtensionNotFound, ExtensionNotLoaded, NoEntryPointError, UserInputError,
)
from .help import DefaultHelpCommand, HelpCommand

if TYPE_CHECKING:
    from ...message import Message

_log = logging.getLogger("vector.ext.commands")

__all__ = ("when_mentioned", "when_mentioned_or", "BotBase", "Bot", "AutoShardedBot")

CXT = TypeVar("CXT", bound=Context)


def when_mentioned(bot: "BotBase", msg: "Message", /) -> List[str]:
    """Prefix = mentioning the bot (``nostr:npub…``)."""
    npub = bot.npub or ""
    return [f"nostr:{npub} ", f"{npub} ", f"@{getattr(bot.user, 'name', '')} "]


def when_mentioned_or(*prefixes: str) -> Callable[["BotBase", "Message"], List[str]]:
    def inner(bot: "BotBase", msg: "Message") -> List[str]:
        r = list(prefixes)
        r = when_mentioned(bot, msg) + r
        return r

    return inner


class _DefaultRepr:
    def __repr__(self) -> str:
        return "<default-help-command>"


_default: Any = _DefaultRepr()


class BotBase(GroupMixin):
    def __init__(self, command_prefix: Any = "/", *, help_command: Optional[HelpCommand] = _default,
                 description: Optional[str] = None, owner_id: Optional[str] = None,
                 owner_ids: Optional[Iterable[str]] = None, strip_after_prefix: bool = False,
                 case_insensitive: bool = False, native_commands: bool = True, **options: Any):
        super().__init__(case_insensitive=case_insensitive, **options)
        self.command_prefix = command_prefix
        self.extra_events: Dict[str, List[Callable[..., Any]]] = getattr(self, "extra_events", {})
        self.__cogs: Dict[str, Cog] = {}
        self.__extensions: Dict[str, types.ModuleType] = {}
        self._checks: List[Callable[..., Any]] = []
        self._check_once: List[Callable[..., Any]] = []
        self._before_invoke: Optional[Callable[..., Any]] = None
        self._after_invoke: Optional[Callable[..., Any]] = None
        self._help_command: Optional[HelpCommand] = None
        self.description: str = inspect.cleandoc(description) if description else ""
        self.owner_id: Optional[str] = owner_id
        self.owner_ids: Set[str] = set(owner_ids or [])
        self.strip_after_prefix = strip_after_prefix
        self.native_commands = native_commands
        self._native_registered: Dict[str, str] = {}
        if self.owner_id and self.owner_ids:
            raise TypeError("Both owner_id and owner_ids are set.")
        if help_command is _default:
            self.help_command = DefaultHelpCommand()
        else:
            self.help_command = help_command
        from ... import app_commands

        self.tree = app_commands.CommandTree(self)

    # -- native slash registration --------------------------------------------------------

    def _on_command_added(self, command: Command) -> None:
        if getattr(self, "native", None) is not None:
            self._register_native(command)

    async def _on_native_ready(self) -> None:
        await super()._on_native_ready()  # type: ignore[misc]
        for command in list(self.commands):
            self._register_native(command)

    def _register_native(self, command: Command) -> None:
        if not self.native_commands or not command.slash or not command.enabled:
            return
        name = command.native_name()
        if name is None:
            _log.info("/%s isn't a valid Vector command name (lowercase a-z, 0-9, _ and -); prefix-only", command.name)
            return
        if name in self._native_registered:
            self._native_registered[name] = command.qualified_name
            return
        spec = command.native_args()
        if spec is None:
            _log.info("/%s's signature doesn't fit Vector's slash format; it works with the text prefix only", name)
            return
        description = (command.short_doc or command.description or command.name)[:200]
        try:
            self.native.register_command(name, description, spec)
            self._native_registered[name] = command.qualified_name
        except ValueError as e:
            _log.warning("could not publish /%s natively (%s); it still works as a prefix command", name, e)

    async def _handle_slash_command(self, name: str, args: Dict[str, Any], message: "Message") -> None:
        tree = getattr(self, "_app_tree", None)
        if tree is not None and await tree._dispatch(name, args, message):
            return
        qualified = self._native_registered.get(name, name)
        command = self.get_command(qualified) or self.get_command(name)
        self.dispatch("slash_command", name, args, message)
        if command is None:
            return
        ctx = Context(message=message, bot=self, view=StringView(""), prefix="/", invoked_with=name, native_args=dict(args))
        ctx.command = command
        await self.invoke(ctx)

    # -- events ---------------------------------------------------------------------------

    def dispatch(self, event_name: str, /, *args: Any, **kwargs: Any) -> None:
        super().dispatch(event_name, *args, **kwargs)  # type: ignore[misc]

    async def on_command_error(self, context: Context, exception: CommandError, /) -> None:
        """Default: print the traceback unless a handler exists (discord.py behaviour)."""
        if self.extra_events.get("on_command_error", None):
            return
        command = context.command
        if command and command.has_error_handler():
            return
        cog = context.cog
        if cog and cog.has_error_handler():
            return
        _log.error("Ignoring exception in command %s", command, exc_info=exception)

    async def on_message(self, message: "Message", /) -> None:
        await self.process_commands(message)

    # -- checks & hooks -------------------------------------------------------------------

    def check(self, func: Callable[..., Any], /) -> Callable[..., Any]:
        """A global check for every command: ``@bot.check``."""
        self.add_check(func)
        return func

    def add_check(self, func: Callable[..., Any], /, *, call_once: bool = False) -> None:
        if call_once:
            self._check_once.append(func)
        else:
            self._checks.append(func)

    def remove_check(self, func: Callable[..., Any], /, *, call_once: bool = False) -> None:
        lst = self._check_once if call_once else self._checks
        try:
            lst.remove(func)
        except ValueError:
            pass

    def check_once(self, func: Callable[..., Any], /) -> Callable[..., Any]:
        self.add_check(func, call_once=True)
        return func

    async def can_run(self, ctx: Context, /, *, call_once: bool = False) -> bool:
        data = self._check_once if call_once else self._checks
        for f in data:
            value = f(ctx)
            if inspect.isawaitable(value):
                value = await value
            if not value:
                return False
        return True

    async def is_owner(self, user: Any, /) -> bool:
        npub = getattr(user, "npub", user)
        if self.owner_id:
            return npub == self.owner_id
        if self.owner_ids:
            return npub in self.owner_ids
        _log.warning("is_owner(): no owner_id/owner_ids configured on the Bot, so nobody is the owner")
        return False

    def before_invoke(self, coro: Callable[..., Any], /) -> Callable[..., Any]:
        if not asyncio.iscoroutinefunction(coro):
            raise TypeError("The pre-invoke hook must be a coroutine.")
        self._before_invoke = coro
        return coro

    def after_invoke(self, coro: Callable[..., Any], /) -> Callable[..., Any]:
        if not asyncio.iscoroutinefunction(coro):
            raise TypeError("The post-invoke hook must be a coroutine.")
        self._after_invoke = coro
        return coro

    # -- listeners (name defaults from the function) --------------------------------------

    def add_listener(self, func: Callable[..., Any], /, name: str = MISSING) -> None:
        super().add_listener(func, name)  # type: ignore[misc]

    # -- cogs -----------------------------------------------------------------------------

    async def add_cog(self, cog: Cog, /, *, override: bool = False, guild: Any = MISSING, guilds: Any = MISSING) -> None:
        if not isinstance(cog, Cog):
            raise TypeError("cogs must derive from Cog")
        cog_name = cog.__cog_name__
        existing = self.__cogs.get(cog_name)
        if existing is not None:
            if not override:
                from ...errors import ClientException

                raise ClientException(f"Cog named {cog_name!r} already loaded")
            await self.remove_cog(cog_name)
        cog = await cog._inject(self, override=override, guild=guild, guilds=guilds)
        self.__cogs[cog_name] = cog

    def get_cog(self, name: str, /) -> Optional[Cog]:
        return self.__cogs.get(name)

    async def remove_cog(self, name: str, /, *, guild: Any = MISSING, guilds: Any = MISSING) -> Optional[Cog]:
        cog = self.__cogs.pop(name, None)
        if cog is None:
            return None
        help_command = self._help_command
        if help_command and help_command.cog is cog:
            help_command.cog = None
        await cog._eject(self, None)
        return cog

    @property
    def cogs(self) -> Mapping[str, Cog]:
        return types.MappingProxyType(self.__cogs)

    # -- extensions -----------------------------------------------------------------------

    async def _remove_module_references(self, name: str) -> None:
        for cogname, cog in self.__cogs.copy().items():
            if _is_submodule(name, cog.__module__):
                await self.remove_cog(cogname)
        for cmd in self.all_commands.copy().values():
            if cmd.module is not None and _is_submodule(name, cmd.module):
                if isinstance(cmd, GroupMixin):
                    cmd.recursively_remove_all_commands()
                self.remove_command(cmd.name)
        for event_list in self.extra_events.copy().values():
            remove = [i for i, event in enumerate(event_list) if event.__module__ is not None and _is_submodule(name, event.__module__)]
            for index in reversed(remove):
                del event_list[index]

    async def _call_module_finalizers(self, lib: types.ModuleType, key: str) -> None:
        try:
            func = getattr(lib, "teardown")
        except AttributeError:
            pass
        else:
            try:
                r = func(self)
                if inspect.isawaitable(r):
                    await r
            except Exception:
                pass
        finally:
            self.__extensions.pop(key, None)
            sys.modules.pop(key, None)
            name = lib.__name__
            for module in list(sys.modules.keys()):
                if _is_submodule(name, module):
                    del sys.modules[module]

    async def _load_from_module_spec(self, spec: Any, key: str) -> None:
        lib = importlib.util.module_from_spec(spec)
        sys.modules[key] = lib
        try:
            spec.loader.exec_module(lib)
        except Exception as e:
            del sys.modules[key]
            raise ExtensionFailed(key, e) from e
        try:
            setup = getattr(lib, "setup")
        except AttributeError:
            del sys.modules[key]
            raise NoEntryPointError(key)
        try:
            r = setup(self)
            if inspect.isawaitable(r):
                await r
        except Exception as e:
            del sys.modules[key]
            await self._remove_module_references(lib.__name__)
            await self._call_module_finalizers(lib, key)
            raise ExtensionFailed(key, e) from e
        else:
            self.__extensions[key] = lib

    def _resolve_name(self, name: str, package: Optional[str]) -> str:
        try:
            return importlib.util.resolve_name(name, package)
        except ImportError:
            raise ExtensionNotFound(name)

    async def load_extension(self, name: str, *, package: Optional[str] = None) -> None:
        """Load ``cogs.music`` etc. The module must define ``async def setup(bot)``."""
        name = self._resolve_name(name, package)
        if name in self.__extensions:
            raise ExtensionAlreadyLoaded(name)
        spec = importlib.util.find_spec(name)
        if spec is None:
            raise ExtensionNotFound(name)
        await self._load_from_module_spec(spec, name)

    async def unload_extension(self, name: str, *, package: Optional[str] = None) -> None:
        name = self._resolve_name(name, package)
        lib = self.__extensions.get(name)
        if lib is None:
            raise ExtensionNotLoaded(name)
        await self._remove_module_references(lib.__name__)
        await self._call_module_finalizers(lib, name)

    async def reload_extension(self, name: str, *, package: Optional[str] = None) -> None:
        name = self._resolve_name(name, package)
        lib = self.__extensions.get(name)
        if lib is None:
            raise ExtensionNotLoaded(name)
        modules = {n: m for n, m in sys.modules.items() if _is_submodule(lib.__name__, n)}
        try:
            await self._remove_module_references(lib.__name__)
            await self._call_module_finalizers(lib, name)
            await self.load_extension(name)
        except Exception:
            r = lib.setup(self)  # type: ignore[attr-defined]
            if inspect.isawaitable(r):
                await r
            self.__extensions[name] = lib
            sys.modules.update(modules)
            raise

    @property
    def extensions(self) -> Mapping[str, types.ModuleType]:
        return types.MappingProxyType(self.__extensions)

    # -- help -----------------------------------------------------------------------------

    @property
    def help_command(self) -> Optional[HelpCommand]:
        return self._help_command

    @help_command.setter
    def help_command(self, value: Optional[HelpCommand]) -> None:
        if value is not None:
            if not isinstance(value, HelpCommand):
                raise TypeError("help_command must be a subclass of HelpCommand")
            if self._help_command is not None:
                self._help_command._remove_from_bot(self)
            self._help_command = value
            value._add_to_bot(self)
        elif self._help_command is not None:
            self._help_command._remove_from_bot(self)
            self._help_command = None

    # -- processing -----------------------------------------------------------------------

    async def get_prefix(self, message: "Message", /) -> Union[List[str], str]:
        prefix = ret = self.command_prefix
        if callable(prefix):
            ret = prefix(self, message)
            if inspect.isawaitable(ret):
                ret = await ret
        if not isinstance(ret, str):
            try:
                ret = list(ret)
            except TypeError:
                raise TypeError("command_prefix must be plain string, iterable of strings, or callable returning either") from None
        return ret

    async def get_context(self, origin: "Message", /, *, cls: Type[CXT] = MISSING) -> CXT:
        if cls is MISSING:
            cls = Context  # type: ignore[assignment]
        view = StringView(origin.content)
        ctx = cls(prefix=None, view=view, bot=self, message=origin)
        if origin.author.npub == self.npub:
            return ctx
        prefix = await self.get_prefix(origin)
        invoked_prefix = prefix
        if isinstance(prefix, str):
            if not view.skip_string(prefix):
                return ctx
        else:
            try:
                if origin.content.startswith(tuple(prefix)):
                    invoked_prefix = next(p for p in prefix if view.skip_string(p))
                else:
                    return ctx
            except TypeError:
                raise TypeError("get_prefix must return either a string or a list of string") from None
        if self.strip_after_prefix:
            view.skip_ws()
        invoker = view.get_word()
        ctx.invoked_with = invoker
        ctx.prefix = invoked_prefix  # type: ignore[assignment]
        ctx.command = self.all_commands.get(invoker)
        return ctx

    async def invoke(self, ctx: Context, /) -> None:
        if ctx.command is not None:
            self.dispatch("command", ctx)
            try:
                if await self.can_run(ctx, call_once=True):
                    await ctx.command.invoke(ctx)
                else:
                    raise CheckFailure("The global check once functions failed.")
            except CommandError as exc:
                await ctx.command.dispatch_error(ctx, exc)
            else:
                self.dispatch("command_completion", ctx)
        elif ctx.invoked_with:
            exc = CommandNotFound(f'Command "{ctx.invoked_with}" is not found')
            self.dispatch("command_error", ctx, exc)

    async def process_commands(self, message: "Message", /) -> None:
        """Parse and run a prefix command. Called by the default ``on_message``."""
        if message.author.bot or message.mine:
            return
        ctx = await self.get_context(message)
        if ctx.prefix == "/" and ctx.command is None and self.native_commands:
            return  # an unknown /command is ordinary chat (it may be meant for another bot)
        await self.invoke(ctx)


class Bot(BotBase, Client):
    """A :class:`vector.Client` with the full ``discord.ext.commands`` framework.

    ``command_prefix`` defaults to ``"/"`` (Vector's native commands). Pass ``"!"`` (or a list /
    callable) to also accept prefix commands; ``/name`` keeps working natively either way.
    """

    pass


AutoShardedBot = Bot


def _is_submodule(parent: str, child: str) -> bool:
    return parent == child or child.startswith(parent + ".")
