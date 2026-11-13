"""``Client``: the event-driven connection to Vector, shaped like ``discord.Client``."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import signal
import sys
import traceback
from typing import (
    TYPE_CHECKING, Any, Callable, Coroutine, Dict, List, Optional, Sequence, Tuple, Type, TypeVar, Union,
)

from .channel import DMChannel
from .community import Community, CommunityPreview, PendingInvite
from .errors import ClientException, LoginFailure
from .flags import Activity, Intents
from .state import ConnectionState
from .user import ClientUser, Profile, User
from .utils import MISSING

if TYPE_CHECKING:
    from .message import Message
    from .xdc import XdcSession

_log = logging.getLogger("vector.client")

__all__ = ("Client", "AutoShardedClient")

Coro = TypeVar("Coro", bound=Callable[..., Coroutine[Any, Any, Any]])


def _native_module():
    try:
        from . import _native
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "vector's Rust extension is missing. Install the package with pip (it builds the extension), "
            "e.g. `pip install git+https://github.com/lucky-edgelord/vector-sdk-py`"
        ) from e
    return _native


def setup_logging(*, level: int = logging.INFO, handler: Optional[logging.Handler] = None,
                  formatter: Optional[logging.Formatter] = None, root: bool = True) -> None:
    """discord.py-style default logging setup."""
    handler = handler or logging.StreamHandler()
    formatter = formatter or logging.Formatter("[{asctime}] [{levelname:<8}] {name}: {message}", "%Y-%m-%d %H:%M:%S", style="{")
    handler.setFormatter(formatter)
    logger = logging.getLogger() if root else logging.getLogger("vector")
    logger.setLevel(level)
    logger.addHandler(handler)


class _ClientEventTask(asyncio.Task):
    pass


class Client:
    """Connects to Vector and dispatches events to ``on_<event>`` coroutines.

    Parameters mirror ``VectorBotBuilder``:

    * ``data_dir``: where the bot's database and keys live (default ``./vector-bot-data``).
    * ``invite_policy``: ``"manual"`` (default: queue Community invites, see
      ``on_community_invite``) or ``"public"`` (auto-accept every invite).
    * ``whitelist``: auto-accept invites only from these npubs.
    * ``password``: encrypt the stored key at rest.
    * ``catch_up``: ``"inline"`` (default) or ``"external"``.
    * ``clearnet`` / ``tor`` / ``i2p``: transport (Tor and I2P need a build with those features).
    * ``max_messages``: message cache size for ``on_message_delete``/``on_message_edit``.

    ``intents`` and other discord.py-only options are accepted and ignored.
    """

    def __init__(
        self,
        *,
        intents: Optional[Intents] = None,
        data_dir: Optional[str] = None,
        invite_policy: str = "manual",
        whitelist: Optional[Sequence[str]] = None,
        password: Optional[str] = None,
        catch_up: str = "inline",
        clearnet: bool = False,
        tor: bool = False,
        tor_bridges: Optional[Sequence[str]] = None,
        i2p: bool = False,
        i2p_sam_port: Optional[int] = None,
        xdc_download_limit: Optional[int] = None,
        max_messages: Optional[int] = 1000,
        activity: Optional[Activity] = None,
        status: Any = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        webhook_base_url: Optional[str] = None,
        webhook_db: Optional[str] = None,
        **options: Any,
    ):
        self._webhook_base_url = webhook_base_url
        self._webhook_db = webhook_db
        self._webhook_store_obj: Any = None
        self.intents = intents or Intents.default()
        self._options = dict(
            data_dir=data_dir, invite_policy=invite_policy, whitelist=list(whitelist) if whitelist else None,
            password=password, catch_up=catch_up, clearnet=clearnet, tor=tor,
            tor_bridges=list(tor_bridges) if tor_bridges else None, i2p=i2p, i2p_sam_port=i2p_sam_port,
            xdc_download_limit=xdc_download_limit,
        )
        self._connection = ConnectionState(self, max_messages=max_messages)
        self._listeners: Dict[str, List[Tuple[asyncio.Future, Callable[..., bool]]]] = {}
        self.extra_events: Dict[str, List[Callable[..., Coroutine[Any, Any, Any]]]] = {}
        self._ready = asyncio.Event() if _has_loop() else None  # created lazily otherwise
        self._closed = False
        self._closing_task: Optional[asyncio.Task] = None
        self._runner: Optional[asyncio.Task] = None
        self._pump: Optional[asyncio.Task] = None
        self._user: Optional[ClientUser] = None
        self._activity = activity
        self._xdc_handlers: Dict[int, Tuple[Callable[..., Any], Any]] = {}
        self._pending_xdc: List[Tuple[Callable[..., Any], Dict[str, Any], Any]] = []
        self._loop = loop

    # ------------------------------------------------------------------------------------
    # properties
    # ------------------------------------------------------------------------------------

    @property
    def native(self) -> Any:
        """The underlying ``vector._native.NativeBot`` (the Rust SDK), for anything not wrapped."""
        return self._connection.native

    @property
    def user(self) -> Optional[ClientUser]:
        return self._user

    @property
    def npub(self) -> Optional[str]:
        return self._connection.self_npub or None

    @property
    def communities(self) -> List[Community]:
        return self._connection.communities

    guilds = communities

    @property
    def users(self) -> List[User]:
        return list(self._connection._users.values())

    @property
    def cached_messages(self) -> Sequence["Message"]:
        return self._connection._message_cache.values()

    @property
    def private_channels(self) -> List[DMChannel]:
        return list(self._connection._dm_channels.values())

    @property
    def voice_clients(self) -> List[Any]:
        return list(self._connection.voice_clients.values())

    @property
    def latency(self) -> float:
        return 0.0

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop or asyncio.get_event_loop()

    @property
    def activity(self) -> Optional[Activity]:
        return self._activity

    def is_ready(self) -> bool:
        return self._ready is not None and self._ready.is_set()

    def is_closed(self) -> bool:
        return self._closed

    @property
    def subscription_ready(self) -> bool:
        return bool(self.native and self.native.subscription_ready())

    @staticmethod
    def features() -> List[str]:
        """Optional features compiled into this install (``voice``, ``xdc``, ``whisper``, ``tor``, ``i2p``)."""
        return list(_native_module().NativeBot.features())

    @staticmethod
    def generate_nsec() -> str:
        """Mint a fresh secret key (``nsec1…``). Store it somewhere safe."""
        return _native_module().NativeBot.generate_nsec()

    # ------------------------------------------------------------------------------------
    # getters / fetchers
    # ------------------------------------------------------------------------------------

    @property
    def webhook_store(self) -> Any:
        """Where this bot's webhooks live (SQLite; ``Client(webhook_db=...)``, ``$WEBHOOKS_DB`` or
        ``<data_dir>/webhooks.db``). Share the path with a ``vector-webhooks`` server to serve their URLs."""
        if self._webhook_store_obj is None:
            import os

            from .ext.webhooks.store import WebhookStore

            path = self._webhook_db or os.environ.get("WEBHOOKS_DB")
            if not path:
                d = self._options.get("data_dir") or "vector-bot-data"
                os.makedirs(d, exist_ok=True)
                path = os.path.join(d, "webhooks.db")
            self._webhook_store_obj = WebhookStore(path)
        return self._webhook_store_obj

    @webhook_store.setter
    def webhook_store(self, store: Any) -> None:
        self._webhook_store_obj = store

    def get_community(self, community_id: str, /) -> Optional[Community]:
        return self._connection.get_community(community_id)

    get_guild = get_community

    def get_channel(self, channel_id: str, /) -> Any:
        return self._connection.get_channel(channel_id)

    def get_partial_messageable(self, channel_id: str, /, **ignored: Any) -> Any:
        from .channel import PartialMessageable

        return PartialMessageable(self._connection, channel_id)

    def get_user(self, npub: str, /) -> Optional[User]:
        return self._connection.get_user(npub)

    def get_all_channels(self):
        for c in self.communities:
            yield from c.channels

    def get_all_members(self):
        for c in self.communities:
            yield from c.members

    def get_emoji(self, code: Any, /) -> Optional[Any]:
        """A custom emoji from the bot's equipped packs, by ``"wave"``, ``":wave:"`` or Discord's ``"<:wave:123>"``.
        Returns a :class:`PartialEmoji` (``str()`` is ``":wave:"``, ``.url`` its image) usable for buttons."""
        from .message import normalize_emoji

        want = (normalize_emoji(code) or "").strip(":")
        return next((e for e in self.emojis if e.name == want), None)

    @property
    def emojis(self) -> List[Any]:
        """Custom emoji from equipped packs, as :class:`PartialEmoji` (``.name``, ``.url``, ``.pack``)."""
        from .message import PartialEmoji

        out = []
        for e in (list(self.native.emojis()) if self.native else []):
            pe = PartialEmoji(name=str(e.get("code", "")).strip(":"), url=e.get("url"))
            pe.pack = e.get("pack")
            out.append(pe)
        return out

    async def fetch_user(self, npub: str, /) -> User:
        user = self._connection.store_user(npub)
        await user.fetch()
        return user

    async def fetch_community(self, community_id: str, /) -> Community:
        return await self._connection.add_community(community_id)

    fetch_guild = fetch_community

    async def fetch_channel(self, channel_id: str, /) -> Any:
        ch = self.get_channel(channel_id)
        if ch is not None:
            return ch
        return self._connection.channel_for(channel_id)

    async def fetch_message(self, message_id: str, /) -> Optional["Message"]:
        return await self._connection.fetch_message(message_id)

    async def create_dm(self, user: Any) -> DMChannel:
        return self._connection.dm_channel(getattr(user, "npub", user))

    async def fetch_communities(self, *, limit: Optional[int] = None):
        for i, cid in enumerate(await self.native.communities()):
            if limit is not None and i >= limit:
                return
            yield await self._connection.add_community(cid)

    fetch_guilds = fetch_communities

    # ------------------------------------------------------------------------------------
    # Vector-specific account actions
    # ------------------------------------------------------------------------------------

    async def create_community(self, name: str, *, description: Optional[str] = None,
                               first_channel: Optional[str] = None, relays: Optional[Sequence[str]] = None) -> Community:
        cid = await self.native.create_community(name, description, first_channel, list(relays) if relays else None)
        return await self._connection.add_community(cid, joined=True)

    create_guild = create_community

    async def join(self, invite_url: str) -> Community:
        """Join a Community from an invite link."""
        cid = await self.native.join(str(invite_url))
        return await self._connection.add_community(cid, joined=True)

    accept_invite_link = join

    async def fetch_invite(self, url: str, /) -> CommunityPreview:
        """Preview an invite link without joining."""
        return CommunityPreview(await self.native.preview_link(str(url)))

    def pending_invites(self) -> List[PendingInvite]:
        """Community invites waiting on a decision (``invite_policy="manual"``)."""
        return [PendingInvite(self._connection, d) for d in self.native.pending_invites()]

    async def accept_invite(self, community_id: str) -> Community:
        await self.native.accept_invite(community_id)
        return await self._connection.add_community(community_id, joined=True)

    async def process_pending_invites(self) -> None:
        await self.native.process_pending_invites()

    async def change_presence(self, *, activity: Optional[Activity] = None, status: Any = None, **ignored: Any) -> None:
        """Set the bot's Vector status text from an activity (``Playing …``) or a plain string."""
        self._activity = activity
        text = activity.to_status() if isinstance(activity, Activity) else (str(activity) if activity else "")
        await self.native.set_status(text)

    async def set_status(self, text: str) -> None:
        await self.native.set_status(text)

    async def block(self, user: Any) -> None:
        await self.native.block(getattr(user, "npub", user))

    async def unblock(self, user: Any) -> None:
        await self.native.unblock(getattr(user, "npub", user))

    async def blocked_users(self) -> List[User]:
        return [self._connection.store_user(p.get("id") or p.get("npub"), p) for p in await self.native.blocked_users()]

    async def set_local_nickname(self, user: Any, nickname: str) -> None:
        """A private nickname for a user, only visible to this bot."""
        await self.native.set_local_nickname(getattr(user, "npub", user), nickname)

    async def sync_dms(self, since_days: Optional[int] = None) -> int:
        return await self.native.sync_dms(since_days)

    async def sync_communities(self) -> int:
        return await self.native.sync_communities()

    async def subscribe_emoji_pack(self, naddr: str) -> Dict[str, Any]:
        return await self.native.subscribe_emoji_pack(naddr)

    async def unsubscribe_emoji_pack(self, naddr: str) -> None:
        await self.native.unsubscribe_emoji_pack(naddr)

    def emoji_packs(self) -> List[Dict[str, Any]]:
        return self.native.emoji_packs()

    async def refresh_emoji_packs(self) -> List[Dict[str, Any]]:
        return await self.native.refresh_emoji_packs()

    async def upload_image(self, path: str) -> str:
        """Upload an image to Blossom and return its URL (for avatars, banners, embeds)."""
        return await self.native.upload_image(str(path))

    async def messages_with_attachment(self, content_hash: str) -> List["Message"]:
        return [self._connection.message_from_incoming(d) for d in await self.native.messages_with_attachment(content_hash)]

    # ------------------------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------------------------

    def event(self, coro: Coro, /) -> Coro:
        """Register an event handler: ``@client.event async def on_message(message): …``."""
        if not inspect.iscoroutinefunction(coro):
            raise TypeError("event registered must be a coroutine function")
        setattr(self, coro.__name__, coro)
        _log.debug("%s has successfully been registered as an event", coro.__name__)
        return coro

    def add_listener(self, func: Callable[..., Coroutine[Any, Any, Any]], /, name: str = MISSING) -> None:
        name = func.__name__ if name is MISSING else name
        if not inspect.iscoroutinefunction(func):
            raise TypeError("Listeners must be coroutines")
        self.extra_events.setdefault(name, []).append(func)

    def remove_listener(self, func: Callable[..., Any], /, name: str = MISSING) -> None:
        name = func.__name__ if name is MISSING else name
        try:
            self.extra_events[name].remove(func)
        except (KeyError, ValueError):
            pass

    def listen(self, name: str = MISSING) -> Callable[[Coro], Coro]:
        """Register an extra listener (several may exist per event): ``@client.listen('on_message')``."""

        def decorator(func: Coro) -> Coro:
            self.add_listener(func, name)
            return func

        return decorator

    def dispatch(self, event: str, /, *args: Any, **kwargs: Any) -> None:
        _log.debug("Dispatching event %s", event)
        method = "on_" + event

        listeners = self._listeners.get(event)
        if listeners:
            removed = []
            for i, (future, condition) in enumerate(listeners):
                if future.cancelled():
                    removed.append(i)
                    continue
                try:
                    result = condition(*args)
                except Exception as exc:
                    future.set_exception(exc)
                    removed.append(i)
                else:
                    if result:
                        if len(args) == 0:
                            future.set_result(None)
                        elif len(args) == 1:
                            future.set_result(args[0])
                        else:
                            future.set_result(args)
                        removed.append(i)
            if len(removed) == len(listeners):
                self._listeners.pop(event)
            else:
                for idx in reversed(removed):
                    del listeners[idx]

        coro = getattr(self, method, None)
        if coro is not None:
            self._schedule_event(coro, method, *args, **kwargs)
        for extra in self.extra_events.get(method, []):
            self._schedule_event(extra, method, *args, **kwargs)

    async def _run_event(self, coro: Callable[..., Coroutine[Any, Any, Any]], event_name: str, *args: Any, **kwargs: Any) -> None:
        try:
            await coro(*args, **kwargs)
        except asyncio.CancelledError:
            pass
        except Exception:
            try:
                await self.on_error(event_name, *args, **kwargs)
            except asyncio.CancelledError:
                pass

    def _schedule_event(self, coro: Callable[..., Coroutine[Any, Any, Any]], event_name: str, *args: Any, **kwargs: Any) -> asyncio.Task:
        return asyncio.ensure_future(self._run_event(coro, event_name, *args, **kwargs))

    async def on_error(self, event_method: str, /, *args: Any, **kwargs: Any) -> None:
        """Default error handler: log the traceback (override like discord.py's)."""
        _log.exception("Ignoring exception in %s", event_method)

    def wait_for(self, event: str, /, *, check: Optional[Callable[..., bool]] = None, timeout: Optional[float] = None) -> Any:
        """Wait for the next matching event: ``msg = await client.wait_for('message', check=…, timeout=30)``."""
        future = asyncio.get_running_loop().create_future()
        if check is None:
            def _check(*args: Any) -> bool:
                return True

            check = _check
        ev = event.lower()
        self._listeners.setdefault(ev, []).append((future, check))
        return asyncio.wait_for(future, timeout)

    async def wait_until_ready(self) -> None:
        if self._ready is None:
            self._ready = asyncio.Event()
        await self._ready.wait()

    async def _on_native_ready(self) -> None:
        """Internal: the Rust bot exists (commands.Bot publishes its slash commands here)."""
        tree = getattr(self, "_app_tree", None)
        if tree is not None:
            tree._register_all()

    async def setup_hook(self) -> None:
        """Runs once after login and before the bot starts listening. Load cogs here."""

    # ------------------------------------------------------------------------------------
    # Mini Apps
    # ------------------------------------------------------------------------------------

    def xdc_app(self, app: str = "*", *, join_when: str = "opened", idle_timeout: Optional[float] = 180.0,
                quiet_timeout: Optional[float] = 900.0, max_sessions: int = 32, max_per_chat: int = 4,
                by_hash: bool = False) -> Callable[[Coro], Coro]:
        """Register a Mini App (WebXDC) handler.

        ``app`` matches the app's manifest id or name, ``"*"`` for any app, or a content hash
        with ``by_hash=True``. The decorated coroutine receives a :class:`vector.XdcSession`::

            @bot.xdc_app("vector-counter")
            async def counter(session):
                async for event in session:
                    ...
        """

        def decorator(func: Coro) -> Coro:
            opts = dict(join_when=join_when, idle_timeout=idle_timeout, quiet_timeout=quiet_timeout,
                        max_sessions=max_sessions, max_per_chat=max_per_chat, by_hash=by_hash)
            self._register_xdc(app, func, opts, None)
            return func

        return decorator

    def _register_xdc(self, app: str, func: Callable[..., Any], opts: Dict[str, Any], owner: Any) -> None:
        if self.native is None:
            self._pending_xdc.append((func, dict(opts, app=app), owner))
            return
        hid = self.native.register_xdc(app, **opts)
        self._xdc_handlers[hid] = (func, owner)

    async def _handle_xdc_session(self, ev: Dict[str, Any]) -> None:
        from .xdc import XdcSession

        entry = self._xdc_handlers.get(ev.get("handler", 0))
        session = XdcSession(self._connection, ev["session"], ev.get("app") or {})
        if entry is None:
            await session.leave()
            return
        func, owner = entry

        async def run() -> None:
            try:
                if owner is not None:
                    await func(owner, session)
                else:
                    await func(session)
            except Exception:
                await self.on_error("xdc_app", session)
            finally:
                await session.leave()

        asyncio.ensure_future(run())
        self.dispatch("xdc_session", session)

    async def _handle_slash_command(self, name: str, args: Dict[str, Any], message: "Message") -> None:
        """Base Client: app_commands tree first, then ``on_slash_command(name, args, message)``."""
        tree = getattr(self, "_app_tree", None)
        if tree is not None and await tree._dispatch(name, args, message):
            return
        self.dispatch("slash_command", name, args, message)

    def register_slash_command(self, name: str, description: str, args: Sequence[Tuple[str, str, str, bool, Sequence[str]]] = ()) -> None:
        """Low-level: publish a native ``/command`` (``commands.Bot`` does this for you)."""
        self.native.register_command(name, description, [(a[0], a[1], a[2], a[3], list(a[4])) for a in args])

    # ------------------------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------------------------

    async def login(self, token: Optional[str] = None, *, mnemonic: Optional[str] = None) -> None:
        """Log in with an ``nsec`` (the "token"), a seed phrase, or nothing (reuse the stored key)."""
        native_mod = _native_module()
        if self._ready is None:
            self._ready = asyncio.Event()
        token = token or None
        if token and len(token.split()) >= 12 and mnemonic is None:
            token, mnemonic = None, token
        global _ACTIVE_CLIENT
        if _ACTIVE_CLIENT is not None and _ACTIVE_CLIENT is not self and not _ACTIVE_CLIENT._closed:
            raise ClientException(
                "only one Vector bot can run per process (vector_core keeps process-global state); "
                "run each bot in its own process"
            )
        _ACTIVE_CLIENT = self
        try:
            native = await native_mod.NativeBot.build(nsec=token, mnemonic=mnemonic, **self._options)
        except native_mod.VectorException as e:
            _ACTIVE_CLIENT = None
            raise LoginFailure(str(e)) from e
        state = self._connection
        state.native = native
        state.self_npub = native.npub
        try:
            prof = await native.cached_profile(native.npub)
        except Exception:
            prof = None
        self._user = ClientUser(state, native.npub, Profile(prof) if prof else None)
        for func, opts, owner in self._pending_xdc:
            opts = dict(opts)
            app = opts.pop("app")
            self._xdc_handlers[native.register_xdc(app, **opts)] = (func, owner)
        self._pending_xdc.clear()
        _log.info("logged in as %s", native.npub)
        await self._on_native_ready()
        await self.setup_hook()

    async def connect(self, *, reconnect: bool = True) -> None:
        """Start listening and process events until :meth:`close`."""
        native = self.native
        if native is None:
            raise ClientException("call login() before connect()")
        self._runner = asyncio.ensure_future(native.start())
        self.dispatch("connect")
        if self._activity is not None:
            asyncio.ensure_future(self._apply_activity())
        try:
            while not self._closed:
                ev = await native.next_event()
                if ev is None:
                    break
                if ev.get("type") == "disconnect":
                    await self._connection.parse(ev)
                    if ev.get("error") and not self._closed:
                        _log.error("listener stopped: %s", ev["error"])
                    break
                asyncio.ensure_future(self._connection.parse(ev))
        finally:
            # let the Rust listener finish on its own: cancelling would leave a native future
            # completing after the interpreter shuts down
            if self._runner is not None and not self._runner.done():
                try:
                    await asyncio.wait_for(asyncio.shield(self._runner), 10)
                except Exception:
                    pass

    async def _apply_activity(self) -> None:
        try:
            await self.change_presence(activity=self._activity)
        except Exception:
            _log.debug("could not set initial status", exc_info=True)

    async def start(self, token: Optional[str] = None, *, reconnect: bool = True, mnemonic: Optional[str] = None) -> None:
        await self.login(token, mnemonic=mnemonic)
        await self.connect(reconnect=reconnect)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for vc in list(self._connection.voice_clients.values()):
            try:
                await vc.disconnect()
            except Exception:
                pass
        for task in list(self._connection._profile_tasks.values()):
            if not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), 2)
                except Exception:
                    pass
        if self.native is not None:
            try:
                await self.native.logout()
            except Exception:
                pass
        if self._ready is not None:
            self._ready.clear()
        global _ACTIVE_CLIENT
        if _ACTIVE_CLIENT is self:
            _ACTIVE_CLIENT = None

    def clear(self) -> None:
        self._closed = False
        if self._ready is not None:
            self._ready.clear()

    async def __aenter__(self) -> "Client":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if not self.is_closed():
            await self.close()
        if self._runner is not None and not self._runner.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._runner), 10)
            except Exception:
                pass

    def run(self, token: Optional[str] = None, *, reconnect: bool = True, log_handler: Optional[logging.Handler] = MISSING,
            log_formatter: logging.Formatter = MISSING, log_level: int = logging.INFO, root_logger: bool = False,
            mnemonic: Optional[str] = None) -> None:
        """Blocking entry point: ``bot.run(os.environ["VECTOR_NSEC"])``.

        ``token`` is the bot's ``nsec``; omit it to reuse the key already stored in ``data_dir``
        (a fresh key is created on first run).
        """
        if log_handler is not None:
            setup_logging(level=log_level, handler=None if log_handler is MISSING else log_handler,
                          formatter=None if log_formatter is MISSING else log_formatter, root=root_logger)

        async def runner() -> None:
            async with self:
                await self.start(token, reconnect=reconnect, mnemonic=mnemonic)
            await _drain_native()

        try:
            asyncio.run(runner())
        except KeyboardInterrupt:
            return


AutoShardedClient = Client


async def _drain_native() -> None:
    """Give in-flight Rust futures a moment to resolve before the event loop closes."""
    for _ in range(20):
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
        if not pending:
            return
        await asyncio.sleep(0.05)


_ACTIVE_CLIENT: Optional["Client"] = None


def _has_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False
