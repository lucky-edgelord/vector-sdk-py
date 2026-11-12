"""``app_commands``: discord.py's slash-command API, backed by Vector's native commands.

    tree = app_commands.CommandTree(client)      # commands.Bot already has bot.tree

    @tree.command(name="hello", description="Say hi")
    @app_commands.describe(user="who to greet")
    async def hello(interaction: vector.Interaction, user: vector.Member):
        await interaction.response.send_message(f"Hi {user.display_name}!")

``await tree.sync()`` is accepted and does nothing: Vector publishes the command manifest when
the bot starts listening.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, Generic, List, Optional, Sequence, Tuple, TypeVar, Union

from .ext.commands.converter import Range as Range
from .ext.commands.converter import run_converters
from .ext.commands.core import (
    _SLUG, _native_type, _unwrap_optional, describe, get_signature_parameters, rename,
)
from .ext.commands.errors import CheckFailure, CommandError, CommandInvokeError, CommandOnCooldown, MissingPermissions, NoPrivateMessage
from .ui.interaction import Interaction, InteractionType

if TYPE_CHECKING:
    from .client import Client
    from .message import Message

_log = logging.getLogger("vector.app_commands")

__all__ = ("CommandTree", "Command", "Group", "Choice", "command", "describe", "rename", "choices", "autocomplete",
           "guild_only", "dm_only", "default_permissions", "check", "checks", "Range", "AppCommandError",
           "CheckFailure", "CommandInvokeError", "Transform", "Transformer", "guilds", "allowed_installs",
           "allowed_contexts")

T = TypeVar("T")
AppCommandError = CommandError


class Choice(Generic[T]):
    def __init__(self, *, name: str, value: T):
        self.name = name
        self.value = value

    def _wire(self) -> str:
        v = str(self.value).lower()
        return v if 0 < len(v) <= 32 and not _SLUG.search(v) else _SLUG.sub("-", self.name.lower())[:32]

    def __repr__(self) -> str:
        return f"Choice(name={self.name!r}, value={self.value!r})"


class Transformer:
    async def transform(self, interaction: Interaction, value: Any) -> Any:
        return value


class _TransformMeta(type):
    def __getitem__(cls, items: Any) -> Any:
        return items[1] if isinstance(items, tuple) else items


class Transform(metaclass=_TransformMeta):
    pass


class _ConvCtx:
    """Just enough of a commands.Context for the converters."""

    def __init__(self, client: "Client", message: "Message"):
        self.bot = client
        self.message = message
        self._state = message._state
        self.channel = message.channel
        self.community = message.community
        self.guild = message.community
        self.author = message.author


def choices(**parameters: List[Choice[Any]]) -> Callable[[T], T]:
    def decorator(func: Any) -> Any:
        target = func._callback if isinstance(func, Command) else func
        existing = getattr(target, "__vector_choices__", {})
        existing.update(parameters)
        target.__vector_choices__ = existing
        return func

    return decorator


def autocomplete(**parameters: Any) -> Callable[[T], T]:
    """Accepted for compatibility; Vector has no live autocomplete."""

    def decorator(func: Any) -> Any:
        return func

    return decorator


def check(predicate: Callable[[Interaction], Any]) -> Callable[[T], T]:
    def decorator(func: Any) -> Any:
        target = func._callback if isinstance(func, Command) else func
        if isinstance(func, Command):
            func.checks.append(predicate)
        else:
            target.__vector_app_checks__ = getattr(target, "__vector_app_checks__", []) + [predicate]
        return func

    return decorator


def guild_only(func: Any = None) -> Any:
    def predicate(interaction: Interaction) -> bool:
        if interaction.guild is None:
            raise NoPrivateMessage()
        return True

    deco = check(predicate)
    return deco(func) if func is not None else deco


def dm_only(func: Any = None) -> Any:
    def predicate(interaction: Interaction) -> bool:
        if interaction.guild is not None:
            raise CheckFailure("This command can only be used in DMs.")
        return True

    deco = check(predicate)
    return deco(func) if func is not None else deco


def guilds(*ids: Any) -> Callable[[T], T]:
    return lambda f: f


def allowed_installs(**kw: Any) -> Callable[[T], T]:
    return lambda f: f


def allowed_contexts(**kw: Any) -> Callable[[T], T]:
    return lambda f: f


def default_permissions(**perms: bool) -> Callable[[T], T]:
    return checks.has_permissions(**perms)


class checks:
    """``app_commands.checks.has_permissions(...)`` / ``.cooldown(...)`` / ``.has_role(...)``."""

    @staticmethod
    def has_permissions(**perms: bool) -> Callable[[T], T]:
        def predicate(interaction: Interaction) -> bool:
            member = interaction.user
            if interaction.guild is None or member.is_owner():
                return True
            missing = [p for p in perms if not member.can(p)]
            if missing:
                raise MissingPermissions(missing)
            return True

        return check(predicate)

    @staticmethod
    def has_role(item: Any) -> Callable[[T], T]:
        def predicate(interaction: Interaction) -> bool:
            from .ext.commands.core import _role_match

            if interaction.guild is None:
                raise NoPrivateMessage()
            if not _role_match(interaction.user, item):
                from .ext.commands.errors import MissingRole

                raise MissingRole(item)
            return True

        return check(predicate)

    @staticmethod
    def cooldown(rate: float, per: float, *, key: Optional[Callable[[Interaction], Any]] = None) -> Callable[[T], T]:
        from .ext.commands.cooldowns import Cooldown

        buckets: Dict[Any, Cooldown] = {}

        def predicate(interaction: Interaction) -> bool:
            k = key(interaction) if key else getattr(interaction.user, "npub", None)
            bucket = buckets.setdefault(k, Cooldown(rate, per))
            retry = bucket.update_rate_limit()
            if retry:
                raise CommandOnCooldown(bucket, retry, None)
            return True

        return check(predicate)


class Command:
    def __init__(self, *, name: str, description: str, callback: Callable[..., Any], parent: Optional["Group"] = None,
                 nsfw: bool = False, extras: Optional[Dict[str, Any]] = None, **ignored: Any):
        self.name = name
        self.description = description or "…"
        self._callback = callback
        self.parent = parent
        self.extras = extras or {}
        self.binding: Any = None
        self.checks: List[Callable[..., Any]] = list(getattr(callback, "__vector_app_checks__", []))
        self.on_error: Optional[Callable[..., Any]] = None

    @property
    def callback(self) -> Callable[..., Any]:
        return self._callback

    @property
    def qualified_name(self) -> str:
        return f"{self.parent.name} {self.name}" if self.parent else self.name

    def _params(self):
        skip = 1 + (1 if self.binding is not None else 0)
        return get_signature_parameters(self._callback, skip=skip)

    def _spec(self) -> Optional[List[Tuple[str, str, str, bool, List[str]]]]:
        out = []
        renames = getattr(self._callback, "__vector_rename__", {})
        choice_map: Dict[str, List[Choice[Any]]] = getattr(self._callback, "__vector_choices__", {})
        optional_seen = False
        self._native_map: Dict[str, str] = {}
        for name, p in self._params().items():
            ann, optional = _unwrap_optional(p.annotation)
            if name in choice_map:
                kind, values = "choice", [c._wire() for c in choice_map[name]]
            else:
                kind, values = _native_type(ann)
            wire = renames.get(name, name).lower()
            wire = _SLUG.sub("_", wire)[:32]
            required = p.required and not optional and not optional_seen
            optional_seen = optional_seen or not required
            out.append((wire, kind, (p.description or name)[:200], required, values))
            self._native_map[wire] = name
        return out if len(out) <= 8 else None

    def error(self, coro: Callable[..., Any]) -> Callable[..., Any]:
        self.on_error = coro
        return coro

    def add_check(self, func: Callable[..., Any]) -> None:
        self.checks.append(func)

    async def _invoke(self, interaction: Interaction, values: Dict[str, Any]) -> None:
        ctx = _ConvCtx(interaction.client, interaction.message)  # type: ignore[arg-type]
        choice_map: Dict[str, List[Choice[Any]]] = getattr(self._callback, "__vector_choices__", {})
        kwargs: Dict[str, Any] = {}
        for name, p in self._params().items():
            raw = values.get(name)
            if raw is None or raw == "":
                if p.required:
                    ann, optional = _unwrap_optional(p.annotation)
                    if not optional:
                        from .ext.commands.errors import MissingRequiredArgument

                        raise MissingRequiredArgument(p)
                    kwargs[name] = None
                else:
                    kwargs[name] = p.default
                continue
            if name in choice_map:
                chosen = next((c for c in choice_map[name] if c._wire() == str(raw).lower()), None)
                ann, _ = _unwrap_optional(p.annotation)
                kwargs[name] = chosen if ann is Choice or getattr(ann, "__origin__", None) is Choice else (chosen.value if chosen else raw)
                continue
            kwargs[name] = await run_converters(ctx, p.annotation if p.annotation is not inspect.Parameter.empty else str, raw, p)  # type: ignore[arg-type]
        for predicate in self.checks:
            ok = predicate(interaction)
            if inspect.isawaitable(ok):
                ok = await ok
            if not ok:
                raise CheckFailure(f"The check functions for command {self.qualified_name} failed.")
        try:
            if self.binding is not None:
                await self._callback(self.binding, interaction, **kwargs)
            else:
                await self._callback(interaction, **kwargs)
        except CommandError:
            raise
        except Exception as e:
            raise CommandInvokeError(e) from e

    def __repr__(self) -> str:
        return f"<app_commands.Command name={self.qualified_name!r}>"


class Group:
    """``/name <subcommand> [args]``. Subclass it or create one and use ``@group.command()``."""

    def __init__(self, *, name: Optional[str] = None, description: Optional[str] = None, **ignored: Any):
        self.name = (name or type(self).__name__).lower()
        self.description = description or (inspect.getdoc(self) or "…")
        self._children: Dict[str, Command] = {}
        for attr in dir(type(self)):
            value = getattr(type(self), attr, None)
            if isinstance(value, Command):
                cmd = Command(name=value.name, description=value.description, callback=value._callback, parent=self)
                cmd.binding = self
                self._children[cmd.name] = cmd

    def command(self, *, name: Optional[str] = None, description: Optional[str] = None, **kw: Any) -> Callable[..., Command]:
        def decorator(func: Callable[..., Any]) -> Command:
            cmd = Command(name=(name or func.__name__).lower(), description=description or inspect.getdoc(func) or "",
                          callback=func, parent=self)
            self._children[cmd.name] = cmd
            return cmd

        return decorator

    def add_command(self, command: Command) -> None:
        command.parent = self
        self._children[command.name] = command

    @property
    def commands(self) -> List[Command]:
        return list(self._children.values())

    def _spec(self) -> List[Tuple[str, str, str, bool, List[str]]]:
        return [("subcommand", "choice", "what to do", True, sorted(self._children)[:32]),
                ("args", "string", "arguments", False, [])]

    async def _invoke(self, interaction: Interaction, values: Dict[str, Any]) -> None:
        from .ext.commands.core import StringView

        sub = self._children.get(str(values.get("subcommand") or ""))
        if sub is None:
            raise CommandError(f"unknown subcommand for /{self.name}")
        view = StringView(str(values.get("args") or ""))
        params = list(sub._params().items())
        parsed: Dict[str, Any] = {}
        for i, (name, p) in enumerate(params):
            view.skip_ws()
            if view.eof:
                break
            parsed[name] = view.read_rest().strip() if i == len(params) - 1 else view.get_quoted_word()
        await sub._invoke(interaction, parsed)


def command(*, name: Optional[str] = None, description: Optional[str] = None, nsfw: bool = False,
            extras: Optional[Dict[str, Any]] = None, **ignored: Any) -> Callable[[Callable[..., Any]], Command]:
    """A standalone app command (add it with ``tree.add_command``) or a Group method."""

    def decorator(func: Callable[..., Any]) -> Command:
        return Command(name=(name or func.__name__).lower(), description=description or inspect.getdoc(func) or "",
                       callback=func, nsfw=nsfw, extras=extras)

    return decorator


class CommandTree:
    def __init__(self, client: "Client", **ignored: Any):
        self.client = client
        self._commands: Dict[str, Union[Command, Group]] = {}
        client._app_tree = self  # type: ignore[attr-defined]
        self._registered: set = set()
        self._error_handler: Optional[Callable[..., Any]] = None

    def command(self, *, name: Optional[str] = None, description: Optional[str] = None, nsfw: bool = False,
                guild: Any = None, guilds: Any = None, extras: Optional[Dict[str, Any]] = None,
                **ignored: Any) -> Callable[[Callable[..., Any]], Command]:
        def decorator(func: Callable[..., Any]) -> Command:
            cmd = Command(name=(name or func.__name__).lower(), description=description or inspect.getdoc(func) or "",
                          callback=func, nsfw=nsfw, extras=extras)
            self.add_command(cmd)
            return cmd

        return decorator

    def add_command(self, command: Union[Command, Group], /, *, guild: Any = None, guilds: Any = None,
                    override: bool = False) -> None:
        self._commands[command.name] = command
        if getattr(self.client, "native", None) is not None:
            self._register(command)

    def remove_command(self, name: str, /, **ignored: Any) -> Optional[Union[Command, Group]]:
        return self._commands.pop(name, None)

    def get_command(self, name: str, /, **ignored: Any) -> Optional[Union[Command, Group]]:
        return self._commands.get(name)

    def get_commands(self, **ignored: Any) -> List[Union[Command, Group]]:
        return list(self._commands.values())

    def walk_commands(self, **ignored: Any):
        for c in self._commands.values():
            yield c
            if isinstance(c, Group):
                yield from c.commands

    def copy_global_to(self, *, guild: Any) -> None:
        pass

    def clear_commands(self, *, guild: Any = None) -> None:
        self._commands.clear()

    async def sync(self, *, guild: Any = None) -> List[Union[Command, Group]]:
        """Vector publishes the manifest when listening starts, so this only reports the commands."""
        return self.get_commands()

    def error(self, coro: Callable[..., Any]) -> Callable[..., Any]:
        self._error_handler = coro
        return coro

    async def on_error(self, interaction: Interaction, error: Exception, /) -> None:
        if self._error_handler is not None:
            await self._error_handler(interaction, error)
        else:
            _log.error("Ignoring exception in command %r", getattr(interaction.command, "name", None), exc_info=error)

    def _register(self, command: Union[Command, Group]) -> None:
        if command.name in self._registered:
            return
        spec = command._spec()
        if spec is None:
            _log.warning("/%s has too many arguments for Vector (max 8)", command.name)
            return
        try:
            self.client.native.register_command(command.name, command.description[:200], spec)
            self._registered.add(command.name)
        except ValueError as e:
            _log.warning("could not publish /%s: %s", command.name, e)

    def _register_all(self) -> None:
        for c in self._commands.values():
            self._register(c)

    async def _dispatch(self, name: str, args: Dict[str, Any], message: "Message") -> bool:
        command = self._commands.get(name)
        if command is None:
            return False
        interaction = Interaction(client=self.client, user=message.author, message=message, channel=message.channel,
                                  data={"name": name, "options": args}, type=InteractionType.application_command)
        interaction.command = command  # type: ignore[assignment]
        if isinstance(command, Command):
            command._spec()
            values = {command._native_map.get(k, k): v for k, v in args.items()}
        else:
            values = dict(args)
        try:
            await command._invoke(interaction, values)
        except Exception as e:
            handler = getattr(command, "on_error", None)
            if handler is not None:
                await handler(interaction, e)
            else:
                await self.on_error(interaction, e)
        return True
