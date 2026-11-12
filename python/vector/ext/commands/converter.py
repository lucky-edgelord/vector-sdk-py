"""Argument converters: type hints turn text into objects, as in ``discord.ext.commands``."""

from __future__ import annotations

import inspect
import re
import sys
from typing import (
    TYPE_CHECKING, Any, Dict, Generic, Iterable, List, Literal, Optional, Tuple, Type, TypeVar, Union,
    get_args, get_origin,
)

from ...channel import CategoryChannel, ForumChannel, TextChannel, VoiceChannel
from ...colour import Colour
from ...community import Community
from ...flags import Object
from ...message import Attachment, Message, PartialMessage
from ...role import Role
from ...user import Member, User
from .errors import (
    BadArgument, BadBoolArgument, BadColourArgument, BadLiteralArgument, BadUnionArgument, ChannelNotFound,
    CommandError, ConversionError, GuildNotFound, MemberNotFound, MessageNotFound, NoPrivateMessage, RangeError,
    RoleNotFound, UserNotFound,
)

if TYPE_CHECKING:
    from .context import Context

__all__ = (
    "Converter", "MemberConverter", "UserConverter", "RoleConverter", "TextChannelConverter", "VoiceChannelConverter",
    "CategoryChannelConverter", "ForumChannelConverter", "GuildChannelConverter", "CommunityConverter",
    "GuildConverter", "MessageConverter", "PartialMessageConverter", "ColourConverter", "ColorConverter",
    "ObjectConverter", "clean_content", "Greedy", "Range", "run_converters", "CONVERTER_MAPPING",
)

T = TypeVar("T")
_NPUB = re.compile(r"(?:nostr:)?(npub1[0-9a-z]{58})")
_HEX64 = re.compile(r"[0-9a-fA-F]{64}")


class Converter(Generic[T]):
    """Subclass and implement ``async def convert(self, ctx, argument)``."""

    async def convert(self, ctx: "Context", argument: str) -> T:
        raise NotImplementedError("Derived classes need to implement this.")


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


class MemberConverter(Converter[Member]):
    """npub / ``nostr:npub`` mention / name / display name / nickname, within the Community."""

    async def convert(self, ctx: "Context", argument: str) -> Member:
        community = ctx.community
        m = _NPUB.search(argument)
        if community is None:
            if m:
                return await UserConverter().convert(ctx, argument)  # type: ignore[return-value]
            raise MemberNotFound(argument)
        if m:
            member = community._member(m.group(1))
            await ctx._state.ensure_profile(member.npub)
            return member
        wanted = _norm(argument.lstrip("@"))
        for member in community.members:
            if wanted in (_norm(member.name), _norm(member.display_name), _norm(member.nick), _norm(member.global_name)):
                return member
        raise MemberNotFound(argument)


class UserConverter(Converter[User]):
    async def convert(self, ctx: "Context", argument: str) -> User:
        m = _NPUB.search(argument)
        if m:
            return await ctx._state.ensure_profile(m.group(1))
        wanted = _norm(argument.lstrip("@"))
        for user in ctx._state._users.values():
            if wanted in (_norm(user.name), _norm(user.display_name), _norm(user.global_name)):
                return user
        raise UserNotFound(argument)


class RoleConverter(Converter[Role]):
    async def convert(self, ctx: "Context", argument: str) -> Role:
        community = ctx.community
        if community is None:
            raise NoPrivateMessage()
        arg = argument.strip()
        role = community.get_role(arg)
        if role is None:
            wanted = _norm(arg.lstrip("@"))
            role = next((r for r in community.roles if _norm(r.name) == wanted), None)
        if role is None:
            raise RoleNotFound(argument)
        return role


class _ChannelConverter(Converter[Any]):
    kinds: Tuple[type, ...] = (TextChannel,)

    async def convert(self, ctx: "Context", argument: str) -> Any:
        communities = [ctx.community] if ctx.community else ctx.bot.communities
        arg = argument.strip().lstrip("#")
        for c in communities:
            for ch in list(c.channels) + list(c.categories):
                if not isinstance(ch, self.kinds):
                    continue
                if ch.id == arg or _norm(ch.name) == _norm(arg):
                    return ch
        raise ChannelNotFound(argument)


class TextChannelConverter(_ChannelConverter):
    kinds = (TextChannel,)

    async def convert(self, ctx: "Context", argument: str) -> Any:
        ch = await super().convert(ctx, argument)
        if isinstance(ch, (VoiceChannel, ForumChannel)) and type(ch) is not TextChannel:
            pass
        return ch


class VoiceChannelConverter(_ChannelConverter):
    kinds = (VoiceChannel,)


class ForumChannelConverter(_ChannelConverter):
    kinds = (ForumChannel,)


class CategoryChannelConverter(_ChannelConverter):
    kinds = (CategoryChannel,)


class GuildChannelConverter(_ChannelConverter):
    kinds = (TextChannel, CategoryChannel)


class CommunityConverter(Converter[Community]):
    async def convert(self, ctx: "Context", argument: str) -> Community:
        arg = argument.strip()
        c = ctx.bot.get_community(arg)
        if c is None:
            c = next((g for g in ctx.bot.communities if _norm(g.name) == _norm(arg)), None)
        if c is None:
            raise GuildNotFound(argument)
        return c


GuildConverter = CommunityConverter


class MessageConverter(Converter[Message]):
    async def convert(self, ctx: "Context", argument: str) -> Message:
        m = _HEX64.search(argument)
        if not m:
            raise MessageNotFound(argument)
        msg = await ctx._state.fetch_message(m.group(0).lower())
        if msg is None:
            raise MessageNotFound(argument)
        return msg


class PartialMessageConverter(Converter[PartialMessage]):
    async def convert(self, ctx: "Context", argument: str) -> PartialMessage:
        m = _HEX64.search(argument)
        if not m:
            raise MessageNotFound(argument)
        return PartialMessage(channel=ctx.channel, id=m.group(0).lower())


class ColourConverter(Converter[Colour]):
    async def convert(self, ctx: "Context", argument: str) -> Colour:
        arg = argument.strip().replace(" ", "_")
        method = getattr(Colour, arg.lower(), None)
        if arg.lower() not in ("from_rgb", "from_hsv", "from_str", "random", "to_rgb", "value", "r", "g", "b") and callable(method):
            return method()
        try:
            return Colour.from_str(argument)
        except Exception:
            raise BadColourArgument(argument) from None


ColorConverter = ColourConverter


class ObjectConverter(Converter[Object]):
    async def convert(self, ctx: "Context", argument: str) -> Object:
        return Object(id=argument.strip())


class clean_content(Converter[str]):
    def __init__(self, *, fix_channel_mentions: bool = False, use_nicknames: bool = True, escape_markdown: bool = False,
                 remove_markdown: bool = False):
        self.escape = escape_markdown
        self.remove = remove_markdown

    async def convert(self, ctx: "Context", argument: str) -> str:
        from ...utils import escape_markdown, escape_mentions, remove_markdown

        result = escape_mentions(argument)
        if self.escape:
            result = escape_markdown(result)
        elif self.remove:
            result = remove_markdown(result)
        return result


class Greedy(Generic[T]):
    """``Greedy[int]``: consume as many arguments as convert (prefix commands)."""

    __slots__ = ("converter",)

    def __init__(self, *, converter: Any):
        self.converter = converter

    def __class_getitem__(cls, params: Any) -> "Greedy":
        if isinstance(params, tuple):
            params = params[0]
        return cls(converter=params)

    def __repr__(self) -> str:
        return f"Greedy[{getattr(self.converter, '__name__', self.converter)!r}]"


class Range:
    """``Range[int, 1, 10]`` / ``Range[float, 0.0, 1.0]`` / ``Range[str, 1, 100]`` (length)."""

    def __init__(self, *, annotation: Any, min: Any = None, max: Any = None):
        self.annotation, self.min, self.max = annotation, min, max

    def __class_getitem__(cls, obj: Any) -> "Range":
        if not isinstance(obj, tuple):
            raise TypeError("Range accepts (type, min[, max])")
        if len(obj) == 2:
            obj = (*obj, None)
        annotation, lo, hi = obj
        return cls(annotation=annotation, min=lo, max=hi)

    async def convert(self, ctx: "Context", value: Any) -> Any:
        if self.annotation is str:
            n = len(str(value))
            if (self.min is not None and n < self.min) or (self.max is not None and n > self.max):
                raise RangeError(value, self.min, self.max)
            return str(value)
        value = await run_converters(ctx, self.annotation, value, None)
        if (self.min is not None and value < self.min) or (self.max is not None and value > self.max):
            raise RangeError(value, self.min, self.max)
        return value

    def __repr__(self) -> str:
        return f"Range[{self.annotation.__name__}, {self.min!r}, {self.max!r}]"


def _convert_bool(argument: Any) -> bool:
    if isinstance(argument, bool):
        return argument
    lowered = str(argument).lower()
    if lowered in ("yes", "y", "true", "t", "1", "enable", "on"):
        return True
    if lowered in ("no", "n", "false", "f", "0", "disable", "off"):
        return False
    raise BadBoolArgument(lowered)


class _AttachmentConverter(Converter[Attachment]):
    async def convert(self, ctx: "Context", argument: str) -> Attachment:
        if not ctx.message.attachments:
            raise BadArgument("this command needs a file attached")
        return ctx.message.attachments[0]


CONVERTER_MAPPING: Dict[type, Any] = {
    Member: MemberConverter,
    User: UserConverter,
    Role: RoleConverter,
    TextChannel: TextChannelConverter,
    VoiceChannel: VoiceChannelConverter,
    ForumChannel: ForumChannelConverter,
    CategoryChannel: CategoryChannelConverter,
    Community: CommunityConverter,
    Message: MessageConverter,
    PartialMessage: PartialMessageConverter,
    Colour: ColourConverter,
    Object: ObjectConverter,
    Attachment: _AttachmentConverter,
}


def _is_union(t: Any) -> bool:
    origin = get_origin(t)
    if origin is Union:
        return True
    if sys.version_info >= (3, 10):
        import types

        return isinstance(t, types.UnionType)
    return False


async def _actual_conversion(ctx: "Context", converter: Any, argument: Any, param: Any) -> Any:
    if converter is bool:
        return _convert_bool(argument)
    if converter in (str, int, float):
        try:
            return converter(argument)
        except (ValueError, TypeError) as exc:
            name = getattr(param, "name", "argument")
            raise BadArgument(f'Converting to "{converter.__name__}" failed for parameter "{name}".') from exc
    converter = CONVERTER_MAPPING.get(converter, converter)
    try:
        if inspect.isclass(converter) and issubclass(converter, Converter):
            if inspect.ismethod(converter.convert):
                return await converter.convert(ctx, argument)
            return await converter().convert(ctx, argument)
        if isinstance(converter, (Converter, Range)):
            return await converter.convert(ctx, argument)
    except CommandError:
        raise
    except Exception as exc:
        raise ConversionError(converter, exc) from exc
    try:
        result = converter(argument)
        if inspect.isawaitable(result):
            result = await result
        return result
    except CommandError:
        raise
    except Exception as exc:
        name = getattr(converter, "__name__", converter.__class__.__name__)
        raise BadArgument(f'Converting to "{name}" failed for parameter "{getattr(param, "name", "")}".') from exc


async def run_converters(ctx: "Context", converter: Any, argument: Any, param: Any) -> Any:
    """Convert ``argument`` per ``converter`` (a type hint), handling Optional/Union/Literal."""
    if converter is inspect.Parameter.empty or converter is Any:
        return argument
    if isinstance(converter, str):  # postponed annotation that couldn't be resolved
        return argument
    origin = get_origin(converter)
    if _is_union(converter):
        errors = []
        args = get_args(converter)
        for conv in args:
            if conv is type(None):
                continue
            try:
                return await run_converters(ctx, conv, argument, param)
            except CommandError as exc:
                errors.append(exc)
        if type(None) in args:
            return None
        raise BadUnionArgument(param, args, errors)
    if origin is Literal:
        errors = []
        for literal in get_args(converter):
            try:
                value = await _actual_conversion(ctx, type(literal), argument, param)
            except CommandError as exc:
                errors.append(exc)
            else:
                if value == literal:
                    return value
        raise BadLiteralArgument(param, get_args(converter), errors, str(argument))
    if isinstance(converter, Greedy):
        return await run_converters(ctx, converter.converter, argument, param)
    return await _actual_conversion(ctx, converter, argument, param)
