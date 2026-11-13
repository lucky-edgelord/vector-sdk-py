"""Messages, attachments, reactions and the raw event payloads."""

from __future__ import annotations

import asyncio
import datetime
import io
import json
import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from .utils import MISSING, from_ms

if TYPE_CHECKING:
    from .channel import DMChannel, TextChannel
    from .community import Community
    from .embeds import Embed
    from .state import ConnectionState
    from .user import Member, User
    from .xdc import XdcApp

__all__ = (
    "Message", "PartialMessage", "Attachment", "Reaction", "MessageReference", "LinkPreview",
    "RawMessageDeletePayload", "RawMessageUpdateEvent", "RawReactionActionEvent", "RawTypingEvent",
    "RawMemberRemoveEvent", "EditEntry",
)


class Attachment:
    """A file on a message. ``await attachment.read()`` downloads and decrypts it."""

    __slots__ = ("_state", "raw", "id", "filename", "extension", "size", "url", "path", "width", "height",
                 "blurhash", "spoiler", "_author", "xdc_topic")

    def __init__(self, state: "ConnectionState", data: Dict[str, Any], author_npub: Optional[str]):
        self._state = state
        self.raw = data
        self.id: str = data.get("id", "")
        ext = data.get("extension", "")
        self.extension: str = ext
        self.filename: str = data.get("name") or (f"{self.id[:12]}.{ext}" if ext else self.id[:12])
        self.size: int = int(data.get("size") or 0)
        self.url: str = data.get("url", "")
        self.path: str = data.get("path", "")
        meta = data.get("img_meta") or {}
        self.width: Optional[int] = meta.get("width")
        self.height: Optional[int] = meta.get("height")
        self.blurhash: Optional[str] = meta.get("blurhash")
        self.spoiler = self.filename.startswith("SPOILER_")
        self.xdc_topic: Optional[str] = data.get("webxdc_topic")
        self._author = author_npub

    @property
    def content_type(self) -> Optional[str]:
        import mimetypes

        return mimetypes.types_map.get("." + self.extension.lower()) if self.extension else None

    @property
    def proxy_url(self) -> str:
        return self.url

    @property
    def content_hash(self) -> str:
        return self.id

    def is_spoiler(self) -> bool:
        return self.spoiler

    def is_image(self) -> bool:
        return self.extension.lower() in ("png", "jpg", "jpeg", "gif", "webp", "avif", "bmp", "heic")

    def is_video(self) -> bool:
        return self.extension.lower() in ("mp4", "mov", "webm", "mkv", "avi", "m4v")

    def is_audio(self) -> bool:
        return self.extension.lower() in ("mp3", "ogg", "opus", "wav", "flac", "m4a", "aac")

    def is_xdc(self) -> bool:
        return self.extension.lower() == "xdc"

    async def read(self, *, use_cached: bool = True) -> bytes:
        if use_cached and self.path and os.path.exists(self.path):
            with open(self.path, "rb") as f:
                return f.read()
        return await self._state.native.download_attachment(json.dumps(self.raw), self._author)

    async def save(self, fp: Union[str, os.PathLike, io.BufferedIOBase], *, seek_begin: bool = True, use_cached: bool = True) -> int:
        data = await self.read(use_cached=use_cached)
        if isinstance(fp, io.BufferedIOBase):
            n = fp.write(data)
            if seek_begin:
                fp.seek(0)
            return n
        with open(fp, "wb") as f:
            return f.write(data)

    async def to_file(self, *, filename: Optional[str] = MISSING, spoiler: bool = False, use_cached: bool = True):
        from .file import File

        return File(await self.read(use_cached=use_cached), filename=self.filename if filename is MISSING else filename, spoiler=spoiler)

    def __repr__(self) -> str:
        return f"<Attachment filename={self.filename!r} size={self.size}>"


class Reaction:
    """Everyone who reacted to a message with one emoji (like ``discord.Reaction``)."""

    __slots__ = ("message", "emoji", "emoji_url", "count", "me", "_users", "_ids")

    def __init__(self, message: "Message", emoji: str, emoji_url: Optional[str] = None):
        self.message = message
        self.emoji = emoji
        self.emoji_url = emoji_url
        self.count = 0
        self.me = False
        self._users: List[str] = []
        self._ids: Dict[str, str] = {}

    def is_custom_emoji(self) -> bool:
        return self.emoji_url is not None

    async def users(self, *, limit: Optional[int] = None, after: Any = None):
        """Async-iterate who reacted (``async for user in reaction.users()``)."""
        for i, npub in enumerate(self._users):
            if limit is not None and i >= limit:
                return
            yield self.message._author_object(npub)

    async def remove(self, user: Any) -> None:
        """Remove the bot's own reaction (Vector reactions are owned by whoever made them)."""
        await self.message.remove_reaction(self.emoji, user)

    async def clear(self) -> None:
        raise NotImplementedError("Vector reactions can only be removed by the user who added them")

    def __str__(self) -> str:
        return self.emoji

    def __repr__(self) -> str:
        return f"<Reaction emoji={self.emoji!r} count={self.count} me={self.me}>"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Reaction) and other.emoji == self.emoji and other.message.id == self.message.id

    def __hash__(self) -> int:
        return hash((self.message.id, self.emoji))


class MessageReference:
    __slots__ = ("message_id", "channel_id", "guild_id", "resolved", "content", "author_id", "fail_if_not_exists")

    def __init__(self, *, message_id: str, channel_id: Optional[str] = None, guild_id: Optional[str] = None,
                 fail_if_not_exists: bool = True, content: Optional[str] = None, author_id: Optional[str] = None):
        self.message_id = message_id
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.fail_if_not_exists = fail_if_not_exists
        self.resolved: Optional["Message"] = None
        self.content = content
        self.author_id = author_id

    @classmethod
    def from_message(cls, message: "Message", *, fail_if_not_exists: bool = True) -> "MessageReference":
        return cls(message_id=message.id, channel_id=message.channel.id,
                   guild_id=message.community.id if message.community else None)

    @property
    def cached_message(self) -> Optional["Message"]:
        return self.resolved

    def __repr__(self) -> str:
        return f"<MessageReference message_id={self.message_id!r}>"


class LinkPreview:
    __slots__ = ("domain", "title", "description", "image", "url", "type", "favicon")

    def __init__(self, data: Dict[str, Any]):
        self.domain = data.get("domain", "")
        self.title = data.get("og_title") or data.get("title")
        self.description = data.get("og_description") or data.get("description")
        self.image = data.get("og_image")
        self.url = data.get("og_url")
        self.type = data.get("og_type")
        self.favicon = data.get("favicon")

    def __repr__(self) -> str:
        return f"<LinkPreview domain={self.domain!r} title={self.title!r}>"


class EditEntry:
    __slots__ = ("content", "edited_at")

    def __init__(self, data: Dict[str, Any]):
        self.content: str = data.get("content", "")
        self.edited_at = from_ms(data.get("edited_at"))


class PartialMessage:
    """A message known only by id: enough to reply, react, edit or delete."""

    def __init__(self, *, channel: Any, id: str):
        self.channel = channel
        self.id = id
        self._state: "ConnectionState" = channel._state

    @property
    def guild(self) -> Optional["Community"]:
        return getattr(self.channel, "community", None)

    community = guild

    async def _target(self):
        return await self.channel._get_channel_target()

    async def fetch(self) -> "Message":
        return await self.channel.fetch_message(self.id)

    async def add_reaction(self, emoji: Any, /) -> None:
        cid, kind = await self._target()
        emoji_str, url = _emoji_parts(emoji)
        emoji_str = normalize_emoji(emoji_str) or emoji_str
        if url is None and emoji_str.startswith(":") and len(emoji_str) > 2:
            # a custom emoji named by code: look its image up in the bot's equipped packs
            found = self._state.client.get_emoji(emoji_str)
            if found is None:
                raise ValueError(f"unknown custom emoji {emoji_str}; equip its pack with subscribe_emoji_pack()")
            url = found.url
        await self._state.native.channel_react(cid, kind, self.id, emoji_str, url)

    async def remove_reaction(self, emoji: Any, member: Any = None) -> None:
        cid, kind = await self._target()
        await self._state.native.channel_unreact(cid, kind, self.id, _emoji_parts(emoji)[0])

    async def edit(self, content: Optional[Any] = MISSING, *, embed: Optional["Embed"] = MISSING,
                   embeds: List["Embed"] = MISSING, view: Any = MISSING, **ignored: Any) -> "Message":
        cid, kind = await self._target()
        parts = []
        if content is not MISSING and content is not None:
            parts.append(str(content))
        elif content is MISSING and isinstance(self, Message):
            parts.append(self._body)
        all_embeds = []
        if embed is not MISSING and embed is not None:
            all_embeds.append(embed)
        if embeds is not MISSING and embeds:
            all_embeds.extend(embeds)
        parts.extend(e.to_markdown() for e in all_embeds)
        if view is not MISSING and view is not None:
            parts.append(view._legend())
        text = "\n\n".join(p for p in parts if p)
        await self._state.native.channel_edit(cid, kind, self.id, text)
        msg = await self._state.fetch_message(self.id)
        if msg is None and isinstance(self, Message):
            self.content = text
            msg = self
        if view is not MISSING and view is not None and msg is not None:
            await view._start(msg, add_reactions=False)
        return msg  # type: ignore[return-value]

    async def delete(self, *, delay: Optional[float] = None) -> None:
        """Delete the message: your own are deleted, anyone else's are hidden (moderation)."""
        if delay is not None:
            await asyncio.sleep(delay)
        cid, kind = await self._target()
        mine = getattr(self, "mine", True)
        try:
            if mine:
                await self._state.native.channel_delete_message(cid, kind, self.id)
            else:
                await self._state.native.channel_hide(cid, kind, self.id)
        except Exception:
            if delay is None:
                raise

    async def hide(self) -> None:
        cid, kind = await self._target()
        await self._state.native.channel_hide(cid, kind, self.id)

    async def pin(self, *, reason: Optional[str] = None) -> None:
        cid, _ = await self._target()
        await self._state.native.channel_pin(cid, self.id)

    async def unpin(self, *, reason: Optional[str] = None) -> None:
        cid, _ = await self._target()
        await self._state.native.channel_unpin(cid, self.id)

    async def reply(self, content: Optional[Any] = None, **kwargs: Any) -> "Message":
        return await self.channel.send(content, reference=self, **kwargs)

    def to_reference(self, *, fail_if_not_exists: bool = True) -> MessageReference:
        return MessageReference(message_id=self.id, channel_id=getattr(self.channel, "id", None))

    @property
    def jump_url(self) -> str:
        return f"vector://message/{self.id}"

    def __repr__(self) -> str:
        return f"<PartialMessage id={self.id!r}>"

    def __eq__(self, other: Any) -> bool:
        return getattr(other, "id", None) == self.id

    def __hash__(self) -> int:
        return hash(self.id)


def _emoji_parts(emoji: Any):
    """``"👍"`` or ``":custom:"`` (from your packs) or an object with ``.name``/``.url``."""
    if isinstance(emoji, Reaction):
        return emoji.emoji, emoji.emoji_url
    if isinstance(emoji, dict):
        return normalize_emoji(emoji), emoji.get("url")
    if isinstance(emoji, PartialEmoji):
        return str(emoji), emoji.url
    if hasattr(emoji, "url") and hasattr(emoji, "name") and not isinstance(emoji, str):
        name = emoji.name if str(emoji.name).startswith(":") else f":{emoji.name}:"
        return name, emoji.url
    return str(emoji), None


class Message(PartialMessage):
    """A received (or sent) message. Mirrors ``discord.Message``."""

    def __init__(self, *, state: "ConnectionState", channel: Any, data: Dict[str, Any],
                 author_npub: Optional[str], community: Optional["Community"] = None):
        self._state = state
        self.channel = channel
        self._community = community
        self.raw = data
        self.id: str = data.get("id", "")
        self._body: str = data.get("content", "")
        self.mine: bool = bool(data.get("mine"))
        self._author_npub = author_npub or (state.self_npub if self.mine else None)
        self.created_at: datetime.datetime = from_ms(data.get("at") or 0)  # type: ignore[assignment]
        self.expires_at = from_ms(data["expiration"] * 1000) if data.get("expiration") else None
        self.edited: bool = bool(data.get("edited"))
        self.edit_history = [EditEntry(e) for e in (data.get("edit_history") or [])]
        self.edited_at = self.edit_history[-1].edited_at if self.edit_history else None
        self.pending: bool = bool(data.get("pending"))
        self.failed: bool = bool(data.get("failed"))
        self.addressed_bots: List[str] = list(data.get("addressed_bots") or [])
        self.role_mention_ids: List[str] = list(data.get("role_mentions") or [])
        self.emoji_tags: List[Dict[str, Any]] = list(data.get("emoji_tags") or [])
        self.attachments = [Attachment(state, a, self._author_npub) for a in data.get("attachments") or []]
        pm = data.get("preview_metadata")
        self.link_preview = LinkPreview(pm) if pm else None
        self.embeds: List[Any] = []
        self.components: List[Any] = []
        self.stickers: List[Any] = []
        self.tts = False
        self.flags = 0
        self.type = "default"
        self.webhook_id = None
        self.application_id = None
        self.interaction = None
        self.pinned = False
        replied = data.get("replied_to") or ""
        self.reference: Optional[MessageReference] = (
            MessageReference(message_id=replied, channel_id=getattr(channel, "id", None),
                             content=data.get("replied_to_content"), author_id=data.get("replied_to_npub"))
            if replied else None
        )
        if self.reference is not None:
            self.reference.resolved = state._message_cache.get(replied)
        self._build_reactions(data.get("reactions") or [])

    def _build_reactions(self, reactions: List[Dict[str, Any]]) -> None:
        agg: Dict[str, Reaction] = {}
        for r in reactions:
            emoji = r.get("emoji", "")
            rx = agg.get(emoji)
            if rx is None:
                rx = agg[emoji] = Reaction(self, emoji, r.get("emoji_url"))
            rx.count += 1
            rx._users.append(r.get("author_id", ""))
            rx._ids[r.get("id", "")] = r.get("author_id", "")
            if r.get("author_id") == self._state.self_npub:
                rx.me = True
        self.reactions: List[Reaction] = list(agg.values())

    # -- content -------------------------------------------------------------------------

    @property
    def content(self) -> str:
        return self._body

    @content.setter
    def content(self, value: str) -> None:
        self._body = value

    @property
    def clean_content(self) -> str:
        from .utils import escape_mentions

        return escape_mentions(self._body)

    @property
    def system_content(self) -> str:
        return self._body

    # -- who & where ---------------------------------------------------------------------

    @property
    def community(self) -> Optional["Community"]:
        return self._community

    guild = community

    def _author_object(self, npub: str):
        if self._community is not None:
            return self._community._member(npub)
        return self._state.store_user(npub)

    @property
    def author(self) -> Union["User", "Member"]:
        if self.mine:
            if self._community is not None:
                return self._community.me
            return self._state.client.user  # type: ignore[return-value]
        return self._author_object(self._author_npub or "")

    @property
    def mentions(self) -> List[Union["User", "Member"]]:
        import re

        npubs = dict.fromkeys(re.findall(r"(?:nostr:)?(npub1[0-9a-z]{58})", self._body))
        return [self._author_object(n) for n in npubs]

    @property
    def raw_mentions(self) -> List[str]:
        return [u.npub for u in self.mentions]

    @property
    def role_mentions(self) -> List[Any]:
        if self._community is None:
            return []
        return [r for r in self._community.roles if r.id in self.role_mention_ids]

    @property
    def mention_everyone(self) -> bool:
        return "@everyone" in self._body or "@here" in self._body

    @property
    def channel_mentions(self) -> List[Any]:
        return []

    def is_system(self) -> bool:
        return False

    def is_addressed_to(self, npub: str) -> bool:
        return npub in self.addressed_bots

    @property
    def xdc(self) -> Optional["XdcApp"]:
        """The Mini App this message shares, if it carries a ``.xdc`` attachment."""
        if not any(a.is_xdc() for a in self.attachments):
            return None
        from .xdc import XdcApp

        return XdcApp(self._state, self.id)

    def __repr__(self) -> str:
        return f"<Message id={self.id!r} author={self._author_npub!r} content={self._body[:40]!r}>"

    def __str__(self) -> str:
        return self._body

    def _copy_with(self, **changes: Any) -> "Message":
        data = dict(self.raw)
        data.update(changes)
        return Message(state=self._state, channel=self.channel, data=data, author_npub=self._author_npub,
                       community=self._community)


# ---------------------------------------------------------------------------------------
# raw payloads (``on_raw_*`` events fire even when the message isn't cached)
# ---------------------------------------------------------------------------------------


class _Raw:
    def __repr__(self) -> str:
        inner = " ".join(f"{k}={v!r}" for k, v in self.__dict__.items() if not k.startswith("_"))
        return f"<{self.__class__.__name__} {inner}>"


class RawMessageDeletePayload(_Raw):
    def __init__(self, *, message_id: str, channel_id: str, guild_id: Optional[str], by: Optional[str],
                 moderated: bool, at: Optional[int], cached_message: Optional[Message]):
        self.message_id = message_id
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.community_id = guild_id
        self.deleted_by = by
        self.moderated = moderated
        self.deleted_at = from_ms(at)
        self.cached_message = cached_message


class RawMessageUpdateEvent(_Raw):
    def __init__(self, *, message: Message, channel_id: str, guild_id: Optional[str], cached_message: Optional[Message]):
        self.message_id = message.id
        self.message = message
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.community_id = guild_id
        self.data = message.raw
        self.cached_message = cached_message


class RawReactionActionEvent(_Raw):
    def __init__(self, *, message_id: str, channel_id: str, guild_id: Optional[str], user_id: str, emoji: str,
                 emoji_url: Optional[str], event_type: str, member: Any = None, reaction_id: Optional[str] = None,
                 message: Optional[Message] = None):
        self.message_id = message_id
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.community_id = guild_id
        self.user_id = user_id
        self.emoji = emoji
        self.emoji_url = emoji_url
        self.event_type = event_type
        self.member = member
        self.reaction_id = reaction_id
        self.message = message
        self.burst = False


class RawTypingEvent(_Raw):
    def __init__(self, *, channel_id: str, user_id: str, until: Optional[int], guild_id: Optional[str]):
        self.channel_id = channel_id
        self.user_id = user_id
        self.guild_id = guild_id
        self.timestamp = from_ms((until or 0) * 1000 if until and until < 10**11 else until)


class RawMemberRemoveEvent(_Raw):
    def __init__(self, *, user: Any, guild_id: str, channel_id: Optional[str]):
        self.user = user
        self.guild_id = guild_id
        self.community_id = guild_id
        self.channel_id = channel_id


class PartialEmoji(str):
    """An emoji, discord.py-style. Either a unicode emoji (``str()`` is the character) or a Vector **custom emoji**
    from an equipped pack (``str()`` is ``":code:"``, ``url`` is its image).

    Accepts Discord's forms too, so ported code keeps working: ``"<:wave:123>"`` / ``"<a:wave:123>"`` become
    ``":wave:"``. Use it, or just the string ``":wave:"``, anywhere an emoji goes: buttons, select options,
    ``message.add_reaction``.
    """

    _DISCORD = __import__("re").compile(r"^<a?:(?P<name>[\w~-]+):(?P<id>\d*)>$")

    def __new__(cls, *, name: str = "", id: Any = None, animated: bool = False, url: Optional[str] = None):
        name = name or ""
        custom = bool(url) or id is not None or (len(name) > 2 and name.startswith(":") and name.endswith(":"))
        bare = name.strip(":") if custom else name
        obj = super().__new__(cls, f":{bare}:" if custom else name)
        # a pack emoji's id is its code, so ``bot.get_emoji(emoji.id)`` round-trips like on Discord
        obj.name, obj.id, obj.animated, obj.url = bare, (id if id is not None else (bare if custom else None)), animated, url
        obj.available, obj.require_colons, obj.managed = True, custom, False
        return obj

    @classmethod
    def from_str(cls, value: str) -> "PartialEmoji":
        value = str(value).strip()
        m = cls._DISCORD.match(value)
        if m:
            return cls(name=m["name"], id=m["id"] or None, animated=value.startswith("<a:"))
        return cls(name=value)

    def is_custom_emoji(self) -> bool:
        return str(self).startswith(":") and len(self) > 2

    def is_unicode_emoji(self) -> bool:
        return not self.is_custom_emoji()

    async def read(self) -> bytes:
        """The emoji image (custom emoji only)."""
        if not self.url:
            raise ValueError("unicode emoji have no image")
        import asyncio
        import urllib.request

        def get() -> bytes:
            with urllib.request.urlopen(self.url, timeout=15) as r:
                return r.read()

        return await asyncio.get_running_loop().run_in_executor(None, get)

    def __repr__(self) -> str:
        return f"<PartialEmoji name={self.name!r} custom={self.is_custom_emoji()}>"


def normalize_emoji(emoji: Any) -> Optional[str]:
    """Any emoji form -> what Vector reactions use: the unicode character, or ``":code:"`` for a custom emoji."""
    if emoji is None:
        return None
    if isinstance(emoji, dict):
        code = emoji.get("code") or emoji.get("shortcode") or emoji.get("name") or ""
        return f":{code.strip(':')}:"
    if hasattr(emoji, "name") and hasattr(emoji, "url") and not isinstance(emoji, PartialEmoji) and emoji.url:
        return f":{str(emoji.name).strip(':')}:"
    return str(PartialEmoji.from_str(str(emoji)))


Emoji = PartialEmoji
