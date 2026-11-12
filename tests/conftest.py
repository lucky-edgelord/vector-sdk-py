"""A fake of the Rust ``NativeBot`` so the Python layer can be tested without relays."""

from __future__ import annotations

import asyncio
import itertools
import os
import time
from typing import Any, Dict, List, Optional

import pytest

import vector

BOT = "npub1" + "b" * 58
ALICE = "npub1" + "a" * 58
MOD = "npub1" + "m" * 58
COMMUNITY = "c" * 64
GENERAL = "1" * 64
VOICE = "2" * 64

_ids = itertools.count(1)


def hexid() -> str:
    return f"{next(_ids):064x}"


def raw_message(content: str, author: str = ALICE, *, mid: Optional[str] = None, mine: bool = False,
                attachments: Optional[list] = None, reactions: Optional[list] = None) -> Dict[str, Any]:
    return {"id": mid or hexid(), "content": content, "replied_to": "", "attachments": attachments or [],
            "reactions": reactions or [], "at": int(time.time() * 1000), "pending": False, "failed": False,
            "mine": mine, "npub": author, "edited": False}


def incoming(content: str, author: str = ALICE, *, chat_id: str = GENERAL, group: bool = True, **kw: Any) -> Dict[str, Any]:
    return {"chat_id": chat_id, "is_group": group, "is_file": False, "author": author,
            "community_id": COMMUNITY if group else None, "message": raw_message(content, author, **kw)}


class FakeNative:
    def __init__(self) -> None:
        self.npub = BOT
        self.queue: asyncio.Queue = asyncio.Queue()
        self.sent: List[Dict[str, Any]] = []
        self.reactions: List[tuple] = []
        self.edits: List[tuple] = []
        self.commands: Dict[str, tuple] = {}
        self.calls: List[tuple] = []
        self.messages: Dict[str, Dict[str, Any]] = {}
        self.perms: Dict[str, int] = {MOD: (1 << 3) | (1 << 4) | (1 << 5), ALICE: 1 << 14}
        self.roles = [{"role_id": "r1", "name": "Mods", "position": 1, "permissions": 0b111000, "scope": {"kind": "server"}, "color": 0xFF0000}]
        self.member_roles_map = {MOD: ["r1"]}
        self.stopped = asyncio.Event()

    # lifecycle
    def subscription_ready(self) -> bool:
        return True

    async def start(self) -> None:
        await self.stopped.wait()

    async def next_event(self):
        return await self.queue.get()

    async def logout(self) -> None:
        self.stopped.set()
        await self.queue.put({"type": "disconnect", "error": None})

    def register_command(self, name, description, args):
        self.commands[name] = (description, args)

    def register_xdc(self, app, **opts):
        self.xdc_handlers = getattr(self, "xdc_handlers", {})
        hid = len(self.xdc_handlers) + 1
        self.xdc_handlers[hid] = app
        return hid

    async def channel_send_xdc(self, cid, kind, path):
        mid = hexid()
        self.sent.append({"channel": cid, "xdc": path, "id": mid})
        self.messages[mid] = {"chat_id": cid, "is_group": True, "author": BOT,
                              "community_id": COMMUNITY if cid in (GENERAL, VOICE) else None,
                              "message": raw_message("", BOT, mid=mid, mine=True)}
        return {"message_id": mid, "chat_id": cid, "file_name": "panel.xdc", "file_hash": "h", "topic": "t"}

    async def message_xdc(self, mid):
        return {"message_id": mid, "chat_id": GENERAL, "file_name": "panel.xdc", "file_hash": "h", "topic": "t"}

    # profiles
    async def cached_profile(self, npub):
        return {"id": npub, "name": {ALICE: "alice", MOD: "mod", BOT: "testbot"}.get(npub, ""), "bot": npub == BOT}

    async def fetch_profile(self, npub):
        return await self.cached_profile(npub)

    async def set_status(self, text):
        self.calls.append(("set_status", text))

    # communities
    async def communities(self):
        return [COMMUNITY]

    async def community_name(self, cid):
        return "Test Community"

    def community_description(self, cid):
        return "a place"

    def community_channel_infos(self, cid):
        return [{"channel_id": GENERAL, "name": "general", "private": False, "category_id": None, "topic": None, "view": "chat"},
                {"channel_id": VOICE, "name": "Lounge", "private": False, "category_id": "k1", "topic": None, "view": "voice"}]

    async def community_channels(self, cid):
        return [{"channel_id": GENERAL, "name": "general", "private": False, "readable": True, "epoch": 0},
                {"channel_id": VOICE, "name": "Lounge", "private": False, "readable": True, "epoch": 0}]

    def community_categories(self, cid):
        return [{"category_id": "k1", "name": "Voice"}]

    def community_roles(self, cid):
        return self.roles

    def community_everyone_permissions(self, cid):
        return (1 << 13) | (1 << 14)

    async def community_members(self, cid):
        return [ALICE, MOD, BOT]

    def community_owner(self, cid):
        return MOD

    def community_primary_channel(self, cid):
        return GENERAL

    def channel_community(self, cid, kind=None):
        return COMMUNITY if cid in (GENERAL, VOICE) else None

    def channel_kind(self, cid):
        return "dm" if cid.startswith("npub1") else "community"

    # members
    def member_nickname(self, cid, npub):
        return None

    def member_roles(self, cid, npub):
        return [r for r in self.roles if r["role_id"] in self.member_roles_map.get(npub, [])]

    def member_permissions(self, cid, npub):
        return self.perms.get(npub, 0)

    def member_is_owner(self, cid, npub):
        return npub == MOD and False

    def member_is_admin(self, cid, npub):
        return False

    def member_can(self, cid, npub, bits):
        return (self.perms.get(npub, 0) & bits) == bits

    def channel_permissions_of(self, cid, npub):
        return self.perms.get(npub, 0)

    def channel_overwrites(self, cid):
        return []

    async def member_kick(self, cid, npub):
        self.calls.append(("kick", npub))

    async def member_ban(self, cid, npub):
        self.calls.append(("ban", npub))

    # messaging
    async def channel_send(self, cid, kind, text, reply_to=None, expires_in=None, to_bot=None):
        mid = hexid()
        self.sent.append({"channel": cid, "kind": kind, "text": text, "reply_to": reply_to, "expires_in": expires_in, "id": mid})
        self.messages[mid] = {"chat_id": cid, "is_group": kind != "dm" and not cid.startswith("npub1"), "author": BOT,
                              "community_id": COMMUNITY if cid in (GENERAL, VOICE) else None,
                              "message": raw_message(text, BOT, mid=mid, mine=True)}
        return mid

    async def channel_send_bytes(self, cid, kind, data, filename, caption=None, reply_to=None, expires_in=None, compress=True):
        mid = hexid()
        self.sent.append({"channel": cid, "file": filename, "bytes": len(data), "text": caption, "id": mid})
        return mid

    async def message(self, mid):
        return self.messages.get(mid)

    async def channel_react(self, cid, kind, mid, emoji, url=None):
        self.reactions.append((mid, emoji))

    async def channel_unreact(self, cid, kind, mid, emoji):
        self.reactions.remove((mid, emoji))

    async def channel_edit(self, cid, kind, mid, text):
        self.edits.append((mid, text))
        if mid in self.messages:
            self.messages[mid]["message"]["content"] = text

    async def channel_delete_message(self, cid, kind, mid):
        self.calls.append(("delete", mid))

    async def channel_hide(self, cid, kind, mid):
        self.calls.append(("hide", mid))

    async def channel_typing(self, cid, kind):
        self.calls.append(("typing", cid))

    async def channel_history(self, cid, kind, limit, before=None):
        return []

    def channel_voice_members(self, cid):
        return []


class Harness:
    """Drives a Client/Bot with a FakeNative: inject events, then wait for the queue to drain."""

    def __init__(self, client: vector.Client):
        self.client = client
        self.native = FakeNative()
        self.task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        from vector.user import ClientUser, Profile

        c = self.client
        state = c._connection
        state.native = self.native
        state.self_npub = self.native.npub
        c._ready = asyncio.Event()
        c._user = ClientUser(state, self.native.npub, Profile({"name": "testbot", "bot": True}))
        await c._on_native_ready()
        await c.setup_hook()
        self.task = asyncio.ensure_future(c.connect())
        await self.emit({"type": "ready", "communities": 1})
        await asyncio.wait_for(c.wait_until_ready(), 5)

    async def emit(self, ev: Dict[str, Any], settle: float = 0.05) -> None:
        await self.native.queue.put(ev)
        await asyncio.sleep(settle)

    async def say(self, content: str, author: str = ALICE, **kw: Any) -> None:
        await self.emit({"type": "message", "message": incoming(content, author, **kw)})

    async def slash(self, name: str, args: Dict[str, Any], author: str = ALICE) -> None:
        await self.emit({"type": "command", "name": name, "args": args, "message": incoming(f"/{name}", author)})

    async def stop(self) -> None:
        await self.client.close()
        if self.task:
            await asyncio.wait_for(self.task, 5)

    @property
    def texts(self) -> List[str]:
        return [s.get("text") or "" for s in self.native.sent]


@pytest.fixture
def harness_factory():
    made: List[Harness] = []

    async def make(client: vector.Client) -> Harness:
        h = Harness(client)
        await h.start()
        made.append(h)
        return h

    yield make
