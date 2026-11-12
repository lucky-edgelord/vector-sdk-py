"""``Command``, ``Group``, the ``@command``/``@group`` decorators and every built-in check.

Every command works two ways at once:

* **Native slash command**: published in the bot's Vector manifest so clients show it in the
  ``/`` picker with typed arguments (``str``→text, ``int``, ``float``→number, ``bool``→flag,
  ``Member``/``User``→user picker, ``Literal[...]``→choice). Vector validates the types and
  replies with usage on bad input before your code runs.
* **Prefix command** (``!ping``) parsed in Python, exactly like discord.py, for any
  ``command_prefix`` you configure.
"""

from __future__ import annotations

import asyncio
import datetime
import functools
import inspect
import re
import sys
import typing
from typing import (
    TYPE_CHECKING, Any, Callable, Coroutine, Dict, Generic, Iterable, List, Literal, Optional, Set, Tuple, Type,
    TypeVar, Union, get_args, get_origin,
)

from ...channel import DMChannel
from ...message import Attachment
from ...user import Member, User
from ...utils import MISSING
from .converter import Greedy, Range, _is_union, run_converters
from .cooldowns import BucketType, Cooldown, CooldownMapping, DynamicCooldownMapping, MaxConcurrency
from .errors import (
    ArgumentParsingError, BadArgument, BotMissingAnyRole, BotMissingPermissions, BotMissingRole, CheckAnyFailure,
    CheckFailure, CommandError, CommandInvokeError, CommandOnCooldown, CommandRegistrationError, DisabledCommand,
    ExpectedClosingQuoteError, InvalidEndOfQuotedStringError, MissingAnyRole, MissingPermissions,
    MissingRequiredArgument, MissingRequiredAttachment, MissingRole, NoPrivateMessage, NotOwner,
    NSFWChannelRequired, PrivateMessageOnly, TooManyArguments, UnexpectedQuoteError,
)

if TYPE_CHECKING:
    from .context import Context

__all__ = (
    "Command", "Group", "GroupMixin", "command", "group", "hybrid_command", "hybrid_group", "Parameter", "param",
    "parameter", "Author", "CurrentChannel", "CurrentGuild", "CurrentCommunity", "check", "check_any", "has_role",
    "has_any_role", "bot_has_role", "bot_has_any_role", "has_permissions", "bot_has_permissions",
    "has_guild_permissions", "bot_has_guild_permissions", "dm_only", "guild_only", "community_only", "is_owner",
    "is_admin", "is_nsfw", "cooldown", "dynamic_cooldown", "max_concurrency", "before_invoke", "after_invoke",
    "describe", "rename", "StringView",
)

T = TypeVar("T")
_SLUG = re.compile(r"[^a-z0-9_-]")


# ---------------------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------------------

_QUOTES = {'"': '"', "“": "”", "‘": "’", "«": "»", "「": "」", "'": "'"}


class StringView:
    """Quote-aware word reader (the same rules as discord.py's)."""

    def __init__(self, buffer: str):
        self.index = 0
        self.buffer = buffer
        self.end = len(buffer)
        self.previous = 0

    @property
    def eof(self) -> bool:
        return self.index >= self.end

    def skip_ws(self) -> bool:
        pos = 0
        while not self.eof:
            if not self.buffer[self.index + pos].isspace():
                break
            pos += 1
            if self.index + pos >= self.end:
                break
        self.previous = self.index
        self.index += pos
        return self.previous != self.index

    def skip_string(self, string: str) -> bool:
        if self.buffer[self.index:self.index + len(string)] == string:
            self.previous = self.index
            self.index += len(string)
            return True
        return False

    def read_rest(self) -> str:
        result = self.buffer[self.index:]
        self.previous = self.index
        self.index = self.end
        return result

    def get_word(self) -> str:
        pos = 0
        while not self.eof:
            try:
                if self.buffer[self.index + pos].isspace():
                    break
                pos += 1
            except IndexError:
                break
        self.previous = self.index
        result = self.buffer[self.index:self.index + pos]
        self.index += pos
        return result

    def get_quoted_word(self) -> Optional[str]:
        if self.eof:
            return None
        current = self.buffer[self.index]
        close_quote = _QUOTES.get(current)
        is_quoted = close_quote is not None and current != "'"
        result = [] if is_quoted else [current]
        self.previous = self.index
        self.index += 1
        escaped = False
        while not self.eof:
            ch = self.buffer[self.index]
            self.index += 1
            if escaped:
                result.append(ch)
                escaped = False
                continue
            if ch == "\\" and is_quoted:
                escaped = True
                continue
            if is_quoted and ch == close_quote:
                if not self.eof and not self.buffer[self.index].isspace():
                    raise InvalidEndOfQuotedStringError(self.buffer[self.index])
                return "".join(result)
            if not is_quoted and ch.isspace():
                self.index -= 1
                return "".join(result)
            result.append(ch)
        if is_quoted:
            raise ExpectedClosingQuoteError(close_quote or '"')
        return "".join(result)

    def undo(self) -> None:
        self.index = self.previous


# ---------------------------------------------------------------------------------------
# parameters
# ---------------------------------------------------------------------------------------


class Parameter(inspect.Parameter):
    """A command parameter, with discord.py's ``description`` / ``displayed_default`` extras."""

    __slots__ = ("_displayed_default", "_description", "_fallback", "_displayed_name")

    def __init__(self, name: str, kind: Any, default: Any = inspect.Parameter.empty, annotation: Any = inspect.Parameter.empty,
                 description: Optional[str] = None, displayed_default: Optional[str] = None,
                 displayed_name: Optional[str] = None):
        super().__init__(name=name, kind=kind, default=default, annotation=annotation)
        self._description = description
        self._displayed_default = displayed_default
        self._displayed_name = displayed_name

    def replace(self, *, name: Any = MISSING, kind: Any = MISSING, default: Any = MISSING, annotation: Any = MISSING,
                description: Any = MISSING, displayed_default: Any = MISSING, displayed_name: Any = MISSING) -> "Parameter":
        return Parameter(
            name=self.name if name is MISSING else name,
            kind=self.kind if kind is MISSING else kind,
            default=self.default if default is MISSING else default,
            annotation=self.annotation if annotation is MISSING else annotation,
            description=self._description if description is MISSING else description,
            displayed_default=self._displayed_default if displayed_default is MISSING else displayed_default,
            displayed_name=self._displayed_name if displayed_name is MISSING else displayed_name,
        )

    @property
    def required(self) -> bool:
        return self.default is inspect.Parameter.empty

    @property
    def converter(self) -> Any:
        return str if self.annotation is inspect.Parameter.empty else self.annotation

    @property
    def description(self) -> Optional[str]:
        return self._description

    @property
    def displayed_default(self) -> Optional[str]:
        if self._displayed_default is not None:
            return self._displayed_default
        if self.required or self.default is None or callable(self.default):
            return None
        return str(self.default)

    @property
    def displayed_name(self) -> str:
        return self._displayed_name or self.name

    async def get_default(self, ctx: "Context") -> Any:
        if callable(self.default) and not inspect.isclass(self.default):
            value = self.default(ctx)
            if inspect.isawaitable(value):
                value = await value
            return value
        return self.default


class _ParamDefault:
    """What ``commands.param(...)`` returns: carried as a parameter's default."""

    def __init__(self, *, converter: Any = MISSING, default: Any = MISSING, description: Optional[str] = None,
                 displayed_default: Optional[str] = None, displayed_name: Optional[str] = None):
        self.converter, self.default, self.description = converter, default, description
        self.displayed_default, self.displayed_name = displayed_default, displayed_name


def param(*, converter: Any = MISSING, default: Any = MISSING, description: Optional[str] = None,
          displayed_default: Optional[str] = None, displayed_name: Optional[str] = None) -> Any:
    """``async def cmd(ctx, user: Member = commands.param(description="who"))``."""
    return _ParamDefault(converter=converter, default=default, description=description,
                         displayed_default=displayed_default, displayed_name=displayed_name)


parameter = param
Author = param(default=lambda ctx: ctx.author, displayed_default="<you>")
CurrentChannel = param(default=lambda ctx: ctx.channel, displayed_default="<this channel>")
CurrentGuild = param(default=lambda ctx: ctx.community, displayed_default="<this community>")
CurrentCommunity = CurrentGuild


def _resolve_hints(func: Callable[..., Any]) -> Dict[str, Any]:
    globalns = getattr(func, "__globals__", {})
    try:
        return typing.get_type_hints(func, globalns=globalns, include_extras=True)
    except Exception:
        hints = {}
        for name, ann in getattr(func, "__annotations__", {}).items():
            if isinstance(ann, str):
                try:
                    ann = eval(ann, globalns)  # noqa: S307 - resolving the user's own annotations
                except Exception:
                    pass
            hints[name] = ann
        return hints


def get_signature_parameters(func: Callable[..., Any], *, skip: int) -> Dict[str, Parameter]:
    sig = inspect.signature(func)
    hints = _resolve_hints(func)
    descriptions: Dict[str, str] = getattr(func, "__vector_describe__", {})
    out: Dict[str, Parameter] = {}
    for i, (name, p) in enumerate(sig.parameters.items()):
        if i < skip:
            continue
        annotation = hints.get(name, p.annotation)
        if hasattr(typing, "Annotated") and get_origin(annotation) is typing.Annotated:
            annotation = get_args(annotation)[1]
        default = p.default
        description = descriptions.get(name)
        displayed_default = displayed_name = None
        if isinstance(default, _ParamDefault):
            pd = default
            if pd.converter is not MISSING:
                annotation = pd.converter
            default = inspect.Parameter.empty if pd.default is MISSING else pd.default
            description = pd.description or description
            displayed_default, displayed_name = pd.displayed_default, pd.displayed_name
        out[name] = Parameter(name, p.kind, default, annotation, description, displayed_default, displayed_name)
    return out


def _unwrap_optional(annotation: Any) -> Tuple[Any, bool]:
    if _is_union(annotation):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) < len(get_args(annotation)):
            return (args[0] if len(args) == 1 else Union[tuple(args)]), True  # type: ignore[return-value]
    return annotation, False


def _native_type(annotation: Any) -> Tuple[str, List[str]]:
    """(vector arg type, choices) for a type hint."""
    from ...user import BaseUser

    ann, _ = _unwrap_optional(annotation)
    if isinstance(ann, Range):
        ann = ann.annotation
    if ann is bool:
        return "flag", []
    if ann is int:
        return "int", []
    if ann is float:
        return "number", []
    if inspect.isclass(ann) and issubclass(ann, BaseUser):
        return "user", []
    if get_origin(ann) is Literal:
        values = [str(v) for v in get_args(ann)]
        if values and all(0 < len(v) <= 32 for v in values) and len(values) <= 32:
            return "choice", values
    return "string", []


# ---------------------------------------------------------------------------------------
# hooks
# ---------------------------------------------------------------------------------------


def hooked_wrapped_callback(command: "Command", ctx: "Context", coro: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(coro)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            ret = await coro(*args, **kwargs)
        except CommandError:
            ctx.command_failed = True
            raise
        except asyncio.CancelledError:
            ctx.command_failed = True
            return None
        except Exception as exc:
            ctx.command_failed = True
            raise CommandInvokeError(exc) from exc
        finally:
            if command._max_concurrency is not None:
                await command._max_concurrency.release(ctx)
            await command.call_after_hooks(ctx)
        return ret

    return wrapped


# ---------------------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------------------


class Command(Generic[T]):
    """A command. Create with ``@bot.command()`` or ``@commands.command()`` (in cogs)."""

    __original_kwargs__: Dict[str, Any]

    def __new__(cls, *args: Any, **kwargs: Any) -> "Command":
        self = super().__new__(cls)
        self.__original_kwargs__ = kwargs.copy()
        return self

    def __init__(self, func: Callable[..., Coroutine[Any, Any, Any]], /, **kwargs: Any):
        if not asyncio.iscoroutinefunction(func):
            raise TypeError("Callback must be a coroutine.")
        name = kwargs.get("name") or func.__name__
        if not isinstance(name, str):
            raise TypeError("Name of a command must be a string.")
        self.name: str = name
        self.callback = func
        self.enabled: bool = kwargs.get("enabled", True)
        help_doc = kwargs.get("help")
        if help_doc is not None:
            help_doc = inspect.cleandoc(help_doc)
        else:
            help_doc = inspect.getdoc(func)
            if isinstance(help_doc, bytes):
                help_doc = help_doc.decode("utf-8")
        self.help: Optional[str] = help_doc
        self.brief: Optional[str] = kwargs.get("brief")
        self.usage: Optional[str] = kwargs.get("usage")
        self.rest_is_raw: bool = kwargs.get("rest_is_raw", False)
        self.aliases: List[str] = list(kwargs.get("aliases", []))
        self.extras: Dict[str, Any] = kwargs.get("extras", {})
        self.description: str = inspect.cleandoc(kwargs.get("description", ""))
        self.hidden: bool = kwargs.get("hidden", False)
        self.slash: bool = kwargs.get("slash", kwargs.get("with_app_command", True))
        self.ignore_extra: bool = kwargs.get("ignore_extra", True)
        self.cooldown_after_parsing: bool = kwargs.get("cooldown_after_parsing", False)
        self.require_var_positional: bool = kwargs.get("require_var_positional", False)

        checks = list(getattr(func, "__commands_checks__", []))
        checks.reverse()
        self.checks: List[Callable[..., Any]] = checks + list(kwargs.get("checks", []))

        cooldown = getattr(func, "__commands_cooldown__", kwargs.get("cooldown"))
        if cooldown is None:
            buckets = CooldownMapping(cooldown, BucketType.default)
        elif isinstance(cooldown, CooldownMapping):
            buckets = cooldown
        else:
            raise TypeError("Cooldown must be an instance of CooldownMapping or None.")
        self._buckets: CooldownMapping = buckets
        self._max_concurrency: Optional[MaxConcurrency] = getattr(func, "__commands_max_concurrency__",
                                                                  kwargs.get("max_concurrency"))
        self.parent: Optional["GroupMixin"] = kwargs.get("parent")
        self.cog: Any = None
        self._before_invoke: Optional[Callable[..., Any]] = getattr(func, "__before_invoke__", None)
        self._after_invoke: Optional[Callable[..., Any]] = getattr(func, "__after_invoke__", None)
        self.on_error: Optional[Callable[..., Any]] = None
        self._renames: Dict[str, str] = getattr(func, "__vector_rename__", {})

    # -- signature ------------------------------------------------------------------------

    @property
    def callback(self) -> Callable[..., Coroutine[Any, Any, Any]]:
        return self._callback

    @callback.setter
    def callback(self, function: Callable[..., Coroutine[Any, Any, Any]]) -> None:
        self._callback = function
        unwrap = inspect.unwrap(function)
        self.module = unwrap.__module__
        self._raw_params = get_signature_parameters(function, skip=0)
        self._params_cache: Optional[Dict[str, Parameter]] = None

    @property
    def params(self) -> Dict[str, Parameter]:
        """Parameters after ``self`` (cogs) and ``ctx``."""
        params = list(self._raw_params.values())
        skip = 1 if self.cog is not None or (params and params[0].name == "self") else 0
        if len(params) <= skip:
            raise TypeError(f"Command signature for {self.name!r} is missing the 'ctx' parameter.")
        return {p.name: p for p in params[skip + 1:]}

    clean_params = params

    @property
    def cooldown(self) -> Optional[Cooldown]:
        return self._buckets._cooldown

    @property
    def full_parent_name(self) -> str:
        entries = []
        command: Any = self
        while command.parent is not None and getattr(command.parent, "name", None):
            command = command.parent
            entries.append(command.name)
        return " ".join(reversed(entries))

    @property
    def parents(self) -> List["Group"]:
        entries = []
        command: Any = self
        while command.parent is not None and isinstance(command.parent, Command):
            command = command.parent
            entries.append(command)
        return entries

    @property
    def root_parent(self) -> Optional["Group"]:
        p = self.parents
        return p[-1] if p else None

    @property
    def qualified_name(self) -> str:
        parent = self.full_parent_name
        return f"{parent} {self.name}" if parent else self.name

    @property
    def short_doc(self) -> str:
        if self.brief is not None:
            return self.brief
        if self.help is not None:
            return self.help.split("\n", 1)[0]
        return ""

    @property
    def signature(self) -> str:
        if self.usage is not None:
            return self.usage
        out = []
        for p in self.params.values():
            if callable(p.default) and not inspect.isclass(p.default) and p.default is not inspect.Parameter.empty and p.displayed_default:
                continue
            name = p.displayed_name
            ann, optional = _unwrap_optional(p.annotation)
            if get_origin(ann) is Literal:
                name = "|".join(f'"{v}"' if isinstance(v, str) else str(v) for v in get_args(ann))
            if isinstance(ann, Greedy):
                out.append(f"[{name}]..." if not p.required else f"<{name}>...")
            elif p.kind == inspect.Parameter.VAR_POSITIONAL:
                out.append(f"<{name}...>" if self.require_var_positional else f"[{name}...]")
            elif not p.required or optional:
                dd = p.displayed_default
                out.append(f"[{name}={dd}]" if dd else f"[{name}]")
            else:
                out.append(f"<{name}>")
        return " ".join(out)

    def __str__(self) -> str:
        return self.qualified_name

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.qualified_name!r}>"

    async def __call__(self, context: "Context", /, *args: Any, **kwargs: Any) -> Any:
        if self.cog is not None:
            return await self.callback(self.cog, context, *args, **kwargs)
        return await self.callback(context, *args, **kwargs)

    # -- native slash spec ----------------------------------------------------------------

    def native_name(self) -> Optional[str]:
        n = self.name.lower()
        return n if n and len(n) <= 32 and not _SLUG.search(n) else None

    def native_args(self) -> Optional[List[Tuple[str, str, str, bool, List[str]]]]:
        """The SDK argument spec, or None if this signature can't be expressed natively."""
        out: List[Tuple[str, str, str, bool, List[str]]] = []
        self._native_map: Dict[str, str] = {}
        optional_seen = False
        params = list(self.params.values())
        for i, p in enumerate(params):
            if callable(p.default) and not inspect.isclass(p.default) and p.default is not inspect.Parameter.empty:
                continue  # context-filled (Author, CurrentChannel…)
            ann, optional = _unwrap_optional(p.annotation)
            if ann is Attachment:
                continue
            greedy = isinstance(ann, Greedy) or p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.KEYWORD_ONLY)
            if greedy:
                if any(q.kind not in (inspect.Parameter.KEYWORD_ONLY,) and q is not p for q in params[i + 1:]):
                    return None
                kind, choices = "string", []
            else:
                kind, choices = _native_type(ann)
            name = self._renames.get(p.name, p.name).lower()
            if _SLUG.search(name) or not name or len(name) > 32:
                name = _SLUG.sub("_", name)[:32] or f"arg{i}"
            required = p.required and not optional and not optional_seen
            if p.kind == inspect.Parameter.VAR_POSITIONAL:
                required = self.require_var_positional and not optional_seen
            optional_seen = optional_seen or not required
            desc = (p.description or p.name.replace("_", " "))[:200]
            out.append((name, kind, desc, required, choices))
            self._native_map[name] = p.name
            if greedy:
                break
        if len(out) > 8:
            return None
        return out

    # -- argument handling ----------------------------------------------------------------

    async def _parse_prefix(self, ctx: "Context") -> None:
        view: StringView = ctx.view
        args: List[Any] = [ctx] if self.cog is None else [self.cog, ctx]
        kwargs: Dict[str, Any] = {}
        for name, p in self.params.items():
            ctx.current_parameter = p
            ann, optional = _unwrap_optional(p.annotation)
            if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.POSITIONAL_ONLY):
                if isinstance(ann, Greedy):
                    args.append(await self._greedy(ctx, p, ann))
                    continue
                args.append(await self._transform(ctx, p, view))
            elif p.kind == inspect.Parameter.VAR_POSITIONAL:
                if self.require_var_positional and (view.skip_ws() or True) and view.eof:
                    raise MissingRequiredArgument(p)
                while not view.eof:
                    try:
                        args.append(await self._transform(ctx, p, view, attachment_ok=False))
                    except RuntimeError:
                        break
            elif p.kind == inspect.Parameter.KEYWORD_ONLY:
                view.skip_ws()
                if self.rest_is_raw:
                    kwargs[name] = view.read_rest()
                elif view.eof:
                    kwargs[name] = await self._missing(ctx, p)
                else:
                    rest = view.read_rest().strip()
                    kwargs[name] = await run_converters(ctx, p.annotation if p.annotation is not inspect.Parameter.empty else str, rest, p)
                break
        if not self.ignore_extra and not view.eof:
            view.skip_ws()
            if not view.eof:
                raise TooManyArguments(f"Too many arguments passed to {self.qualified_name}")
        ctx.args, ctx.kwargs = args, kwargs

    async def _missing(self, ctx: "Context", p: Parameter) -> Any:
        ann, optional = _unwrap_optional(p.annotation)
        if p.required:
            if optional:
                return None
            if ann is Attachment:
                raise MissingRequiredAttachment(p)
            raise MissingRequiredArgument(p)
        return await p.get_default(ctx)

    async def _transform(self, ctx: "Context", p: Parameter, view: StringView, attachment_ok: bool = True) -> Any:
        ann, optional = _unwrap_optional(p.annotation)
        if ann is Attachment and attachment_ok:
            atts = ctx.message.attachments
            idx = ctx._attachment_cursor
            if idx < len(atts):
                ctx._attachment_cursor += 1
                return atts[idx]
            return await self._missing(ctx, p)
        if callable(p.default) and not inspect.isclass(p.default) and p.default is not inspect.Parameter.empty:
            view.skip_ws()
            if view.eof:
                return await p.get_default(ctx)
        view.skip_ws()
        if view.eof:
            if p.kind == inspect.Parameter.VAR_POSITIONAL:
                raise RuntimeError()
            return await self._missing(ctx, p)
        previous = view.index
        argument = view.get_quoted_word()
        try:
            return await run_converters(ctx, p.annotation if p.annotation is not inspect.Parameter.empty else str, argument, p)
        except CommandError:
            if optional or not p.required:
                view.index = previous
                return None if optional else await p.get_default(ctx)
            raise

    async def _greedy(self, ctx: "Context", p: Parameter, greedy: Greedy) -> Any:
        view = ctx.view
        result = []
        while not view.eof:
            previous = view.index
            view.skip_ws()
            try:
                argument = view.get_quoted_word()
                value = await run_converters(ctx, greedy.converter, argument, p)
            except (CommandError, ArgumentParsingError):
                view.index = previous
                break
            else:
                result.append(value)
        if not result and p.required:
            raise MissingRequiredArgument(p)
        return result or (await p.get_default(ctx) if not p.required else [])

    async def _parse_native(self, ctx: "Context", native_args: Dict[str, Any]) -> None:
        if not hasattr(self, "_native_map"):
            self.native_args()
        values = {self._native_map.get(k, k): v for k, v in native_args.items()}
        args: List[Any] = [ctx] if self.cog is None else [self.cog, ctx]
        kwargs: Dict[str, Any] = {}
        for name, p in self.params.items():
            ctx.current_parameter = p
            ann, optional = _unwrap_optional(p.annotation)
            raw = values.get(name)
            if ann is Attachment:
                atts = ctx.message.attachments
                value = atts[ctx._attachment_cursor] if ctx._attachment_cursor < len(atts) else await self._missing(ctx, p)
                ctx._attachment_cursor += 1
            elif raw is None or raw == "":
                value = await self._missing(ctx, p)
            elif p.kind == inspect.Parameter.VAR_POSITIONAL or isinstance(ann, Greedy):
                view = StringView(str(raw))
                items = []
                conv = ann.converter if isinstance(ann, Greedy) else (p.annotation if p.annotation is not inspect.Parameter.empty else str)
                while not view.eof:
                    view.skip_ws()
                    if view.eof:
                        break
                    items.append(await run_converters(ctx, conv, view.get_quoted_word(), p))
                if p.kind == inspect.Parameter.VAR_POSITIONAL:
                    args.extend(items)
                    continue
                value = items
            else:
                conv = p.annotation if p.annotation is not inspect.Parameter.empty else str
                value = await run_converters(ctx, conv, raw, p)
            if p.kind == inspect.Parameter.KEYWORD_ONLY:
                kwargs[name] = value
            else:
                args.append(value)
        ctx.args, ctx.kwargs = args, kwargs

    # -- checks, cooldowns, invoke --------------------------------------------------------

    async def can_run(self, ctx: "Context", /) -> bool:
        if not self.enabled:
            raise DisabledCommand(f"{self.name} command is disabled")
        original = ctx.command
        ctx.command = self
        try:
            if not await ctx.bot.can_run(ctx):
                raise CheckFailure(f"The global check functions for command {self.qualified_name} failed.")
            cog = self.cog
            if cog is not None:
                local_check = type(cog)._get_overridden_method(cog.cog_check)
                if local_check is not None:
                    ret = await _maybe_await(local_check(ctx))
                    if not ret:
                        return False
            predicates = self.checks
            if not predicates:
                return True
            for predicate in predicates:
                if not await _maybe_await(predicate(ctx)):
                    return False
            return True
        finally:
            ctx.command = original

    def _prepare_cooldowns(self, ctx: "Context") -> None:
        if self._buckets.valid:
            bucket = self._buckets.get_bucket(ctx)
            if bucket is not None:
                retry_after = bucket.update_rate_limit()
                if retry_after:
                    raise CommandOnCooldown(bucket, retry_after, self._buckets.type)

    async def prepare(self, ctx: "Context", native_args: Optional[Dict[str, Any]] = None) -> None:
        ctx.command = self
        if not await self.can_run(ctx):
            raise CheckFailure(f"The check functions for command {self.qualified_name} failed.")
        if self._max_concurrency is not None:
            await self._max_concurrency.acquire(ctx)
        try:
            if self.cooldown_after_parsing:
                await self._parse(ctx, native_args)
                self._prepare_cooldowns(ctx)
            else:
                self._prepare_cooldowns(ctx)
                await self._parse(ctx, native_args)
            await self.call_before_hooks(ctx)
        except Exception:
            if self._max_concurrency is not None:
                await self._max_concurrency.release(ctx)
            raise

    async def _parse(self, ctx: "Context", native_args: Optional[Dict[str, Any]]) -> None:
        if native_args is not None:
            await self._parse_native(ctx, native_args)
        else:
            await self._parse_prefix(ctx)

    async def call_before_hooks(self, ctx: "Context") -> None:
        cog = self.cog
        if self._before_invoke is not None:
            instance = getattr(self._before_invoke, "__self__", cog)
            if instance is not None and not inspect.ismethod(self._before_invoke):
                await self._before_invoke(instance, ctx)
            else:
                await self._before_invoke(ctx)
        if cog is not None:
            hook = type(cog)._get_overridden_method(cog.cog_before_invoke)
            if hook is not None:
                await hook(ctx)
        hook = ctx.bot._before_invoke
        if hook is not None:
            await hook(ctx)

    async def call_after_hooks(self, ctx: "Context") -> None:
        cog = self.cog
        if self._after_invoke is not None:
            instance = getattr(self._after_invoke, "__self__", cog)
            if instance is not None and not inspect.ismethod(self._after_invoke):
                await self._after_invoke(instance, ctx)
            else:
                await self._after_invoke(ctx)
        if cog is not None:
            hook = type(cog)._get_overridden_method(cog.cog_after_invoke)
            if hook is not None:
                await hook(ctx)
        hook = ctx.bot._after_invoke
        if hook is not None:
            await hook(ctx)

    async def invoke(self, ctx: "Context", /) -> None:
        await self.prepare(ctx, ctx._native_args)
        ctx.invoked_subcommand = None
        ctx.subcommand_passed = None
        injected = hooked_wrapped_callback(self, ctx, self.callback)
        await injected(*ctx.args, **ctx.kwargs)

    async def reinvoke(self, ctx: "Context", /, *, call_hooks: bool = False) -> None:
        ctx.command = self
        await self._parse(ctx, ctx._native_args)
        if call_hooks:
            await self.call_before_hooks(ctx)
        try:
            await self.callback(*ctx.args, **ctx.kwargs)
        except Exception:
            ctx.command_failed = True
            raise
        finally:
            if call_hooks:
                await self.call_after_hooks(ctx)

    async def dispatch_error(self, ctx: "Context", error: CommandError, /) -> None:
        ctx.command_failed = True
        cog = self.cog
        if self.on_error is not None:
            if cog is not None and not inspect.ismethod(self.on_error):
                await self.on_error(cog, ctx, error)
            else:
                await self.on_error(ctx, error)
        try:
            if cog is not None:
                local = type(cog)._get_overridden_method(cog.cog_command_error)
                if local is not None:
                    await local(ctx, error)
        finally:
            ctx.bot.dispatch("command_error", ctx, error)

    def error(self, coro: Callable[..., Any], /) -> Callable[..., Any]:
        """``@mycommand.error`` local error handler."""
        if not asyncio.iscoroutinefunction(coro):
            raise TypeError("The error handler must be a coroutine.")
        self.on_error = coro
        return coro

    def has_error_handler(self) -> bool:
        return self.on_error is not None

    def before_invoke(self, coro: Callable[..., Any], /) -> Callable[..., Any]:
        self._before_invoke = coro
        return coro

    def after_invoke(self, coro: Callable[..., Any], /) -> Callable[..., Any]:
        self._after_invoke = coro
        return coro

    def add_check(self, func: Callable[..., Any], /) -> None:
        self.checks.append(func)

    def remove_check(self, func: Callable[..., Any], /) -> None:
        try:
            self.checks.remove(func)
        except ValueError:
            pass

    def is_on_cooldown(self, ctx: "Context", /) -> bool:
        if not self._buckets.valid:
            return False
        bucket = self._buckets.get_bucket(ctx)
        return bucket is not None and bucket.get_tokens() == 0

    def reset_cooldown(self, ctx: "Context", /) -> None:
        if self._buckets.valid:
            bucket = self._buckets.get_bucket(ctx)
            if bucket is not None:
                bucket.reset()

    def get_cooldown_retry_after(self, ctx: "Context", /) -> float:
        if self._buckets.valid:
            bucket = self._buckets.get_bucket(ctx)
            if bucket is not None:
                return bucket.get_retry_after()
        return 0.0

    def update(self, **kwargs: Any) -> None:
        cog = self.cog
        self.__init__(self.callback, **dict(self.__original_kwargs__, **kwargs))  # type: ignore[misc]
        self.cog = cog

    def _ensure_assignment_on_copy(self, other: "Command") -> "Command":
        other._before_invoke = self._before_invoke
        other._after_invoke = self._after_invoke
        other.on_error = self.on_error
        if self.checks != other.checks:
            other.checks = self.checks.copy()
        if self._buckets.valid and not other._buckets.valid:
            other._buckets = self._buckets.copy()
        if self._max_concurrency and self._max_concurrency != other._max_concurrency:
            other._max_concurrency = self._max_concurrency.copy()
        return other

    def copy(self) -> "Command":
        ret = self.__class__(self.callback, **self.__original_kwargs__)
        return self._ensure_assignment_on_copy(ret)

    def _update_copy(self, kwargs: Dict[str, Any]) -> "Command":
        if kwargs:
            kw = kwargs.copy()
            kw.update(self.__original_kwargs__)
            copy = self.__class__(self.callback, **kw)
            return self._ensure_assignment_on_copy(copy)
        return self.copy()


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


# ---------------------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------------------


class GroupMixin(Generic[T]):
    def __init__(self, *args: Any, **kwargs: Any):
        case_insensitive = kwargs.get("case_insensitive", False)
        self.all_commands: Dict[str, Command] = _CaseInsensitiveDict() if case_insensitive else {}
        self.case_insensitive: bool = case_insensitive
        super().__init__(*args, **kwargs)

    @property
    def commands(self) -> Set[Command]:
        return set(self.all_commands.values())

    def recursively_remove_all_commands(self) -> None:
        for command in self.all_commands.copy().values():
            if isinstance(command, GroupMixin):
                command.recursively_remove_all_commands()
            self.remove_command(command.name)

    def add_command(self, command: Command, /) -> None:
        if not isinstance(command, Command):
            raise TypeError("The command passed must be a subclass of Command")
        if isinstance(self, Command):
            command.parent = self
        if command.name in self.all_commands:
            raise CommandRegistrationError(command.name)
        self.all_commands[command.name] = command
        for alias in command.aliases:
            if alias in self.all_commands:
                self.remove_command(command.name)
                raise CommandRegistrationError(alias, alias_conflict=True)
            self.all_commands[alias] = command
        self._on_command_added(command)

    def _on_command_added(self, command: Command) -> None:
        pass

    def remove_command(self, name: str, /) -> Optional[Command]:
        command = self.all_commands.pop(name, None)
        if command is None:
            return None
        if name in command.aliases:
            return command
        for alias in command.aliases:
            cmd = self.all_commands.pop(alias, None)
            if cmd is not None and cmd != command:
                self.all_commands[alias] = cmd
        return command

    def walk_commands(self):
        for command in self.commands:
            yield command
            if isinstance(command, GroupMixin):
                yield from command.walk_commands()

    def get_command(self, name: str, /) -> Optional[Command]:
        if " " not in name:
            return self.all_commands.get(name)
        names = name.split()
        if not names:
            return None
        obj: Any = self.all_commands.get(names[0])
        if not isinstance(obj, GroupMixin):
            return obj
        for n in names[1:]:
            try:
                obj = obj.all_commands[n]
            except (AttributeError, KeyError):
                return None
        return obj

    def command(self, name: str = MISSING, cls: Type[Command] = MISSING, *args: Any, **kwargs: Any) -> Callable[..., Command]:
        def decorator(func: Callable[..., Any]) -> Command:
            kwargs.setdefault("parent", self)
            result = command(name=name, cls=cls, *args, **kwargs)(func)
            self.add_command(result)
            return result

        return decorator

    def group(self, name: str = MISSING, cls: Type["Group"] = MISSING, *args: Any, **kwargs: Any) -> Callable[..., "Group"]:
        def decorator(func: Callable[..., Any]) -> "Group":
            kwargs.setdefault("parent", self)
            result = group(name=name, cls=cls, *args, **kwargs)(func)
            self.add_command(result)
            return result

        return decorator

    hybrid_command = command
    hybrid_group = group


class _CaseInsensitiveDict(dict):
    def __contains__(self, k: object) -> bool:
        return super().__contains__(str(k).casefold())

    def __delitem__(self, k: str) -> None:
        return super().__delitem__(k.casefold())

    def __getitem__(self, k: str) -> Any:
        return super().__getitem__(k.casefold())

    def get(self, k: str, default: Any = None) -> Any:
        return super().get(k.casefold(), default)

    def pop(self, k: str, default: Any = None) -> Any:
        return super().pop(k.casefold(), default)

    def __setitem__(self, k: str, v: Any) -> None:
        super().__setitem__(k.casefold(), v)


class Group(GroupMixin, Command):
    """A command with subcommands. Natively it's ``/name <subcommand> [args]``."""

    def __init__(self, *args: Any, **attrs: Any):
        self.invoke_without_command: bool = attrs.pop("invoke_without_command", False)
        super().__init__(*args, **attrs)

    def copy(self) -> "Group":
        ret = super().copy()
        for cmd in self.commands:
            ret.add_command(cmd.copy())
        return ret  # type: ignore[return-value]

    def native_args(self) -> Optional[List[Tuple[str, str, str, bool, List[str]]]]:
        subs = sorted({c.name.lower() for c in self.commands if not _SLUG.search(c.name.lower())})
        if not subs:
            return super().native_args()
        self._native_map = {}
        return [
            ("subcommand", "choice", "what to do", not self.invoke_without_command, subs[:32]),
            ("args", "string", "the subcommand's arguments", False, []),
        ]

    async def invoke(self, ctx: "Context", /) -> None:
        native = ctx._native_args
        if native is not None and self.all_commands:
            # natively a group is `/name <subcommand> [args]`: replay it through the prefix parser
            sub = native.get("subcommand") or ""
            ctx.view = StringView(f"{sub} {native.get('args') or ''}".strip())
        elif native is not None:
            await Command.invoke(self, ctx)
            return
        ctx._native_args = None
        early_invoke = not self.invoke_without_command
        if early_invoke:
            await self.prepare(ctx)
        view = ctx.view
        previous = view.index
        view.skip_ws()
        trigger = view.get_word()
        if trigger:
            ctx.subcommand_passed = trigger
            ctx.invoked_subcommand = self.all_commands.get(trigger, None)
        if early_invoke:
            injected = hooked_wrapped_callback(self, ctx, self.callback)
            await injected(*ctx.args, **ctx.kwargs)
        ctx.invoked_parents.append(ctx.invoked_with)  # type: ignore[arg-type]
        if trigger and ctx.invoked_subcommand:
            ctx.invoked_with = trigger
            await ctx.invoked_subcommand.invoke(ctx)
        elif not early_invoke:
            view.index = previous
            view.previous = previous
            await super().invoke(ctx)


# ---------------------------------------------------------------------------------------
# decorators
# ---------------------------------------------------------------------------------------


def command(name: str = MISSING, cls: Type[Command] = MISSING, **attrs: Any) -> Callable[..., Command]:
    """Turn a coroutine into a :class:`Command` (use ``@bot.command()`` outside cogs)."""
    if cls is MISSING:
        cls = Command

    def decorator(func: Callable[..., Any]) -> Command:
        if isinstance(func, Command):
            raise TypeError("Callback is already a command.")
        return cls(func, name=None if name is MISSING else name, **attrs)

    return decorator


def group(name: str = MISSING, cls: Type[Group] = MISSING, **attrs: Any) -> Callable[..., Group]:
    if cls is MISSING:
        cls = Group
    return command(name=name, cls=cls, **attrs)  # type: ignore[return-value]


hybrid_command = command
hybrid_group = group


def describe(**parameters: str) -> Callable[[T], T]:
    """``@commands.describe(user="who to greet")``: argument help shown in Vector's ``/`` picker."""

    def decorator(func: Any) -> Any:
        target = func.callback if isinstance(func, Command) else func
        existing = getattr(target, "__vector_describe__", {})
        existing.update(parameters)
        target.__vector_describe__ = existing
        if isinstance(func, Command):
            func.callback = target
        return func

    return decorator


def rename(**parameters: str) -> Callable[[T], T]:
    """``@commands.rename(member="user")``: the argument's name in the slash picker."""

    def decorator(func: Any) -> Any:
        target = func.callback if isinstance(func, Command) else func
        existing = getattr(target, "__vector_rename__", {})
        existing.update(parameters)
        target.__vector_rename__ = existing
        if isinstance(func, Command):
            func._renames = existing
        return func

    return decorator


# ---------------------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------------------


def check(predicate: Callable[["Context"], Any], /) -> Callable[[T], T]:
    """``@commands.check(lambda ctx: …)`` (sync or async)."""

    def decorator(func: Any) -> Any:
        if isinstance(func, Command):
            func.checks.append(predicate)
        else:
            if not hasattr(func, "__commands_checks__"):
                func.__commands_checks__ = []
            func.__commands_checks__.append(predicate)
        return func

    if inspect.iscoroutinefunction(predicate):
        decorator.predicate = predicate  # type: ignore[attr-defined]
    else:
        @functools.wraps(predicate)
        async def wrapper(ctx: "Context") -> Any:
            return predicate(ctx)

        decorator.predicate = wrapper  # type: ignore[attr-defined]
    return decorator  # type: ignore[return-value]


def check_any(*checks: Any) -> Callable[[T], T]:
    unwrapped = []
    for wrapped in checks:
        try:
            pred = wrapped.predicate
        except AttributeError:
            raise TypeError(f"{wrapped!r} must be wrapped by commands.check decorator") from None
        unwrapped.append(pred)

    async def predicate(ctx: "Context") -> bool:
        errors = []
        for func in unwrapped:
            try:
                value = await func(ctx)
            except CheckFailure as e:
                errors.append(e)
            else:
                if value:
                    return True
        raise CheckAnyFailure(unwrapped, errors)

    return check(predicate)


def _role_match(member: Any, item: Any) -> bool:
    roles = getattr(member, "roles", [])
    if isinstance(item, str):
        return any(r.id == item or r.name == item for r in roles)
    return any(r.id == getattr(item, "id", item) for r in roles)


def has_role(item: Union[str, Any], /) -> Callable[[T], T]:
    def predicate(ctx: "Context") -> bool:
        if ctx.community is None:
            raise NoPrivateMessage()
        if not _role_match(ctx.author, item):
            raise MissingRole(item)
        return True

    return check(predicate)


def has_any_role(*items: Any) -> Callable[[T], T]:
    def predicate(ctx: "Context") -> bool:
        if ctx.community is None:
            raise NoPrivateMessage()
        if any(_role_match(ctx.author, i) for i in items):
            return True
        raise MissingAnyRole(list(items))

    return check(predicate)


def bot_has_role(item: Any, /) -> Callable[[T], T]:
    def predicate(ctx: "Context") -> bool:
        if ctx.community is None:
            raise NoPrivateMessage()
        if not _role_match(ctx.me, item):
            raise BotMissingRole(item)
        return True

    return check(predicate)


def bot_has_any_role(*items: Any) -> Callable[[T], T]:
    def predicate(ctx: "Context") -> bool:
        if ctx.community is None:
            raise NoPrivateMessage()
        if any(_role_match(ctx.me, i) for i in items):
            return True
        raise BotMissingAnyRole(list(items))

    return check(predicate)


def _missing_perms(member: Any, channel: Any, perms: Dict[str, bool]) -> List[str]:
    from ...permissions import DISCORD_ONLY, VALID_FLAGS

    invalid = set(perms) - set(VALID_FLAGS) - DISCORD_ONLY
    if invalid:
        raise TypeError(f"Invalid permission(s): {', '.join(sorted(invalid))}")
    if perms.get("administrator"):
        if getattr(member, "is_owner", lambda: False)() or getattr(member, "is_admin", lambda: False)():
            return [p for p in perms if p != "administrator" and p in VALID_FLAGS and not member.can(p)]
        return ["administrator"]
    if channel is not None and hasattr(channel, "permissions_for") and not isinstance(channel, DMChannel):
        resolved = channel.permissions_for(member)
    else:
        resolved = getattr(member, "guild_permissions", None)
    if resolved is None:
        return []
    return [p for p, v in perms.items() if p in VALID_FLAGS and getattr(resolved, p) != v]


def has_permissions(**perms: bool) -> Callable[[T], T]:
    """``@commands.has_permissions(kick_members=True)`` (owners always pass)."""

    def predicate(ctx: "Context") -> bool:
        if ctx.community is None:
            return True  # discord.py: permissions in DMs are implicitly granted
        if ctx.author.is_owner():
            return True
        missing = _missing_perms(ctx.author, ctx.channel, perms)
        if missing:
            raise MissingPermissions(missing)
        return True

    return check(predicate)


def bot_has_permissions(**perms: bool) -> Callable[[T], T]:
    def predicate(ctx: "Context") -> bool:
        if ctx.community is None:
            return True
        me = ctx.me
        if me.is_owner():
            return True
        missing = _missing_perms(me, ctx.channel, perms)
        if missing:
            raise BotMissingPermissions(missing)
        return True

    return check(predicate)


def has_guild_permissions(**perms: bool) -> Callable[[T], T]:
    def predicate(ctx: "Context") -> bool:
        if ctx.community is None:
            raise NoPrivateMessage()
        if ctx.author.is_owner():
            return True
        missing = _missing_perms(ctx.author, None, perms)
        if missing:
            raise MissingPermissions(missing)
        return True

    return check(predicate)


def bot_has_guild_permissions(**perms: bool) -> Callable[[T], T]:
    def predicate(ctx: "Context") -> bool:
        if ctx.community is None:
            raise NoPrivateMessage()
        missing = _missing_perms(ctx.me, None, perms)
        if missing:
            raise BotMissingPermissions(missing)
        return True

    return check(predicate)


def dm_only() -> Callable[[T], T]:
    def predicate(ctx: "Context") -> bool:
        if ctx.community is not None:
            raise PrivateMessageOnly()
        return True

    return check(predicate)


def guild_only() -> Callable[[T], T]:
    def predicate(ctx: "Context") -> bool:
        if ctx.community is None:
            raise NoPrivateMessage()
        return True

    return check(predicate)


community_only = guild_only


def is_owner() -> Callable[[T], T]:
    """Only the bot's owner(s) (``Bot(owner_id=…)`` / ``owner_ids``)."""

    async def predicate(ctx: "Context") -> bool:
        if not await ctx.bot.is_owner(ctx.author):
            raise NotOwner("You do not own this bot.")
        return True

    return check(predicate)


def is_admin() -> Callable[[T], T]:
    """Vector extra: the author is a Community owner or admin."""

    def predicate(ctx: "Context") -> bool:
        if ctx.community is None:
            raise NoPrivateMessage()
        if ctx.author.is_owner() or ctx.author.is_admin():
            return True
        raise MissingPermissions(["administrator"])

    return check(predicate)


def is_nsfw() -> Callable[[T], T]:
    """Vector has no NSFW flag: passes in DMs, fails in Community channels."""

    def predicate(ctx: "Context") -> bool:
        if ctx.community is None:
            return True
        raise NSFWChannelRequired(ctx.channel)

    return check(predicate)


def cooldown(rate: int, per: float, type: Any = BucketType.default) -> Callable[[T], T]:
    """``@commands.cooldown(1, 30, commands.BucketType.user)``."""

    def decorator(func: Any) -> Any:
        if isinstance(func, Command):
            func._buckets = CooldownMapping(Cooldown(rate, per), type)
        else:
            func.__commands_cooldown__ = CooldownMapping(Cooldown(rate, per), type)
        return func

    return decorator


def dynamic_cooldown(cooldown: Callable[["Context"], Optional[Cooldown]], type: Any) -> Callable[[T], T]:
    def decorator(func: Any) -> Any:
        mapping = DynamicCooldownMapping(cooldown, type)
        if isinstance(func, Command):
            func._buckets = mapping
        else:
            func.__commands_cooldown__ = mapping
        return func

    return decorator


def max_concurrency(number: int, per: Any = BucketType.default, *, wait: bool = False) -> Callable[[T], T]:
    def decorator(func: Any) -> Any:
        value = MaxConcurrency(number, per=per, wait=wait)
        if isinstance(func, Command):
            func._max_concurrency = value
        else:
            func.__commands_max_concurrency__ = value
        return func

    return decorator


def before_invoke(coro: Callable[..., Any], /) -> Callable[[T], T]:
    def decorator(func: Any) -> Any:
        if isinstance(func, Command):
            func.before_invoke(coro)
        else:
            func.__before_invoke__ = coro
        return func

    return decorator


def after_invoke(coro: Callable[..., Any], /) -> Callable[[T], T]:
    def decorator(func: Any) -> Any:
        if isinstance(func, Command):
            func.after_invoke(coro)
        else:
            func.__after_invoke__ = coro
        return func

    return decorator
