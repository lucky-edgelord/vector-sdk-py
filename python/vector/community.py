"""``Community``: Vector's server, aliased as ``Guild`` so discord.py code reads naturally."""

from __future__ import annotations

import datetime
import time
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional, Sequence, Tuple, Union

from .channel import CategoryChannel, ForumChannel, TextChannel, VoiceChannel, channel_from_info
from .permissions import PermissionOverwrite, Permissions
from .role import Role
from .utils import MISSING, from_ms

if TYPE_CHECKING:
    from .state import ConnectionState
    from .user import Member, User

__all__ = ("Community", "Guild", "Invite", "BanEntry", "AuditLogEntry", "AuditLogAction", "PendingInvite",
           "CommunityPreview", "RaidContainment", "RelayCheck", "RelayMove")


class Invite:
    """A shareable join link."""

    def __init__(self, community: "Community", url: str, data: Optional[Dict[str, Any]] = None):
        data = data or {}
        self.community = community
        self.url = url
        self.code: str = data.get("token") or url.rsplit("/", 1)[-1]
        self.label: Optional[str] = data.get("label")
        self.inviter_id: Optional[str] = data.get("creator") or data.get("creator_npub")
        self.created_at = from_ms(data.get("created_at_ms") or (data.get("created_at") or 0) * 1000) if data else None
        exp = data.get("expires_at_ms") or data.get("expires_at")
        self.expires_at = from_ms(exp if exp and exp > 10**11 else (exp or 0) * 1000) if exp else None
        self.uses: int = int(data.get("join_count") or 0)
        self.raw = data

    @property
    def guild(self) -> "Community":
        return self.community

    @property
    def id(self) -> str:
        return self.code

    @property
    def max_age(self) -> int:
        if not self.expires_at or not self.created_at:
            return 0
        return int((self.expires_at - self.created_at).total_seconds())

    async def delete(self, *, reason: Optional[str] = None) -> None:
        await self.community._state.native.community_revoke_invite(self.community.id, self.code)

    revoke = delete

    def __str__(self) -> str:
        return self.url

    def __repr__(self) -> str:
        return f"<Invite code={self.code!r} label={self.label!r}>"


class BanEntry:
    __slots__ = ("user", "reason")

    def __init__(self, user: "User"):
        self.user = user
        self.reason: Optional[str] = None

    def __repr__(self) -> str:
        return f"<BanEntry user={self.user!r}>"


class AuditLogAction:
    """Action names as they appear on :attr:`AuditLogEntry.action` (snake_case strings)."""

    def __getattr__(self, name: str) -> str:
        return name


AuditLogAction = AuditLogAction()  # type: ignore[misc,assignment]


class AuditLogEntry:
    def __init__(self, community: "Community", data: Dict[str, Any]):
        self.community = community
        self.id: str = data.get("id", "")
        self.created_at = from_ms(data.get("at_ms"))
        self.user_id: str = data.get("actor", "")
        self.action: str = data.get("action", "")
        self.target_data: Optional[Dict[str, Any]] = data.get("target")
        self.changes: Dict[str, Any] = data.get("changes") or {}
        self.partial: bool = bool(data.get("partial"))
        self.reason: Optional[str] = None

    @property
    def guild(self) -> "Community":
        return self.community

    @property
    def user(self) -> "Member":
        return self.community._member(self.user_id)

    @property
    def target(self) -> Any:
        t = self.target_data or {}
        kind = t.get("kind")
        if kind == "member":
            return self.community._member(t["npub"])
        if kind == "everyone":
            return self.community.default_role
        if kind == "role":
            return self.community.get_role(t["id"]) or t
        if kind == "channel":
            return self.community.get_channel(t["id"]) or t
        if kind == "category":
            return self.community.get_category(t["id"]) or t
        return t or None

    def __repr__(self) -> str:
        return f"<AuditLogEntry action={self.action!r} actor={self.user_id[:16]!r}>"


class PendingInvite:
    """An invite *to* the bot (``on_community_invite``). ``await invite.accept()`` joins."""

    def __init__(self, state: "ConnectionState", data: Dict[str, Any]):
        self._state = state
        self.community_id: str = data.get("community_id", "")
        self.name: Optional[str] = data.get("name")
        self.inviter_id: Optional[str] = data.get("inviter_npub")
        self.raw = data

    @property
    def inviter(self) -> Optional["User"]:
        return self._state.store_user(self.inviter_id) if self.inviter_id else None

    async def accept(self) -> "Community":
        await self._state.native.accept_invite(self.community_id)
        return await self._state.add_community(self.community_id, joined=True)

    def __repr__(self) -> str:
        return f"<PendingInvite community_id={self.community_id[:12]!r} name={self.name!r}>"


class CommunityPreview:
    def __init__(self, data: Dict[str, Any]):
        self.id: str = data.get("community_id", "")
        self.name: str = data.get("name", "")
        self.description: Optional[str] = data.get("description")
        self.joined: bool = bool(data.get("joined"))
        self.verified: bool = bool(data.get("verified"))
        self.raw = data

    def __repr__(self) -> str:
        return f"<CommunityPreview name={self.name!r} verified={self.verified}>"


class RaidContainment:
    def __init__(self, data: Dict[str, Any]):
        self.banned: int = data.get("banned", 0)
        self.window_cut: int = data.get("window_cut", 0)
        self.epoch_before: int = data.get("epoch_before", 0)
        self.epoch_after: int = data.get("epoch_after", 0)
        self.raw = data

    def __repr__(self) -> str:
        return f"<RaidContainment banned={self.banned} window_cut={self.window_cut}>"


class RelayCheck:
    def __init__(self, data: Dict[str, Any]):
        self.relay: str = data.get("relay", "")
        self.ok: bool = bool(data.get("ok"))
        self.rate_limited: bool = bool(data.get("rate_limited"))
        self.raw = data


class RelayMove:
    def __init__(self, data: Dict[str, Any]):
        self.relays: List[str] = data.get("relays", [])
        self.added: List[str] = data.get("added", [])
        self.removed: List[str] = data.get("removed", [])
        self.copied: int = data.get("copied", 0)
        self.previous: List[str] = data.get("previous", [])
        self.raw = data


def _now_ms() -> int:
    return int(time.time() * 1000)


class Community:
    """A Vector Community. Everything discord.py's ``Guild`` does that Vector supports."""

    def __init__(self, state: "ConnectionState", id: str):
        self._state = state
        self.id = id
        self.name: str = ""
        self.description: Optional[str] = None
        self._channels: Dict[str, TextChannel] = {}
        self._channel_order: List[str] = []
        self._categories: Dict[str, CategoryChannel] = {}
        self._readable: Dict[str, bool] = {}
        self._roles: Dict[str, Role] = {}
        self._everyone_perms: int = 0
        self._members: Optional[Dict[str, "Member"]] = None
        self.unavailable = False
        self.dissolved = False

    # ------------------------------------------------------------------------------------
    # cache
    # ------------------------------------------------------------------------------------

    async def _refresh(self) -> "Community":
        native = self._state.native
        try:
            self.name = await native.community_name(self.id) or self.name
        except Exception:
            pass
        self.description = native.community_description(self.id)
        await self._refresh_channels()
        self._refresh_roles()
        try:
            await self._refresh_members()
        except Exception:
            pass
        return self

    async def _refresh_channels(self) -> None:
        native = self._state.native
        try:
            infos = native.community_channel_infos(self.id)
        except Exception:
            infos = []
        try:
            listing = await native.community_channels(self.id)
        except Exception:
            listing = []
        self._readable = {c["channel_id"]: c.get("readable", True) for c in listing}
        known = {i["channel_id"] for i in infos}
        for c in listing:  # private channels the bot can't read yet still appear in the listing
            if c["channel_id"] not in known:
                infos.append({"channel_id": c["channel_id"], "name": c.get("name", ""), "private": c.get("private", False)})
        fresh: Dict[str, TextChannel] = {}
        for info in infos:
            existing = self._channels.get(info["channel_id"])
            if existing is not None and type(existing) is type(channel_from_info(self._state, self, info)):
                existing._update(info)
                fresh[existing.id] = existing
            else:
                fresh[info["channel_id"]] = channel_from_info(self._state, self, info)
        self._channels = fresh
        self._channel_order = [i["channel_id"] for i in infos]
        try:
            self._categories = {c["category_id"]: CategoryChannel(self._state, self, c) for c in native.community_categories(self.id)}
        except Exception:
            self._categories = {}

    def _refresh_roles(self) -> None:
        native = self._state.native
        try:
            self._roles = {r["role_id"]: Role(self._state, self, r) for r in native.community_roles(self.id)}
        except Exception:
            self._roles = {}
        try:
            self._everyone_perms = native.community_everyone_permissions(self.id) or 0
        except Exception:
            self._everyone_perms = 0

    async def _refresh_members(self) -> None:
        npubs = await self._state.native.community_members(self.id)
        self._members = {n: self._member(n) for n in npubs}

    def _member(self, npub: str) -> "Member":
        from .user import Member

        if self._members is not None and npub in self._members:
            return self._members[npub]
        return Member(self._state, self, self._state.store_user(npub))

    def _target_of(self, target: Any) -> Tuple[str, Optional[str]]:
        from .user import BaseUser

        if isinstance(target, Role):
            return ("everyone", None) if target.is_default() else ("role", target.id)
        if isinstance(target, BaseUser):
            return "member", target.npub
        if isinstance(target, str):
            if target in ("everyone", "@everyone"):
                return "everyone", None
            return ("member", target) if target.startswith("npub1") else ("role", target)
        raise TypeError(f"overwrite target must be a Role or Member, not {type(target).__name__}")

    def _overwrite_target(self, t: Dict[str, Any]) -> Any:
        kind = t.get("kind")
        if kind == "everyone":
            return self.default_role
        if kind == "role":
            return self._roles.get(t.get("id", "")) or Role(self._state, self, {"role_id": t.get("id"), "name": "?"})
        return self._member(t.get("id", ""))

    # ------------------------------------------------------------------------------------
    # discord.py surface
    # ------------------------------------------------------------------------------------

    @property
    def channels(self) -> List[TextChannel]:
        return [self._channels[i] for i in self._channel_order if i in self._channels]

    @property
    def text_channels(self) -> List[TextChannel]:
        return [c for c in self.channels if type(c) is TextChannel]

    @property
    def voice_channels(self) -> List[VoiceChannel]:
        return [c for c in self.channels if isinstance(c, VoiceChannel)]

    @property
    def forums(self) -> List[ForumChannel]:
        return [c for c in self.channels if isinstance(c, ForumChannel)]

    @property
    def categories(self) -> List[CategoryChannel]:
        return list(self._categories.values())

    def by_category(self) -> List[Tuple[Optional[CategoryChannel], List[TextChannel]]]:
        out: List[Tuple[Optional[CategoryChannel], List[TextChannel]]] = [(None, [c for c in self.channels if not c.category_id])]
        for cat in self.categories:
            out.append((cat, cat.channels))
        return out

    @property
    def emojis(self) -> tuple:
        """Custom emoji the bot can use here (``discord.Guild.emojis``): every emoji in the bot's equipped packs, so
        ``discord.utils.get(guild.emojis, name="wave")`` works."""
        return tuple(self._state.client.emojis)

    def get_emoji(self, emoji_id: Any, /) -> Any:
        return self._state.client.get_emoji(emoji_id)

    async def fetch_emojis(self) -> List[Any]:
        return list(self._state.client.emojis)

    async def fetch_emoji(self, emoji_id: Any, /) -> Any:
        from .errors import NotFound

        e = self._state.client.get_emoji(emoji_id)
        if e is None:
            raise NotFound(None, f"unknown emoji {emoji_id}")
        return e

    @property
    def roles(self) -> List[Role]:
        """Lowest first, ``@everyone`` at index 0 (discord.py order)."""
        return [self.default_role] + sorted(self._roles.values(), key=lambda r: r.position)

    @property
    def default_role(self) -> Role:
        return Role._everyone(self._state, self, self._everyone_perms)

    @property
    def members(self) -> List["Member"]:
        return list((self._members or {}).values())

    @property
    def member_count(self) -> int:
        return len(self._members or {})

    @property
    def owner_id(self) -> Optional[str]:
        return self._state.native.community_owner(self.id)

    @property
    def owner(self) -> Optional["Member"]:
        oid = self.owner_id
        return self._member(oid) if oid else None

    @property
    def me(self) -> "Member":
        return self._member(self._state.self_npub)

    @property
    def admins(self) -> List["Member"]:
        return [self._member(n) for n in self._state.native.community_admins(self.id)]

    @property
    def system_channel(self) -> Optional[TextChannel]:
        cid = self._state.native.community_primary_channel(self.id)
        return self._channels.get(cid) if cid else (self.text_channels[0] if self.text_channels else None)

    primary_channel = system_channel

    @property
    def capabilities(self) -> Any:
        return self._state.native.community_capabilities(self.id)

    @property
    def relays(self) -> List[str]:
        return self._state.native.community_relays(self.id)

    @property
    def voice_relays(self) -> List[str]:
        return self._state.native.community_voice_relays(self.id)

    @property
    def voice_client(self) -> Any:
        return self._state.voice_clients.get(self.id)

    @property
    def chunked(self) -> bool:
        return self._members is not None

    def get_channel(self, channel_id: str, /) -> Optional[TextChannel]:
        return self._channels.get(channel_id) or self._categories.get(channel_id)  # type: ignore[return-value]

    get_channel_or_thread = get_channel

    def get_category(self, category_id: str, /) -> Optional[CategoryChannel]:
        return self._categories.get(category_id)

    def get_role(self, role_id: str, /) -> Optional[Role]:
        if role_id == "everyone":
            return self.default_role
        return self._roles.get(role_id)

    def get_member(self, npub: str, /) -> Optional["Member"]:
        if self._members is None:
            return self._member(npub)
        return self._members.get(npub)

    def get_member_named(self, name: str, /) -> Optional["Member"]:
        for m in self.members:
            if name in (m.name, m.display_name, m.nick, m.global_name):
                return m
        return None

    async def fetch_member(self, npub: str, /) -> "Member":
        m = self._member(npub)
        await m.fetch()
        return m

    async def fetch_members(self, *, limit: Optional[int] = None) -> AsyncIterator["Member"]:
        await self._refresh_members()
        for i, m in enumerate(self.members):
            if limit is not None and i >= limit:
                return
            yield m

    async def chunk(self, *, cache: bool = True) -> List["Member"]:
        await self._refresh_members()
        return self.members

    async def fetch_channels(self) -> List[TextChannel]:
        await self._refresh_channels()
        return self.channels

    async def fetch_channel(self, channel_id: str, /) -> TextChannel:
        await self._refresh_channels()
        ch = self.get_channel(channel_id)
        if ch is None:
            from .errors import NotFound

            raise NotFound(f"no channel {channel_id}", "channel")
        return ch

    async def fetch_roles(self) -> List[Role]:
        self._refresh_roles()
        return self.roles

    async def fetch_role(self, role_id: str, /) -> Role:
        return Role(self._state, self, self._state.native.role_info(self.id, role_id))

    # -- moderation -----------------------------------------------------------------------

    async def ban(self, user: Any, *, reason: Optional[str] = None, delete_message_days: int = 0, delete_message_seconds: int = 0) -> None:
        await self._state.native.member_ban(self.id, getattr(user, "npub", getattr(user, "id", user)))

    async def unban(self, user: Any, *, reason: Optional[str] = None) -> None:
        await self._state.native.member_unban(self.id, getattr(user, "npub", getattr(user, "id", user)))

    async def kick(self, user: Any, *, reason: Optional[str] = None) -> None:
        await self._state.native.member_kick(self.id, getattr(user, "npub", getattr(user, "id", user)))

    async def bulk_ban(self, users: Sequence[Any], *, reason: Optional[str] = None, delete_message_seconds: int = 0) -> Any:
        """Ban many at once with a single rekey (Vector's ``ban_many``)."""
        npubs = [getattr(u, "npub", getattr(u, "id", u)) for u in users]
        await self._state.native.community_ban_many(self.id, npubs)

    async def bulk_unban(self, users: Sequence[Any]) -> None:
        npubs = [getattr(u, "npub", getattr(u, "id", u)) for u in users]
        await self._state.native.community_unban_many(self.id, npubs)

    async def bans(self, *, limit: Optional[int] = None, **ignored: Any) -> AsyncIterator[BanEntry]:
        for i, npub in enumerate(self._state.native.community_banned(self.id)):
            if limit is not None and i >= limit:
                return
            yield BanEntry(self._state.store_user(npub))

    async def fetch_ban(self, user: Any) -> BanEntry:
        npub = getattr(user, "npub", user)
        if not self._state.native.member_is_banned(self.id, npub):
            from .errors import NotFound

            raise NotFound("not banned", "ban")
        return BanEntry(self._state.store_user(npub))

    async def contain_raid(self, users: Sequence[Any], *, window: Union[datetime.timedelta, datetime.datetime, int],
                           cut_also: Sequence[Any] = ()) -> RaidContainment:
        """Ban a raid wave *and* cut everyone who joined since ``window`` out of the next key."""
        if isinstance(window, datetime.timedelta):
            start = int(time.time() - window.total_seconds())
        elif isinstance(window, datetime.datetime):
            start = int(window.timestamp())
        else:
            start = int(window)
        data = await self._state.native.community_contain_raid(
            self.id, [getattr(u, "npub", u) for u in users], start, [getattr(u, "npub", u) for u in cut_also])
        return RaidContainment(data)

    def raid_report(self) -> Any:
        return self._state.native.community_raid_report(self.id)

    @property
    def timeouts(self) -> Dict[str, datetime.datetime]:
        return {n: datetime.datetime.fromtimestamp(t, tz=datetime.timezone.utc) for n, t in self._state.native.community_timeouts(self.id)}

    @property
    def nicknames(self) -> Dict[str, str]:
        return dict(self._state.native.community_nicknames(self.id))

    async def audit_logs(self, *, limit: Optional[int] = 100, user: Any = None, action: Optional[str] = None,
                         before: Any = None, after: Any = None, oldest_first: bool = False) -> AsyncIterator[AuditLogEntry]:
        log = await self._state.native.community_audit_log(self.id)
        entries = [AuditLogEntry(self, e) for e in log.get("entries", [])]
        entries.sort(key=lambda e: e.created_at or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
                     reverse=not oldest_first)
        uid = getattr(user, "npub", user) if user is not None else None
        n = 0
        for e in entries:
            if uid and e.user_id != uid:
                continue
            if action and e.action != action:
                continue
            if before is not None and e.created_at and e.created_at >= getattr(before, "created_at", before):
                continue
            if after is not None and e.created_at and e.created_at <= getattr(after, "created_at", after):
                continue
            yield e
            n += 1
            if limit is not None and n >= limit:
                return

    # -- roles ----------------------------------------------------------------------------

    async def create_role(self, *, name: str = "new role", permissions: Union[Permissions, int] = MISSING,
                          colour: Any = MISSING, color: Any = MISSING, hoist: bool = MISSING,
                          mentionable: bool = MISSING, channel: Any = None, reason: Optional[str] = None,
                          **ignored: Any) -> Role:
        col = colour if colour is not MISSING else color
        role_id = await self._state.native.community_create_role(
            self.id, name,
            color=None if col is MISSING else int(col),
            permissions=None if permissions is MISSING else int(permissions),
            channel_id=getattr(channel, "id", channel),
            shown=None if hoist is MISSING else hoist,
            mentionable=None if mentionable is MISSING else mentionable,
        )
        self._refresh_roles()
        return self._roles.get(role_id) or Role(self._state, self, {"role_id": role_id, "name": name})

    async def edit_role_positions(self, positions: Dict[Role, int], *, reason: Optional[str] = None) -> List[Role]:
        current = {r.id: r.position for r in self._roles.values()}
        for role, pos in positions.items():
            current[role.id] = pos
        order = sorted(current, key=lambda i: current[i], reverse=True)
        await self._state.native.community_reorder_roles(self.id, order)
        self._refresh_roles()
        return self.roles

    async def set_default_permissions(self, permissions: Union[Permissions, int]) -> None:
        await self._state.native.community_set_everyone_permissions(self.id, int(permissions))
        self._everyone_perms = int(permissions)

    # -- channels -------------------------------------------------------------------------

    async def _create_channel(self, name: str, view: str, *, category: Any = None, topic: Optional[str] = None,
                              private: bool = False, overwrites: Optional[Dict[Any, PermissionOverwrite]] = None,
                              position: int = MISSING) -> TextChannel:
        cid = await self._state.native.community_create_channel(
            self.id, name, private=private, category_id=getattr(category, "id", category), view=view, topic=topic)
        await self._refresh_channels()
        ch = self._channels.get(cid) or channel_from_info(self._state, self, {"channel_id": cid, "name": name, "view": view})
        for target, ow in (overwrites or {}).items():
            await ch.set_permissions(target, overwrite=ow)
        if position is not MISSING:
            await self._state.native.channel_move(cid, getattr(category, "id", category), position)
        return ch

    async def create_text_channel(self, name: str, *, category: Any = None, topic: Optional[str] = None,
                                  private: bool = False, overwrites: Optional[Dict[Any, PermissionOverwrite]] = None,
                                  position: int = MISSING, reason: Optional[str] = None, **ignored: Any) -> TextChannel:
        return await self._create_channel(name, "chat", category=category, topic=topic, private=private,
                                          overwrites=overwrites, position=position)

    async def create_voice_channel(self, name: str, *, category: Any = None, private: bool = False,
                                   overwrites: Optional[Dict[Any, PermissionOverwrite]] = None,
                                   position: int = MISSING, reason: Optional[str] = None, **ignored: Any) -> VoiceChannel:
        return await self._create_channel(name, "voice", category=category, private=private,
                                          overwrites=overwrites, position=position)  # type: ignore[return-value]

    create_stage_channel = create_voice_channel

    async def create_forum(self, name: str, *, category: Any = None, topic: Optional[str] = None, private: bool = False,
                           overwrites: Optional[Dict[Any, PermissionOverwrite]] = None, position: int = MISSING,
                           reason: Optional[str] = None, **ignored: Any) -> ForumChannel:
        return await self._create_channel(name, "forum", category=category, topic=topic, private=private,
                                          overwrites=overwrites, position=position)  # type: ignore[return-value]

    create_forum_channel = create_forum

    async def create_category(self, name: str, *, overwrites: Optional[Dict[Any, PermissionOverwrite]] = None,
                              position: int = MISSING, reason: Optional[str] = None, **ignored: Any) -> CategoryChannel:
        cat_id = await self._state.native.community_create_category(self.id, name)
        await self._refresh_channels()
        cat = self._categories.get(cat_id) or CategoryChannel(self._state, self, {"category_id": cat_id, "name": name})
        for target, ow in (overwrites or {}).items():
            await cat.set_permissions(target, overwrite=ow)
        if position is not MISSING:
            await cat.edit(position=position)
        return cat

    create_category_channel = create_category

    # -- invites --------------------------------------------------------------------------

    async def invite(self, user: Any) -> None:
        """Invite a specific user (by npub) directly."""
        await self._state.native.community_invite(self.id, getattr(user, "npub", user))

    async def webhooks(self) -> List[Any]:
        """Every webhook in this community (``discord.Guild.webhooks``)."""
        from .webhook import Webhook

        client = self._state.client
        return [Webhook._from_row(r, None, client) for r in client.webhook_store.list(community_id=self.id)]

    async def create_invite(self, *, max_age: int = 0, label: Optional[str] = None, **ignored: Any) -> Invite:
        """A shareable join link. ``max_age`` in seconds (0 = never expires)."""
        expires = _now_ms() + max_age * 1000 if max_age else None
        url = await self._state.native.community_create_invite(self.id, expires_at_ms=expires, label=label)
        return Invite(self, url, {"label": label, "expires_at_ms": expires, "created_at_ms": _now_ms()})

    async def invites(self) -> List[Invite]:
        out = []
        for d in self._state.native.community_invite_links(self.id):
            out.append(Invite(self, d.get("url") or d.get("link") or d.get("token", ""), d))
        return out

    async def revoke_all_invites(self) -> None:
        await self._state.native.community_revoke_all_invites(self.id)

    # -- the Community itself -------------------------------------------------------------

    async def edit(self, *, name: str = MISSING, description: Optional[str] = MISSING, icon: Optional[bytes] = MISSING,
                   banner: Optional[bytes] = MISSING, reason: Optional[str] = None, **ignored: Any) -> "Community":
        native = self._state.native
        if name is not MISSING or description is not MISSING:
            await native.community_edit(self.id, None if name is MISSING else name,
                                        None if description is MISSING else (description or ""))
            if name is not MISSING:
                self.name = name
            if description is not MISSING:
                self.description = description
        if icon is not MISSING:
            await native.community_set_icon(self.id, icon)
        if banner is not MISSING:
            await native.community_set_banner(self.id, banner)
        return self

    async def icon(self) -> Optional[bytes]:
        """The decrypted icon image bytes, if one is set."""
        return await self._state.native.community_icon(self.id)

    async def banner(self) -> Optional[bytes]:
        return await self._state.native.community_banner(self.id)

    async def leave(self) -> None:
        await self._state.native.community_leave(self.id)
        self._state.remove_community(self.id)

    async def delete(self) -> None:
        """Dissolve the Community (owner only)."""
        await self._state.native.community_dissolve(self.id)
        self._state.remove_community(self.id)

    dissolve = delete

    async def is_dissolved(self) -> bool:
        return await self._state.native.community_is_dissolved(self.id)

    # -- relays & recovery ----------------------------------------------------------------

    async def check_relays(self, relays: Sequence[str]) -> List[RelayCheck]:
        return [RelayCheck(d) for d in await self._state.native.community_check_relays(self.id, list(relays))]

    async def move_relays(self, relays: Sequence[str]) -> RelayMove:
        return RelayMove(await self._state.native.community_move_relays(self.id, list(relays)))

    async def set_voice_relays(self, relays: Sequence[str]) -> None:
        await self._state.native.community_set_voice_relays(self.id, list(relays))

    async def refound(self, retain: Sequence[Any]) -> None:
        await self._state.native.community_refound(self.id, [getattr(u, "npub", u) for u in retain])

    async def rescue_stranded(self, users: Sequence[Any]) -> Any:
        return await self._state.native.community_rescue_stranded(self.id, [getattr(u, "npub", u) for u in users])

    async def repair_roster(self) -> Any:
        return await self._state.native.community_repair_roster(self.id)

    async def explain_epoch(self) -> Any:
        return await self._state.native.community_explain_epoch(self.id)

    # -- dunder ---------------------------------------------------------------------------

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Community) and other.id == self.id

    def __hash__(self) -> int:
        return hash(self.id)

    def __str__(self) -> str:
        return self.name or self.id[:12]

    def __repr__(self) -> str:
        return f"<Community id={self.id[:12]!r} name={self.name!r} channels={len(self._channels)}>"


Guild = Community
