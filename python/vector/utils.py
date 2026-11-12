"""Helpers mirroring ``discord.utils``."""

from __future__ import annotations

import asyncio
import datetime
import re
from typing import Any, AsyncIterable, Awaitable, Callable, Iterable, List, Optional, Sequence, TypeVar, Union

__all__ = (
    "MISSING", "get", "find", "utcnow", "format_dt", "sleep_until", "escape_markdown", "remove_markdown",
    "escape_mentions", "as_chunks", "maybe_coroutine", "from_ms", "to_ms", "oauth_url", "snowflake_time",
)

T = TypeVar("T")


class _Missing:
    __slots__ = ()

    def __eq__(self, other: Any) -> bool:
        return False

    def __bool__(self) -> bool:
        return False

    def __hash__(self) -> int:
        return 0

    def __repr__(self) -> str:
        return "..."


MISSING: Any = _Missing()


def find(predicate: Callable[[T], Any], iterable: Iterable[T]) -> Optional[T]:
    """The first element for which ``predicate`` is truthy, else ``None``."""
    for element in iterable:
        if predicate(element):
            return element
    return None


def get(iterable: Iterable[T], **attrs: Any) -> Optional[T]:
    """The first element whose attributes match: ``get(guild.roles, name="Mods")``.

    Nested attributes use ``__``: ``get(members, author__name="kit")``.
    """
    converted = [(attr.split("__"), value) for attr, value in attrs.items()]
    for elem in iterable:
        ok = True
        for path, value in converted:
            obj: Any = elem
            for part in path:
                obj = getattr(obj, part, MISSING)
            if obj != value:
                ok = False
                break
        if ok:
            return elem
    return None


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def from_ms(ms: Optional[int]) -> Optional[datetime.datetime]:
    if ms is None:
        return None
    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc)


def to_ms(dt: datetime.datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return int(dt.timestamp() * 1000)


def snowflake_time(id: Any) -> datetime.datetime:  # pragma: no cover - Vector ids are hashes
    raise TypeError("Vector ids are content hashes, not snowflakes: use message.created_at instead")


def format_dt(dt: datetime.datetime, /, style: Optional[str] = None) -> str:
    """``<t:UNIX:STYLE>``. Vector renders these in each reader's own timezone, like Discord."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    if style is None:
        return f"<t:{int(dt.timestamp())}>"
    return f"<t:{int(dt.timestamp())}:{style}>"


async def sleep_until(when: datetime.datetime, result: Optional[T] = None) -> Optional[T]:
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    delta = (when - utcnow()).total_seconds()
    await asyncio.sleep(max(delta, 0))
    return result


_MARKDOWN_ESCAPE = re.compile(r"([_\\~|\*`]|^>(?:>>)?\s|^#{1,3}\s|^-#\s)", re.MULTILINE)
_MARKDOWN_STRIP = re.compile(r"(?:\*|_|~|`|\|)")
_URL = re.compile(r"(<[^: >]+:\/[^ >]+>|(?:https?|steam):\/\/[^\s<]+[^<.,:;\"\'\]\s])")


def escape_markdown(text: str, *, as_needed: bool = False, ignore_links: bool = True) -> str:
    if ignore_links:
        parts = _URL.split(text)
        return "".join(p if _URL.fullmatch(p) else _MARKDOWN_ESCAPE.sub(r"\\\1", p) for p in parts)
    return _MARKDOWN_ESCAPE.sub(r"\\\1", text)


def remove_markdown(text: str, *, ignore_links: bool = True) -> str:
    return _MARKDOWN_STRIP.sub("", text)


def escape_mentions(text: str) -> str:
    return re.sub(r"@(everyone|here)", "@​\\1", text)


def as_chunks(iterator: Iterable[T], max_size: int) -> Iterable[List[T]]:
    if max_size <= 0:
        raise ValueError("Chunk sizes must be greater than 0.")
    chunk: List[T] = []
    for item in iterator:
        chunk.append(item)
        if len(chunk) == max_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


async def maybe_coroutine(f: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    value = f(*args, **kwargs)
    if asyncio.iscoroutine(value) or isinstance(value, Awaitable):
        return await value
    return value


def oauth_url(*args: Any, **kwargs: Any) -> str:
    """Vector bots join by invite, not OAuth. Use ``community.create_invite()`` and share the link."""
    raise NotImplementedError("Vector has no OAuth: invite the bot's npub to a Community instead")


def _shorten(npub: str) -> str:
    return npub[:12] + "…" if len(npub) > 16 else npub
