"""Mini Apps (WebXDC): live sessions with everyone who has an app open.

    @bot.xdc_app("vector-counter")
    async def counter(session: vector.XdcSession):
        async for event in session:
            if event.type == "data":
                await session.send_json({"t": "echo", "got": event.json()})

Sessions end when everyone closes the app, the idle/quiet timeout passes, or the handler returns.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional

if TYPE_CHECKING:
    from .message import Message
    from .state import ConnectionState
    from .user import User

__all__ = ("XdcApp", "XdcSession", "XdcEvent", "XdcPeer", "XdcManifest", "allow_outside_transport")


def allow_outside_transport(on: bool = True) -> None:
    """Let Mini App sessions join even when the bot runs over Tor/I2P (peers then see the bot's IP)."""
    from . import _native

    _native.allow_outside_transport(on)


class XdcManifest:
    def __init__(self, data: Dict[str, Any]):
        self.name: Optional[str] = data.get("name")
        self.id: Optional[str] = data.get("id")
        self.description: Optional[str] = data.get("description")
        self.icon: Optional[str] = data.get("icon")
        self.version: Optional[str] = data.get("version")
        self.source_code_url: Optional[str] = data.get("source_code_url")

    def __repr__(self) -> str:
        return f"<XdcManifest id={self.id!r} name={self.name!r} version={self.version!r}>"


class XdcPeer:
    __slots__ = ("_state", "node", "npub")

    def __init__(self, state: "ConnectionState", data: Dict[str, Any]):
        self._state = state
        self.node: str = data.get("node", "")
        self.npub: Optional[str] = data.get("npub")

    @property
    def user(self) -> Optional["User"]:
        return self._state.store_user(self.npub) if self.npub else None

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, XdcPeer) and other.node == self.node

    def __hash__(self) -> int:
        return hash(self.node)

    def __repr__(self) -> str:
        return f"<XdcPeer npub={self.npub!r} node={self.node[:12]!r}>"


class XdcEvent:
    """``type`` is ``"data"``, ``"peer_join"``, ``"peer_leave"`` or ``"lagged"``."""

    def __init__(self, state: "ConnectionState", data: Dict[str, Any]):
        self.type: str = data.get("type", "")
        self.payload: bytes = data.get("payload") or b""
        self.direct: bool = bool(data.get("direct"))
        self.verified_sender: Optional[str] = data.get("verified_sender")
        p = data.get("from") or data.get("peer")
        self.peer: Optional[XdcPeer] = XdcPeer(state, p) if p else None

    @property
    def author(self) -> Optional["User"]:
        """The sender, *only* if their npub is verified (see the SDK docs on trust)."""
        if self.verified_sender is None or self.peer is None:
            return None
        return self.peer.user

    def text(self) -> str:
        return self.payload.decode("utf-8", "replace")

    def json(self) -> Any:
        return json.loads(self.payload)

    def __repr__(self) -> str:
        return f"<XdcEvent type={self.type!r} bytes={len(self.payload)}>"


class XdcSession:
    """A live Mini App session. Iterate it for events; ``send*`` broadcast to everyone in it."""

    def __init__(self, state: "ConnectionState", native_session: Any, app: Dict[str, Any]):
        self._state = state
        self._s = native_session
        self.app = XdcApp(state, app.get("message_id", ""), app)
        self._left = False

    @property
    def chat_id(self) -> str:
        return self.app.chat_id

    @property
    def channel(self) -> Any:
        return self._state.channel_for(self.chat_id)

    @property
    def self_addr(self) -> str:
        return self._s.self_addr

    def __aiter__(self) -> AsyncIterator[XdcEvent]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[XdcEvent]:
        while True:
            ev = await self.next()
            if ev is None:
                return
            yield ev

    async def next(self) -> Optional[XdcEvent]:
        data = await self._s.next()
        return XdcEvent(self._state, data) if data is not None else None

    async def send(self, data: bytes) -> None:
        await self._s.send(bytes(data))

    async def send_text(self, text: str) -> None:
        await self._s.send_text(text)

    async def send_json(self, obj: Any) -> None:
        await self._s.send_json(json.dumps(obj))

    async def peers(self) -> List[XdcPeer]:
        return [XdcPeer(self._state, p) for p in await self._s.peers()]

    async def set_idle_timeout(self, seconds: Optional[float]) -> None:
        await self._s.set_idle_timeout(seconds)

    async def set_quiet_timeout(self, seconds: Optional[float]) -> None:
        await self._s.set_quiet_timeout(seconds)

    async def leave(self) -> None:
        if not self._left:
            self._left = True
            await self._s.leave()

    async def __aenter__(self) -> "XdcSession":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.leave()

    def __repr__(self) -> str:
        return f"<XdcSession app={self.app.file_name!r} chat={self.chat_id[:16]!r}>"


class XdcApp:
    """A Mini App shared into a chat (``message.xdc``)."""

    def __init__(self, state: "ConnectionState", message_id: str, data: Optional[Dict[str, Any]] = None):
        self._state = state
        self.message_id = message_id
        data = data or {}
        self.chat_id: str = data.get("chat_id", "")
        self.file_name: str = data.get("file_name", "")
        self.file_hash: str = data.get("file_hash", "")
        self.topic: Optional[str] = data.get("topic")
        self.raw = data

    async def _load(self) -> None:
        if not self.raw:
            data = await self._state.native.message_xdc(self.message_id)
            if data:
                self.__init__(self._state, self.message_id, data)  # type: ignore[misc]

    async def manifest(self) -> XdcManifest:
        return XdcManifest(await self._state.native.xdc_manifest(self.message_id))

    async def join(self) -> XdcSession:
        """Join this app's live session yourself (outside any ``xdc_app`` handler)."""
        await self._load()
        native_session = await self._state.native.xdc_join(self.message_id)
        return XdcSession(self._state, native_session, self.raw or {"message_id": self.message_id})

    async def fetch_message(self) -> Optional["Message"]:
        return await self._state.fetch_message(self.message_id)

    def __repr__(self) -> str:
        return f"<XdcApp file={self.file_name!r} message={self.message_id[:12]!r}>"
