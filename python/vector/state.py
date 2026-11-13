"""Connection state: caches, model factories, and raw-event → discord.py-event translation."""

from __future__ import annotations

import asyncio
import copy
import datetime
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .channel import CategoryChannel, DMChannel, PartialMessageable, TextChannel, channel_from_info
from .community import Community, PendingInvite
from .message import (
    Message, RawMemberRemoveEvent, RawMessageDeletePayload, RawMessageUpdateEvent, RawReactionActionEvent,
    RawTypingEvent, Reaction,
)
from .role import Role
from .user import Profile, User
from .utils import from_ms

if TYPE_CHECKING:
    from .client import Client

_log = logging.getLogger("vector.state")

__all__ = ("ConnectionState", "CommunityChange", "XdcPresence")


class _MessageCache:
    def __init__(self, maxlen: Optional[int]):
        self.maxlen = maxlen
        self._d: "OrderedDict[str, Message]" = OrderedDict()

    def add(self, m: Message) -> None:
        if self.maxlen == 0:
            return
        self._d[m.id] = m
        self._d.move_to_end(m.id)
        while self.maxlen is not None and len(self._d) > self.maxlen:
            self._d.popitem(last=False)

    def get(self, mid: str) -> Optional[Message]:
        return self._d.get(mid)

    def pop(self, mid: str) -> Optional[Message]:
        return self._d.pop(mid, None)

    def values(self) -> List[Message]:
        return list(self._d.values())


class CommunityChange:
    """One audited Community change (``on_community_change``). ``kind`` is e.g. ``"role_created"``."""

    def __init__(self, community: Community, data: Dict[str, Any]):
        self.community = community
        self.kind: str = data.get("change", "")
        self.data = data

    @property
    def guild(self) -> Community:
        return self.community

    def __getattr__(self, name: str) -> Any:
        try:
            return self.__dict__["data"][name]
        except KeyError:
            raise AttributeError(name) from None

    def __repr__(self) -> str:
        return f"<CommunityChange kind={self.kind!r}>"


class XdcPresence:
    def __init__(self, state: "ConnectionState", data: Dict[str, Any]):
        self.chat_id: str = data.get("chat_id", "")
        self.topic: str = data.get("topic", "")
        self.npub: str = data.get("npub", "")
        self.online: bool = bool(data.get("online"))
        self.at = from_ms(data.get("at"))
        self._state = state

    @property
    def user(self) -> User:
        return self._state.store_user(self.npub)

    @property
    def channel(self) -> Any:
        return self._state.channel_for(self.chat_id)

    def __repr__(self) -> str:
        return f"<XdcPresence npub={self.npub[:16]!r} online={self.online}>"


class ConnectionState:
    def __init__(self, client: "Client", *, max_messages: Optional[int] = 1000):
        self.client = client
        self.native: Any = None
        self.self_npub: str = ""
        self._users: Dict[str, User] = {}
        self._communities: Dict[str, Community] = {}
        self._dm_channels: Dict[str, DMChannel] = {}
        self._message_cache = _MessageCache(max_messages)
        self._last_message: Dict[str, Message] = {}
        self.voice_clients: Dict[str, Any] = {}
        self._views: Dict[str, Any] = {}
        self._voice_snapshot: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._profile_tasks: Dict[str, asyncio.Task] = {}
        self._ready_once = False

    # ------------------------------------------------------------------------------------
    # caches & factories
    # ------------------------------------------------------------------------------------

    @property
    def communities(self) -> List[Community]:
        return list(self._communities.values())

    def store_user(self, npub: str, profile: Optional[Dict[str, Any]] = None) -> User:
        user = self._users.get(npub)
        if user is None:
            user = self._users[npub] = User(self, npub, Profile(profile) if profile else None)
        elif profile:
            user._update_profile(Profile(profile))
        return user

    def get_user(self, npub: str) -> Optional[User]:
        return self._users.get(npub)

    async def ensure_profile(self, npub: str) -> User:
        """Load a user's cached profile (fast, local); refresh from relays in the background."""
        user = self.store_user(npub)
        if user._profile.raw:
            return user
        try:
            data = await self.native.cached_profile(npub)
        except Exception:
            data = None
        if data:
            user._update_profile(Profile(data))
        elif npub not in self._profile_tasks:
            async def fetch() -> None:
                try:
                    d = await self.native.fetch_profile(npub)
                    if d:
                        user._update_profile(Profile(d))
                except Exception:
                    pass

            self._profile_tasks[npub] = asyncio.ensure_future(fetch())
        return user

    def dm_channel(self, npub: str) -> DMChannel:
        ch = self._dm_channels.get(npub)
        if ch is None:
            ch = self._dm_channels[npub] = DMChannel(self, npub)
        return ch

    def get_community(self, community_id: str) -> Optional[Community]:
        return self._communities.get(community_id)

    def _community_shell(self, community_id: str) -> Community:
        c = self._communities.get(community_id)
        if c is None:
            c = self._communities[community_id] = Community(self, community_id)
        return c

    async def add_community(self, community_id: str, *, joined: bool = False) -> Community:
        new = community_id not in self._communities
        c = self._community_shell(community_id)
        await c._refresh()
        if joined and new:
            self.client.dispatch("guild_join", c)
        return c

    def remove_community(self, community_id: str) -> Optional[Community]:
        return self._communities.pop(community_id, None)

    def get_channel(self, channel_id: str) -> Any:
        if channel_id.startswith("npub1"):
            return self.dm_channel(channel_id)
        for c in self._communities.values():
            ch = c.get_channel(channel_id)
            if ch is not None:
                return ch
        return None

    def channel_for(self, channel_id: str, *, kind: Optional[str] = None, community_id: Optional[str] = None) -> Any:
        if kind == "dm" or channel_id.startswith("npub1"):
            return self.dm_channel(channel_id)
        if community_id is None:
            ch = self.get_channel(channel_id)
            if ch is not None:
                return ch
            try:
                community_id = self.native.channel_community(channel_id, kind)
            except Exception:
                community_id = None
        if community_id:
            c = self._community_shell(community_id)
            ch = c.get_channel(channel_id)
            if ch is None:
                ch = channel_from_info(self, c, {"channel_id": channel_id, "name": ""})
                c._channels[channel_id] = ch
                c._channel_order.append(channel_id)
            return ch
        return PartialMessageable(self, channel_id)

    # ------------------------------------------------------------------------------------
    # messages
    # ------------------------------------------------------------------------------------

    def _cache_message(self, m: Message) -> Message:
        self._message_cache.add(m)
        self._last_message[getattr(m.channel, "id", "")] = m
        return m

    def message_from_incoming(self, data: Dict[str, Any]) -> Message:
        """From the ``{chat_id, is_group, author, community_id, message}`` shape."""
        chat_id = data.get("chat_id", "")
        community_id = data.get("community_id")
        channel = self.channel_for(chat_id, kind="community" if data.get("is_group") else "dm", community_id=community_id)
        community = getattr(channel, "community", None)
        return Message(state=self, channel=channel, data=data.get("message") or {}, author_npub=data.get("author"),
                       community=community)

    def message_from_raw(self, raw: Dict[str, Any], channel: Any) -> Message:
        author = raw.get("npub")
        if not author and isinstance(channel, DMChannel) and not raw.get("mine"):
            author = channel.id
        cached = self._message_cache.get(raw.get("id", ""))
        m = Message(state=self, channel=channel, data=raw, author_npub=author, community=getattr(channel, "community", None))
        if cached is not None:
            self._message_cache.add(m)
        return m

    async def fetch_message(self, message_id: str) -> Optional[Message]:
        data = await self.native.message(message_id)
        if not data:
            return self._message_cache.get(message_id)
        return self._cache_message(self.message_from_incoming(data))

    async def sent_message(self, message_id: str, channel_id: str, kind: Optional[str], text: str,
                           reply_to: Optional[str]) -> Message:
        try:
            data = await self.native.message(message_id)
        except Exception:
            data = None
        if data:
            return self._cache_message(self.message_from_incoming(data))
        channel = self.channel_for(channel_id, kind=kind)
        raw = {"id": message_id, "content": text, "replied_to": reply_to or "", "attachments": [], "reactions": [],
               "at": int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000), "mine": True,
               "npub": self.self_npub, "pending": False, "failed": False}
        return self._cache_message(Message(state=self, channel=channel, data=raw, author_npub=self.self_npub,
                                           community=getattr(channel, "community", None)))

    def last_message_in(self, channel_id: str) -> Optional[Message]:
        return self._last_message.get(channel_id)

    # ------------------------------------------------------------------------------------
    # event translation
    # ------------------------------------------------------------------------------------

    async def parse(self, ev: Dict[str, Any]) -> None:
        kind = ev.get("type")
        handler = getattr(self, f"parse_{kind}", None)
        self.client.dispatch("socket_event_type", kind)
        self.client.dispatch("raw_event", ev)
        if handler is None:
            _log.debug("unhandled event %s", kind)
            return
        try:
            await handler(ev)
        except Exception:
            _log.exception("failed to parse %s event", kind)

    async def parse_ready(self, ev: Dict[str, Any]) -> None:
        ids = []
        listed = ev.get("communities")
        # the native event carries a *count*; older shapes carried a list of ids/dicts
        for c in (listed if isinstance(listed, (list, tuple)) else []):
            ids.append(c if isinstance(c, str) else c.get("community_id") or c.get("id"))
        try:
            ids = list(dict.fromkeys(ids + list(await self.native.communities())))
        except Exception:
            pass
        await asyncio.gather(*(self.add_community(i) for i in ids if i), return_exceptions=True)
        if not self._ready_once:
            self._ready_once = True
            self.client._ready.set()
            self.client.dispatch("ready")
        else:
            self.client.dispatch("resumed")

    def note_incoming(self, chat_id: str, msg: Any) -> None:
        """Remember when the newest incoming message of a chat was sent (see ``order_after_incoming``)."""
        try:
            at = msg.created_at.timestamp()
        except Exception:
            return
        book = self.__dict__.setdefault("_last_incoming", {})
        chat_id = chat_id or str(getattr(getattr(msg, "channel", None), "id", ""))
        if at > book.get(chat_id, 0):
            book[chat_id] = at

    async def order_after_incoming(self, chat_id: str) -> None:
        """Vector sorts messages by whole-second timestamps. If a reply goes out within the same second as the
        message that triggered it (or the sender's clock is a bit ahead of ours) it is shown *above* it. Wait until
        our clock has passed the incoming message's second."""
        if not getattr(self.client, "reply_ordering", True):
            return
        import math
        import time

        at = self.__dict__.get("_last_incoming", {}).get(chat_id)
        if at is None:
            return
        wait = (math.floor(at) + 1) - time.time()
        if 0 < wait <= 2.5:
            await asyncio.sleep(wait + 0.05)

    async def parse_message(self, ev: Dict[str, Any]) -> None:
        data = ev["message"]
        if data.get("author"):
            try:
                await asyncio.wait_for(self.ensure_profile(data["author"]), 2)
            except Exception:
                pass
        msg = self._cache_message(self.message_from_incoming(data))
        self.note_incoming(data.get("chat_id") or ev.get("chat_id", ""), msg)
        self.client.dispatch("message", msg)

    async def parse_command(self, ev: Dict[str, Any]) -> None:
        data = ev["message"]
        if data.get("author"):
            try:
                await asyncio.wait_for(self.ensure_profile(data["author"]), 2)
            except Exception:
                pass
        msg = self._cache_message(self.message_from_incoming(data))
        await self.client._handle_slash_command(ev["name"], ev.get("args") or {}, msg)

    async def parse_reaction_add(self, ev: Dict[str, Any]) -> None:
        r = ev.get("reaction") or {}
        chat_id = ev.get("chat_id", "")
        channel = self.channel_for(chat_id)
        community = getattr(channel, "community", None)
        raw_msg = ev.get("message") or {}
        msg = self.message_from_raw(raw_msg, channel) if raw_msg else None
        if msg is not None:
            self._cache_message(msg)
        user_id = r.get("author_id", "")
        await self.ensure_profile(user_id) if user_id else None
        member = community._member(user_id) if community else None
        payload = RawReactionActionEvent(
            message_id=r.get("reference_id", raw_msg.get("id", "")), channel_id=chat_id,
            guild_id=community.id if community else None, user_id=user_id, emoji=r.get("emoji", ""),
            emoji_url=r.get("emoji_url"), event_type="REACTION_ADD", member=member, reaction_id=r.get("id"), message=msg)
        self.client.dispatch("raw_reaction_add", payload)
        if msg is not None:
            reaction = next((x for x in msg.reactions if x.emoji == payload.emoji), None) or Reaction(msg, payload.emoji, payload.emoji_url)
            user = member or self.store_user(user_id)
            self.client.dispatch("reaction_add", reaction, user)
            view = self._views.get(msg.id)
            if view is not None and user_id != self.self_npub:
                asyncio.ensure_future(view._dispatch_reaction(payload.emoji, user, msg))

    async def parse_reaction_remove(self, ev: Dict[str, Any]) -> None:
        chat_id = ev.get("chat_id", "")
        channel = self.channel_for(chat_id)
        community = getattr(channel, "community", None)
        raw_msg = ev.get("message") or {}
        old = self._message_cache.get(raw_msg.get("id", ""))
        emoji = ""
        emoji_url = None
        if old is not None:
            for rx in old.reactions:
                if ev.get("reaction_id") in rx._ids:
                    emoji, emoji_url = rx.emoji, rx.emoji_url
        msg = self._cache_message(self.message_from_raw(raw_msg, channel)) if raw_msg else None
        by = ev.get("by", "")
        member = community._member(by) if community else None
        payload = RawReactionActionEvent(
            message_id=raw_msg.get("id", ""), channel_id=chat_id, guild_id=community.id if community else None,
            user_id=by, emoji=emoji, emoji_url=emoji_url, event_type="REACTION_REMOVE", member=member,
            reaction_id=ev.get("reaction_id"), message=msg)
        self.client.dispatch("raw_reaction_remove", payload)
        if msg is not None:
            reaction = next((x for x in msg.reactions if x.emoji == emoji), None) or Reaction(msg, emoji, emoji_url)
            user = member or self.store_user(by)
            self.client.dispatch("reaction_remove", reaction, user)
            view = self._views.get(msg.id)
            if view is not None and emoji and by != self.self_npub:
                asyncio.ensure_future(view._dispatch_reaction(emoji, user, msg))

    async def parse_message_edit(self, ev: Dict[str, Any]) -> None:
        chat_id = ev.get("chat_id", "")
        channel = self.channel_for(chat_id)
        raw = ev.get("message") or {}
        before = self._message_cache.get(raw.get("id", ""))
        after = self.message_from_raw(raw, channel)
        if before is None and after.edit_history:
            prev = after.edit_history[-2].content if len(after.edit_history) > 1 else None
            if prev is not None:
                before = after._copy_with(content=prev)
        self._cache_message(after)
        community = getattr(channel, "community", None)
        self.client.dispatch("raw_message_edit", RawMessageUpdateEvent(
            message=after, channel_id=chat_id, guild_id=community.id if community else None, cached_message=before))
        if before is not None:
            self.client.dispatch("message_edit", before, after)

    async def parse_message_delete(self, ev: Dict[str, Any]) -> None:
        mid = ev.get("message_id", "")
        cached = self._message_cache.pop(mid)
        channel = self.channel_for(ev.get("chat_id", ""))
        community = getattr(channel, "community", None)
        self.client.dispatch("raw_message_delete", RawMessageDeletePayload(
            message_id=mid, channel_id=ev.get("chat_id", ""), guild_id=community.id if community else None,
            by=ev.get("by"), moderated=bool(ev.get("moderated")), at=ev.get("at"), cached_message=cached))
        if cached is not None:
            self.client.dispatch("message_delete", cached)
        self._views.pop(mid, None)

    async def _community_for_event(self, community_id: str) -> Community:
        """The cached Community, loading it (and firing ``on_guild_join``) the first time it shows up,
        e.g. when an invite is auto-accepted by ``invite_policy="public"``."""
        c = self._communities.get(community_id)
        if c is None:
            c = await self.add_community(community_id, joined=True)
        return c

    async def parse_member_join(self, ev: Dict[str, Any]) -> None:
        c = await self._community_for_event(ev["community_id"])
        npub = ev.get("npub", "")
        await self.ensure_profile(npub)
        member = c._member(npub)
        if c._members is not None:
            c._members[npub] = member
        member._overrides["invited_by"] = ev.get("invited_by")
        member._overrides["invite_label"] = ev.get("invite_label")
        self.client.dispatch("member_join", member)

    async def parse_member_remove(self, ev: Dict[str, Any]) -> None:
        c = self._community_shell(ev["community_id"])
        npub = ev.get("npub", "")
        member = c._member(npub)
        if c._members is not None:
            c._members.pop(npub, None)
        self.client.dispatch("raw_member_remove", RawMemberRemoveEvent(user=member, guild_id=c.id, channel_id=ev.get("channel_id")))
        self.client.dispatch("member_remove", member)

    async def parse_typing(self, ev: Dict[str, Any]) -> None:
        chat_id = ev.get("chat_id", "")
        channel = self.channel_for(chat_id)
        community = getattr(channel, "community", None)
        npub = ev.get("npub", "")
        user = community._member(npub) if community else self.store_user(npub)
        payload = RawTypingEvent(channel_id=chat_id, user_id=npub, until=ev.get("until"), guild_id=community.id if community else None)
        self.client.dispatch("raw_typing", payload)
        self.client.dispatch("typing", channel, user, payload.timestamp)

    async def parse_community_change(self, ev: Dict[str, Any]) -> None:
        c = await self._community_for_event(ev["community_id"])
        change = ev.get("change") or {}
        kind = change.get("change", "")
        before = copy.copy(c)
        before._channels = dict(c._channels)
        before._roles = dict(c._roles)
        before._categories = dict(c._categories)

        if kind in ("renamed", "description_changed"):
            if kind == "renamed":
                c.name = change.get("new", c.name)
            else:
                c.description = change.get("new")
            self.client.dispatch("guild_update", before, c)
        elif kind in ("icon_changed", "banner_changed", "relays_changed", "voice_relays_changed"):
            self.client.dispatch("guild_update", before, c)
        elif kind == "everyone_changed":
            old_role = c.default_role
            c._everyone_perms = int(change.get("new") or 0)
            self.client.dispatch("guild_role_update", old_role, c.default_role)
        elif kind == "role_created":
            role = Role(self, c, change["role"])
            c._roles[role.id] = role
            self.client.dispatch("guild_role_create", role)
        elif kind == "role_updated":
            old, new = Role(self, c, change["old"]), Role(self, c, change["new"])
            c._roles[new.id] = new
            self.client.dispatch("guild_role_update", old, new)
        elif kind == "role_deleted":
            role = Role(self, c, change["role"])
            c._roles.pop(role.id, None)
            self.client.dispatch("guild_role_delete", role)
        elif kind == "roles_reordered":
            c._refresh_roles()
            self.client.dispatch("guild_roles_reorder", c, change.get("order", []))
        elif kind == "member_roles_changed":
            npub = change.get("member", "")
            after = c._member(npub)
            current = {r.id for r in after.roles if not r.is_default()}
            prev = (current - set(change.get("added", []))) | set(change.get("removed", []))
            self.client.dispatch("member_update", after._snapshot(role_ids=prev), after)
            self.client.dispatch("member_roles_update", after,
                                 [c.get_role(i) or i for i in change.get("added", [])],
                                 [before._roles.get(i) or i for i in change.get("removed", [])])
        elif kind == "member_banned":
            user = self.store_user(change.get("member", ""))
            if c._members is not None:
                c._members.pop(user.npub, None)
            self.client.dispatch("member_ban", c, user)
        elif kind == "member_unbanned":
            self.client.dispatch("member_unban", c, self.store_user(change.get("member", "")))
        elif kind == "member_kicked":
            member = c._member(change.get("member", ""))
            if c._members is not None:
                c._members.pop(member.npub, None)
            self.client.dispatch("member_kick", c, member)
        elif kind in ("channel_created", "channel_updated", "channel_deleted",
                      "category_created", "category_updated", "category_deleted", "layout_changed"):
            old_info = change.get("old")
            await c._refresh_channels()
            if kind == "channel_created":
                ch = c.get_channel(change["channel"]["channel_id"]) or channel_from_info(self, c, change["channel"])
                self.client.dispatch("guild_channel_create", ch)
            elif kind == "channel_updated":
                old = channel_from_info(self, c, old_info)
                new = c.get_channel(change["new"]["channel_id"]) or channel_from_info(self, c, change["new"])
                self.client.dispatch("guild_channel_update", old, new)
            elif kind == "channel_deleted":
                self.client.dispatch("guild_channel_delete", channel_from_info(self, c, change["channel"]))
            elif kind == "category_created":
                self.client.dispatch("guild_channel_create", CategoryChannel(self, c, change["category"]))
            elif kind == "category_updated":
                self.client.dispatch("guild_channel_update", CategoryChannel(self, c, old_info),
                                     CategoryChannel(self, c, change["new"]))
            elif kind == "category_deleted":
                self.client.dispatch("guild_channel_delete", CategoryChannel(self, c, change["category"]))
            else:
                self.client.dispatch("guild_layout_update", c)
        elif kind == "overwrite_changed":
            scope = c.get_channel(change.get("scope_id", "")) or c.get_category(change.get("scope_id", ""))
            from .permissions import PermissionOverwrite

            target = c._overwrite_target(change.get("target") or {})
            self.client.dispatch("overwrite_update", scope, target,
                                 PermissionOverwrite.from_pair(int(change.get("allow") or 0), int(change.get("deny") or 0)))
        elif kind == "channel_synced":
            ch = c.get_channel(change.get("channel_id", ""))
            cat = c.get_category(change.get("category_id") or "")
            self.client.dispatch("channel_permissions_sync", ch, cat)
        elif kind == "pins_changed":
            ch = c.get_channel(change.get("channel_id", ""))
            self.client.dispatch("guild_channel_pins_update", ch, datetime.datetime.now(datetime.timezone.utc))
        elif kind == "timed_out":
            member = c._member(change.get("member", ""))
            until = datetime.datetime.fromtimestamp(int(change.get("until") or 0), tz=datetime.timezone.utc)
            self.client.dispatch("member_update", member._snapshot(timed_out_until=None), member)
            self.client.dispatch("member_timeout", member, until)
        elif kind == "timeout_ended":
            member = c._member(change.get("member", ""))
            self.client.dispatch("member_timeout_end", member)
        elif kind == "nickname_changed":
            member = c._member(change.get("member", ""))
            self.client.dispatch("member_update", member._snapshot(nick=None), member)
            self.client.dispatch("member_nickname_update", member, change.get("nickname"))
        self.client.dispatch("community_change", CommunityChange(c, change))

    async def parse_community_dissolve(self, ev: Dict[str, Any]) -> None:
        c = self.remove_community(ev["community_id"]) or Community(self, ev["community_id"])
        c.dissolved = True
        self.client.dispatch("community_dissolve", c)
        self.client.dispatch("guild_remove", c)

    async def parse_community_remove(self, ev: Dict[str, Any]) -> None:
        c = self.remove_community(ev["community_id"]) or Community(self, ev["community_id"])
        self.client.dispatch("guild_remove", c)

    async def parse_community_invite(self, ev: Dict[str, Any]) -> None:
        cid = ev["community_id"]
        data = {"community_id": cid}
        try:
            for p in self.native.pending_invites():
                if p.get("community_id") == cid:
                    data = p
        except Exception:
            pass
        invite = PendingInvite(self, data)
        self.client.dispatch("community_invite", invite)

    async def parse_channel_keyed(self, ev: Dict[str, Any]) -> None:
        c = self._community_shell(ev["community_id"])
        await c._refresh_channels()
        ch = self.channel_for(ev["channel_id"], community_id=c.id)
        self.client.dispatch("channel_keyed", ch, bool(ev.get("backfilled")))

    async def parse_voice_presence(self, ev: Dict[str, Any]) -> None:
        from .voice import VoiceState

        channel_id = ev.get("channel_id", "")
        channel = self.channel_for(channel_id, kind="community")
        self.client.dispatch("voice_channel_update", channel)
        try:
            now = {s["npub"]: s for s in self.native.channel_voice_members(channel_id)}
        except Exception:
            return
        then = self._voice_snapshot.get(channel_id, {})
        self._voice_snapshot[channel_id] = now
        community = getattr(channel, "community", None)
        for npub in set(now) | set(then):
            if now.get(npub) == then.get(npub):
                continue
            member = community._member(npub) if community else self.store_user(npub)
            before = VoiceState(channel if npub in then else None, then.get(npub) or {})
            after = VoiceState(channel if npub in now else None, now.get(npub) or {})
            self.client.dispatch("voice_state_update", member, before, after)

    async def parse_xdc_presence(self, ev: Dict[str, Any]) -> None:
        self.client.dispatch("xdc_presence", XdcPresence(self, ev))

    async def parse_xdc_session(self, ev: Dict[str, Any]) -> None:
        await self.client._handle_xdc_session(ev)

    async def parse_disconnect(self, ev: Dict[str, Any]) -> None:
        self.client.dispatch("disconnect")

    async def parse_unknown(self, ev: Dict[str, Any]) -> None:
        self.client.dispatch("unknown_event", ev)
