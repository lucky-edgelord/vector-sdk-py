"""Channels: DMs, Community text/voice/forum channels, and categories."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Union

from .abc import GuildChannel, Messageable, PrivateChannel
from .permissions import PermissionOverwrite, Permissions
from .utils import MISSING

if TYPE_CHECKING:
    from .community import Community
    from .message import Message
    from .role import Role
    from .state import ConnectionState
    from .user import Member, User
    from .voice import VoiceClient, VoiceState
    from .xdc import XdcApp

__all__ = ("DMChannel", "TextChannel", "VoiceChannel", "ForumChannel", "CategoryChannel", "ChannelType",
           "PartialMessageable")


class ChannelType:
    text = "chat"
    private = "dm"
    voice = "voice"
    forum = "forum"
    category = "category"
    news = "chat"
    stage_voice = "voice"
    public_thread = "chat"
    private_thread = "chat"


class _Base(Messageable):
    __slots__ = ()
    id: str

    async def send_xdc(self, path: str) -> "XdcApp":
        """Share a Mini App (``.xdc`` file) into this chat."""
        from .xdc import XdcApp

        cid, kind = await self._get_channel_target()
        data = await self._state.native.channel_send_xdc(cid, kind, str(path))
        return XdcApp(self._state, data["message_id"], data)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, _Base) and other.id == self.id

    def __hash__(self) -> int:
        return hash(self.id)


class DMChannel(_Base, PrivateChannel):
    """A one-to-one chat. Its id is the other person's npub."""

    __slots__ = ("_state", "id")
    type = ChannelType.private

    def __init__(self, state: "ConnectionState", npub: str):
        self._state = state
        self.id = npub

    async def _get_channel_target(self):
        return self.id, "dm"

    @property
    def recipient(self) -> "User":
        return self._state.store_user(self.id)

    @property
    def recipients(self) -> List["User"]:
        return [self.recipient]

    @property
    def me(self):
        return self._state.client.user

    @property
    def guild(self) -> None:
        return None

    community = guild

    def permissions_for(self, obj: Any = None, /) -> Permissions:
        return Permissions.text() | Permissions(Permissions.VALID_FLAGS["view_channel"])

    def __repr__(self) -> str:
        return f"<DMChannel recipient={self.id!r}>"

    def __str__(self) -> str:
        return f"Direct Message with {self.recipient}"


class PartialMessageable(_Base):
    """A channel known only by id (kind auto-detected)."""

    __slots__ = ("_state", "id")

    def __init__(self, state: "ConnectionState", id: str):
        self._state = state
        self.id = id

    async def _get_channel_target(self):
        return self.id, None


class TextChannel(_Base, GuildChannel):
    """A Community channel. Mirrors ``discord.TextChannel``."""

    __slots__ = ("_state", "id", "community", "name", "topic", "category_id", "private", "view", "_raw")

    def __init__(self, state: "ConnectionState", community: "Community", data: Dict[str, Any]):
        self._state = state
        self.community = community
        self.id: str = data.get("channel_id") or data.get("id") or ""
        self._update(data)

    def _update(self, data: Dict[str, Any]) -> None:
        self._raw = data
        self.name: str = data.get("name", "")
        self.topic: Optional[str] = data.get("topic")
        self.category_id: Optional[str] = data.get("category_id")
        self.private: bool = bool(data.get("private"))
        self.view: str = data.get("view") or "chat"

    async def _get_channel_target(self):
        return self.id, "community"

    # -- discord.py surface ---------------------------------------------------------------

    @property
    def guild(self) -> "Community":
        return self.community

    @property
    def type(self) -> str:
        return self.view

    @property
    def mention(self) -> str:
        return f"#{self.name}"

    @property
    def category(self) -> Optional["CategoryChannel"]:
        return self.community.get_category(self.category_id) if self.category_id else None

    @property
    def position(self) -> int:
        chans = self.community.channels
        return chans.index(self) if self in chans else 0

    @property
    def members(self) -> List["Member"]:
        if not self.private:
            return list(self.community.members)
        npubs = self._state.native.community_channel_members(self.community.id, self.id)
        return [self.community._member(n) for n in npubs]

    @property
    def readable(self) -> bool:
        return self.community._readable.get(self.id, True)

    def is_nsfw(self) -> bool:
        return False

    def is_news(self) -> bool:
        return False

    @property
    def slowmode_delay(self) -> int:
        return 0

    @property
    def read_only(self) -> bool:
        return bool(self._raw.get("read_only"))

    @property
    def last_message(self) -> Optional["Message"]:
        return self._state.last_message_in(self.id)

    @property
    def overwrites(self) -> Dict[Any, PermissionOverwrite]:
        """``{Role | Member: PermissionOverwrite}`` (``@everyone`` is the default role)."""
        out: Dict[Any, PermissionOverwrite] = {}
        for o in self._state.native.channel_overwrites(self.id):
            out[self.community._overwrite_target(o["target"])] = PermissionOverwrite.from_pair(o["allow"], o["deny"])
        return out

    def overwrites_for(self, obj: Any) -> PermissionOverwrite:
        for target, ow in self.overwrites.items():
            if getattr(target, "id", None) == getattr(obj, "id", obj):
                return ow
        return PermissionOverwrite()

    @property
    def changed_roles(self) -> List["Role"]:
        from .role import Role

        return [t for t in self.overwrites if isinstance(t, Role) and not t.is_default()]

    def permissions_for(self, obj: Any, /) -> Permissions:
        npub = getattr(obj, "npub", None)
        if npub is None:  # a Role
            perms = Permissions(self.community.default_role.permissions.value | getattr(obj, "permissions", Permissions()).value)
            ow = self.overwrites_for(obj)
            allow, deny = ow.pair()
            perms.handle_overwrite(allow.value, deny.value)
            return perms
        try:
            return Permissions(self._state.native.channel_permissions_of(self.id, npub))
        except Exception:
            return Permissions.none()

    @property
    def permissions_synced(self) -> bool:
        return bool(self._raw.get("synced"))

    async def edit(
        self,
        *,
        name: str = MISSING,
        topic: Optional[str] = MISSING,
        category: Optional["CategoryChannel"] = MISSING,
        position: int = MISSING,
        sync_permissions: bool = MISSING,
        overwrites: Dict[Any, PermissionOverwrite] = MISSING,
        type: str = MISSING,
        view: str = MISSING,
        read_only: bool = MISSING,
        private: bool = MISSING,
        reason: Optional[str] = None,
        **ignored: Any,
    ) -> "TextChannel":
        native = self._state.native
        if name is not MISSING:
            await native.channel_rename(self.id, name)
        if topic is not MISSING:
            await native.channel_set_topic(self.id, topic)
        v = view if view is not MISSING else type
        if v is not MISSING:
            await native.channel_set_view(self.id, v)
        if read_only is not MISSING:
            await native.channel_set_read_only(self.id, read_only)
        if private is not MISSING:
            await native.community_set_channel_private(self.community.id, self.id, private)
        if category is not MISSING or position is not MISSING:
            cat_id = (category.id if category else None) if category is not MISSING else self.category_id
            idx = position if position is not MISSING else 0
            await native.channel_move(self.id, cat_id, idx)
        if sync_permissions is not MISSING and sync_permissions:
            await native.channel_sync_permissions(self.id, self.category_id)
        if overwrites is not MISSING:
            for target, ow in overwrites.items():
                await self.set_permissions(target, overwrite=ow)
        await self.community._refresh_channels()
        return self.community.get_channel(self.id) or self  # type: ignore[return-value]

    async def set_permissions(self, target: Any, *, overwrite: Optional[PermissionOverwrite] = MISSING,
                              reason: Optional[str] = None, **permissions: Optional[bool]) -> None:
        """``await channel.set_permissions(guild.default_role, send_messages=False)``."""
        kind, tid = self.community._target_of(target)
        if overwrite is None:
            await self._state.native.channel_clear_overwrite(self.id, kind, tid)
            return
        if overwrite is MISSING:
            overwrite = self.overwrites_for(target)
            overwrite.update(**permissions)
        allow, deny = overwrite.pair()
        if allow.value == 0 and deny.value == 0:
            await self._state.native.channel_clear_overwrite(self.id, kind, tid)
        else:
            await self._state.native.channel_set_overwrite(self.id, kind, tid, allow.value, deny.value)

    async def delete(self, *, reason: Optional[str] = None) -> None:
        await self._state.native.community_delete_channel(self.community.id, self.id)

    async def move(self, *, beginning: bool = False, end: bool = False, offset: int = 0,
                   category: Optional["CategoryChannel"] = MISSING, **kwargs: Any) -> None:
        cat = self.category if category is MISSING else category
        siblings = [c for c in self.community.channels if c.category_id == (cat.id if cat else None) and c.id != self.id]
        idx = 0 if beginning else len(siblings) if end else max(0, min(len(siblings), self.position + offset))
        await self._state.native.channel_move(self.id, cat.id if cat else None, idx)

    async def clone(self, *, name: Optional[str] = None, reason: Optional[str] = None) -> "TextChannel":
        return await self.community.create_text_channel(name or self.name, category=self.category, topic=self.topic,
                                                        private=self.private)

    async def create_webhook(self, *, name: str, avatar: Any = None, reason: Optional[str] = None) -> Any:
        """Create a Discord-style webhook for this channel (``discord.TextChannel.create_webhook``)."""
        from .webhook import Webhook

        client = self._state.client
        row, token = client.webhook_store.create(name, self.id, self.community.id, None)
        return Webhook._from_row(row, token, client)

    async def webhooks(self) -> List[Any]:
        """This channel's webhooks. Tokens aren't kept, so ``url`` is only known when the webhook was created."""
        from .webhook import Webhook

        client = self._state.client
        return [Webhook._from_row(r, None, client) for r in client.webhook_store.list(channel_id=self.id)]

    async def create_invite(self, *, max_age: int = 0, label: Optional[str] = None, **ignored: Any):
        return await self.community.create_invite(max_age=max_age, label=label)

    async def invites(self):
        return await self.community.invites()

    async def pins(self) -> List["Message"]:
        out = []
        for p in self._state.native.channel_pins(self.id):
            m = await self._state.fetch_message(p["message_id"])
            if m is not None:
                m.pinned = True
                out.append(m)
        return out

    async def purge(
        self,
        *,
        limit: Optional[int] = 100,
        check: Callable[["Message"], bool] = MISSING,
        before: Any = None,
        after: Any = None,
        oldest_first: bool = False,
        bulk: bool = True,
        reason: Optional[str] = None,
    ) -> List["Message"]:
        """Delete (own) or hide (others') messages. Needs ``manage_messages`` for others'."""
        deleted = []
        async for msg in self.history(limit=limit, before=before, after=after, oldest_first=oldest_first):
            if check is not MISSING and not check(msg):
                continue
            try:
                await msg.delete()
                deleted.append(msg)
            except Exception:
                continue
        return deleted

    async def grant_access(self, member: Any) -> None:
        """Give a member access to this private channel."""
        await self._state.native.community_grant_access(self.community.id, self.id, getattr(member, "npub", member))

    async def revoke_access(self, member: Any) -> None:
        await self._state.native.community_revoke_access(self.community.id, self.id, getattr(member, "npub", member))

    def access(self) -> Any:
        return self._state.native.community_channel_access(self.community.id, self.id)

    async def sync(self, max_events: int = 500, *, since: Optional[datetime.datetime] = None) -> int:
        """Pull a page of this channel's history from relays. Returns how many messages were new."""
        since_ms = int(since.timestamp() * 1000) if since else None
        return await self._state.native.channel_sync(self.id, max_events, since_ms=since_ms)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id[:12]!r} name={self.name!r}>"

    def __str__(self) -> str:
        return self.name


class VoiceChannel(TextChannel):
    """A voice Channel (it also has a text chat, like Discord's)."""

    __slots__ = ()

    @property
    def voice_states(self) -> Dict[str, "VoiceState"]:
        from .voice import VoiceState

        return {s["npub"]: VoiceState(self, s) for s in self._state.native.channel_voice_members(self.id)}

    @property
    def members(self) -> List["Member"]:  # type: ignore[override]
        """Who is in the call right now (discord.py semantics)."""
        return [self.community._member(n) for n in self.voice_states]

    async def connect(self, *, timeout: float = 60.0, reconnect: bool = True, self_mute: bool = False,
                      self_deaf: bool = False, cls: Any = None) -> "VoiceClient":
        from .voice import VoiceClient

        native_call = await self._state.native.channel_join_voice(self.id)
        vc = (cls or VoiceClient)(self._state.client, self, native_call)
        if self_mute:
            vc.mute(True)
        if self_deaf:
            vc.deafen(True)
        self._state.voice_clients[self.community.id] = vc
        return vc

    join = connect


class ForumChannel(TextChannel):
    __slots__ = ()


class CategoryChannel(GuildChannel):
    """A Community category. Mirrors ``discord.CategoryChannel``."""

    __slots__ = ("_state", "community", "id", "name", "_raw")
    type = ChannelType.category

    def __init__(self, state: "ConnectionState", community: "Community", data: Dict[str, Any]):
        self._state = state
        self.community = community
        self.id: str = data.get("category_id") or data.get("id") or ""
        self.name: str = data.get("name", "")
        self._raw = data

    @property
    def guild(self) -> "Community":
        return self.community

    @property
    def channels(self) -> List[TextChannel]:
        return [c for c in self.community.channels if c.category_id == self.id]

    @property
    def text_channels(self) -> List[TextChannel]:
        return [c for c in self.channels if c.view == "chat"]

    @property
    def voice_channels(self) -> List[TextChannel]:
        return [c for c in self.channels if c.view == "voice"]

    @property
    def position(self) -> int:
        cats = self.community.categories
        return cats.index(self) if self in cats else 0

    @property
    def mention(self) -> str:
        return self.name

    @property
    def overwrites(self) -> Dict[Any, PermissionOverwrite]:
        return {}

    async def edit(self, *, name: str = MISSING, position: int = MISSING, reason: Optional[str] = None, **ignored: Any) -> "CategoryChannel":
        if name is not MISSING:
            await self._state.native.category_rename(self.community.id, self.id, name)
            self.name = name
        if position is not MISSING:
            await self._state.native.category_move(self.community.id, self.id, position)
        return self

    async def delete(self, *, reason: Optional[str] = None) -> None:
        await self._state.native.category_delete(self.community.id, self.id)

    async def set_permissions(self, target: Any, *, overwrite: Optional[PermissionOverwrite] = MISSING,
                              reason: Optional[str] = None, **permissions: Optional[bool]) -> None:
        kind, tid = self.community._target_of(target)
        if overwrite is None:
            overwrite = PermissionOverwrite()
        elif overwrite is MISSING:
            overwrite = PermissionOverwrite(**permissions)
        allow, deny = overwrite.pair()
        await self._state.native.category_set_overwrite(self.community.id, self.id, kind, tid, allow.value, deny.value)

    async def create_text_channel(self, name: str, **options: Any) -> TextChannel:
        return await self.community.create_text_channel(name, category=self, **options)

    async def create_voice_channel(self, name: str, **options: Any) -> TextChannel:
        return await self.community.create_voice_channel(name, category=self, **options)

    async def create_forum(self, name: str, **options: Any) -> TextChannel:
        return await self.community.create_forum(name, category=self, **options)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, CategoryChannel) and other.id == self.id

    def __hash__(self) -> int:
        return hash(self.id)

    def __repr__(self) -> str:
        return f"<CategoryChannel id={self.id[:12]!r} name={self.name!r}>"

    def __str__(self) -> str:
        return self.name


def channel_from_info(state: "ConnectionState", community: "Community", data: Dict[str, Any]) -> TextChannel:
    view = data.get("view") or "chat"
    cls = {"voice": VoiceChannel, "forum": ForumChannel}.get(view, TextChannel)
    return cls(state, community, data)
