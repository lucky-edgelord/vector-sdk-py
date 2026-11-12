"""Cogs: classes that group commands, listeners, Mini App handlers and tasks."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Dict, Generator, List, Optional, Tuple, Type, TypeVar

from ...utils import MISSING
from .core import Command, GroupMixin

if TYPE_CHECKING:
    from .bot import BotBase
    from .context import Context

__all__ = ("CogMeta", "Cog", "GroupCog")

FuncT = TypeVar("FuncT", bound=Callable[..., Any])


class CogMeta(type):
    __cog_name__: str
    __cog_description__: str
    __cog_settings__: Dict[str, Any]
    __cog_commands__: List[Command]
    __cog_listeners__: List[Tuple[str, str]]
    __cog_xdc__: List[Tuple[str, str, Dict[str, Any]]]

    def __new__(cls, *args: Any, **kwargs: Any) -> "CogMeta":
        name, bases, attrs = args
        attrs["__cog_name__"] = kwargs.pop("name", name)
        attrs["__cog_settings__"] = kwargs.pop("command_attrs", {})
        description = kwargs.pop("description", None)
        if description is None:
            description = inspect.cleandoc(attrs.get("__doc__", "") or "")
        attrs["__cog_description__"] = description

        commands: Dict[str, Command] = {}
        listeners: Dict[str, Any] = {}
        xdc: Dict[str, Any] = {}
        no_bot_cog = "Commands or listeners must not start with cog_ or bot_ (in method {0.__name__}.{1})"

        new_cls = super().__new__(cls, name, bases, attrs, **kwargs)
        for base in reversed(new_cls.__mro__):
            for elem, value in base.__dict__.items():
                commands.pop(elem, None)
                listeners.pop(elem, None)
                xdc.pop(elem, None)
                is_static = isinstance(value, staticmethod)
                if is_static:
                    value = value.__func__
                if isinstance(value, Command):
                    if is_static:
                        raise TypeError(f"Command in method {base}.{elem!r} must not be staticmethod.")
                    if elem.startswith(("cog_", "bot_")):
                        raise TypeError(no_bot_cog.format(base, elem))
                    commands[elem] = value
                elif inspect.iscoroutinefunction(value):
                    if getattr(value, "__cog_listener__", False):
                        if elem.startswith(("cog_", "bot_")):
                            raise TypeError(no_bot_cog.format(base, elem))
                        listeners[elem] = value
                    if getattr(value, "__cog_xdc__", None) is not None:
                        xdc[elem] = value

        new_cls.__cog_commands__ = list(commands.values())
        listeners_as_list = []
        for listener in listeners.values():
            for listener_name in listener.__cog_listener_names__:
                listeners_as_list.append((listener_name, listener.__name__))
        new_cls.__cog_listeners__ = listeners_as_list
        new_cls.__cog_xdc__ = [(v.__cog_xdc__[0], k, v.__cog_xdc__[1]) for k, v in xdc.items()]
        return new_cls

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args)

    @classmethod
    def qualified_name(cls) -> str:
        return cls.__cog_name__


def _cog_special_method(func: FuncT) -> FuncT:
    func.__cog_special_method__ = None  # type: ignore[attr-defined]
    return func


class Cog(metaclass=CogMeta):
    """Group commands and listeners in a class::

        class Moderation(commands.Cog):
            def __init__(self, bot):
                self.bot = bot

            @commands.command()
            @commands.has_permissions(kick_members=True)
            async def kick(self, ctx, member: vector.Member):
                await member.kick()

            @commands.Cog.listener()
            async def on_member_join(self, member):
                ...

        async def setup(bot):
            await bot.add_cog(Moderation(bot))
    """

    __cog_name__: str
    __cog_description__: str
    __cog_settings__: Dict[str, Any]
    __cog_commands__: List[Command]
    __cog_listeners__: List[Tuple[str, str]]
    __cog_xdc__: List[Tuple[str, str, Dict[str, Any]]]

    def __new__(cls, *args: Any, **kwargs: Any) -> "Cog":
        self = super().__new__(cls)
        cmd_attrs = cls.__cog_settings__
        self.__cog_commands__ = [c._update_copy(cmd_attrs) for c in cls.__cog_commands__]
        lookup = {cmd.qualified_name: cmd for cmd in self.__cog_commands__}
        for command in self.__cog_commands__:
            setattr(self, command.callback.__name__, command)
            parent = command.parent
            if parent is not None and isinstance(parent, Command):
                parent = lookup[parent.qualified_name]
                parent.remove_command(command.name)
                parent.add_command(command)
        return self

    def get_commands(self) -> List[Command]:
        return [c for c in self.__cog_commands__ if c.parent is None]

    @property
    def qualified_name(self) -> str:
        return self.__cog_name__

    @property
    def description(self) -> str:
        return self.__cog_description__

    @description.setter
    def description(self, description: str) -> None:
        self.__cog_description__ = description

    def walk_commands(self) -> Generator[Command, None, None]:
        for command in self.__cog_commands__:
            if command.parent is None:
                yield command
                if isinstance(command, GroupMixin):
                    yield from command.walk_commands()

    def get_listeners(self) -> List[Tuple[str, Callable[..., Any]]]:
        return [(name, getattr(self, method_name)) for name, method_name in self.__cog_listeners__]

    @classmethod
    def _get_overridden_method(cls, method: FuncT) -> Optional[FuncT]:
        return getattr(method.__func__, "__cog_special_method__", method)  # type: ignore[attr-defined]

    @classmethod
    def listener(cls, name: str = MISSING) -> Callable[[FuncT], FuncT]:
        """``@commands.Cog.listener()`` → ``on_<name>`` from the method name, or pass a name."""
        if name is not MISSING and not isinstance(name, str):
            raise TypeError(f"Cog.listener expected str but received {name.__class__.__name__} instead.")

        def decorator(func: FuncT) -> FuncT:
            actual = func
            if isinstance(actual, staticmethod):
                actual = actual.__func__
            if not inspect.iscoroutinefunction(actual):
                raise TypeError("Listener function must be a coroutine function.")
            actual.__cog_listener__ = True  # type: ignore[attr-defined]
            to_assign = name or actual.__name__
            try:
                actual.__cog_listener_names__.append(to_assign)  # type: ignore[attr-defined]
            except AttributeError:
                actual.__cog_listener_names__ = [to_assign]  # type: ignore[attr-defined]
            return func

        return decorator

    @classmethod
    def xdc_app(cls, app: str = "*", **options: Any) -> Callable[[FuncT], FuncT]:
        """``@commands.Cog.xdc_app("vector-chess")``: a Mini App handler method ``(self, session)``."""

        def decorator(func: FuncT) -> FuncT:
            if not inspect.iscoroutinefunction(func):
                raise TypeError("xdc_app handler must be a coroutine function.")
            func.__cog_xdc__ = (app, options)  # type: ignore[attr-defined]
            return func

        return decorator

    def has_error_handler(self) -> bool:
        return not hasattr(self.cog_command_error.__func__, "__cog_special_method__")  # type: ignore[attr-defined]

    @_cog_special_method
    async def cog_load(self) -> None:
        pass

    @_cog_special_method
    async def cog_unload(self) -> None:
        pass

    @_cog_special_method
    def bot_check_once(self, ctx: "Context") -> bool:
        return True

    @_cog_special_method
    def bot_check(self, ctx: "Context") -> bool:
        return True

    @_cog_special_method
    def cog_check(self, ctx: "Context") -> bool:
        return True

    @_cog_special_method
    async def cog_command_error(self, ctx: "Context", error: Exception) -> None:
        pass

    @_cog_special_method
    async def cog_before_invoke(self, ctx: "Context") -> None:
        pass

    @_cog_special_method
    async def cog_after_invoke(self, ctx: "Context") -> None:
        pass

    async def _inject(self, bot: "BotBase", override: bool, guild: Any, guilds: Any) -> "Cog":
        cls = self.__class__
        await _maybe(self.cog_load())
        for index, command in enumerate(self.__cog_commands__):
            command.cog = self
            if command.parent is None:
                try:
                    bot.add_command(command)
                except Exception:
                    for to_undo in self.__cog_commands__[:index]:
                        if to_undo.parent is None:
                            bot.remove_command(to_undo.name)
                    raise
        if cls.bot_check is not Cog.bot_check:
            bot.add_check(self.bot_check)
        if cls.bot_check_once is not Cog.bot_check_once:
            bot.add_check(self.bot_check_once, call_once=True)
        for name, method_name in self.__cog_listeners__:
            bot.add_listener(getattr(self, method_name), name)
        for app, method_name, options in self.__cog_xdc__:
            opts = dict(join_when="opened", idle_timeout=180.0, quiet_timeout=900.0, max_sessions=32,
                        max_per_chat=4, by_hash=False)
            opts.update(options)
            bot._register_xdc(app, getattr(type(self), method_name), opts, self)
        return self

    async def _eject(self, bot: "BotBase", guild_ids: Any) -> None:
        cls = self.__class__
        try:
            for command in self.__cog_commands__:
                if command.parent is None:
                    bot.remove_command(command.name)
            for name, method_name in self.__cog_listeners__:
                bot.remove_listener(getattr(self, method_name), name)
            if cls.bot_check is not Cog.bot_check:
                bot.remove_check(self.bot_check)
            if cls.bot_check_once is not Cog.bot_check_once:
                bot.remove_check(self.bot_check_once, call_once=True)
            for hid, (func, owner) in list(bot._xdc_handlers.items()):
                if owner is self:
                    del bot._xdc_handlers[hid]
        finally:
            try:
                await _maybe(self.cog_unload())
            except Exception:
                pass


class GroupCog(Cog):
    """discord.py's GroupCog: here simply a Cog (Vector has no nested slash groups)."""


async def _maybe(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
