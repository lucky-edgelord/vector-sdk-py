"""``Messageable``: the ``send`` / ``typing`` / ``history`` mixin shared by channels, users and contexts."""

from __future__ import annotations

import asyncio
import datetime
import math
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, List, Optional, Sequence, Tuple, Union

if TYPE_CHECKING:
    from .embeds import Embed
    from .file import File
    from .message import Message
    from .state import ConnectionState
    from .ui.view import View

__all__ = ("Messageable", "Typing", "Snowflake", "GuildChannel", "PrivateChannel")


class Snowflake:
    """Anything with an ``id`` (kept for type hints ported from discord.py)."""

    id: str


class Typing:
    """``async with channel.typing():`` keeps the typing indicator up until the block exits."""

    def __init__(self, messageable: "Messageable"):
        self.messageable = messageable
        self._task: Optional[asyncio.Task] = None

    async def _do(self) -> None:
        target = await self.messageable._get_channel_target()
        await self.messageable._state.native.channel_typing(*target)

    async def _loop(self) -> None:
        while True:
            try:
                await self._do()
            except Exception:
                pass
            await asyncio.sleep(5)

    def __await__(self):
        return self._do().__await__()

    async def __aenter__(self) -> None:
        self._task = asyncio.ensure_future(self._loop())

    async def __aexit__(self, *exc: Any) -> None:
        if self._task:
            self._task.cancel()


def _reference_id(reference: Any) -> Optional[str]:
    if reference is None:
        return None
    if isinstance(reference, str):
        return reference
    return getattr(reference, "message_id", None) or getattr(reference, "id", None)


class Messageable:
    """Mixin for everything you can ``send`` to."""

    __slots__ = ()
    _state: "ConnectionState"

    async def _get_channel_target(self) -> Tuple[str, Optional[str]]:
        """``(channel_id, kind)`` where kind is ``"dm"``, ``"community"`` or ``None`` (auto)."""
        raise NotImplementedError

    async def _get_channel(self) -> Any:
        cid, kind = await self._get_channel_target()
        return self._state.channel_for(cid, kind=kind)

    async def send(
        self,
        content: Optional[Any] = None,
        *,
        embed: Optional["Embed"] = None,
        embeds: Optional[Sequence["Embed"]] = None,
        file: Optional["File"] = None,
        files: Optional[Sequence["File"]] = None,
        reference: Optional[Any] = None,
        delete_after: Optional[float] = None,
        expires_in: Optional[float] = None,
        view: Optional["View"] = None,
        to_bot: Optional[str] = None,
        mention_author: Optional[bool] = None,
        tts: bool = False,
        stickers: Any = None,
        nonce: Any = None,
        allowed_mentions: Any = None,
        suppress_embeds: bool = False,
        silent: bool = False,
        poll: Any = None,
        ephemeral: bool = False,
    ) -> "Message":
        """Send a message. Accepts discord.py's arguments.

        * ``embed`` / ``embeds`` are rendered to Vector markdown (see :class:`vector.Embed`).
        * ``file`` / ``files`` upload attachments; the text becomes the first file's caption.
        * ``delete_after`` sets a NIP-40 expiry (honoured by every Vector client) *and* deletes
          the message after that many seconds.
        * ``expires_in``: just the NIP-40 expiry, in seconds.
        * ``view``: a :class:`vector.ui.View`, rendered as reaction buttons.
        * ``to_bot``: address a specific bot's command (an npub).
        """
        state = self._state
        native = state.native
        channel_id, kind = await self._get_channel_target()

        all_embeds: List["Embed"] = list(embeds or [])
        if embed is not None:
            all_embeds.insert(0, embed)
        all_files: List["File"] = list(files or [])
        if file is not None:
            all_files.insert(0, file)

        # embed images given as web URLs are downloaded and sent as attachments (Vector shows no inline images)
        keep_urls = True
        fetched = await _fetch_images(all_embeds)
        if fetched:
            all_files.extend(fetched)
            keep_urls = False

        def build(part: str) -> str:
            out: List[str] = []
            if part != "footer" and content is not None:
                out.append(_DISCORD_EMOJI.sub(r":\g<name>:", str(content)))  # "<:wave:123>" -> ":wave:"
            for e in all_embeds:
                md = e.to_markdown(part=part, images=keep_urls)
                if md:
                    out.append(md)
            if part != "body" and view is not None:
                legend = view._legend()
                if legend:
                    out.append(legend)
            return "\n\n".join(p for p in out if p)

        # with an attached image the footer goes in a second message, so the image sits above it
        wanted_names = {n for e in all_embeds for n in e.attachment_names()} | {f.filename for f in fetched}
        split = bool(all_files) and any(f.filename in wanted_names for f in all_files) and \
            any(e.to_markdown(part="footer") for e in all_embeds)
        text = build("body") if split else build("all")
        footer_text = build("footer") if split else ""

        reply_to = _reference_id(reference)
        expiry = expires_in if expires_in is not None else delete_after
        expiry_s = int(math.ceil(expiry)) if expiry else None

        # embed images referenced as attachment://name go first so the caption sits on them
        wanted = {n for e in all_embeds for n in e.attachment_names()}
        all_files.sort(key=lambda f: 0 if f.filename in wanted else 1)

        if not text and not all_files:
            from .errors import InvalidArgument

            raise InvalidArgument("cannot send an empty message")

        if all_files:
            message_id = None
            # captions don't survive Vector reloading a chat (the text under an attachment can vanish), so with
            # an embed the text goes out as its own message and the image(s) follow without a caption
            own_text = bool(all_embeds) and bool(text)
            if own_text:
                message_id = await native.channel_send(channel_id, kind, text, reply_to=reply_to,
                                                       expires_in=expiry_s, to_bot=to_bot)
                reply_to_files = None
            else:
                reply_to_files = reply_to
            for i, f in enumerate(all_files):
                caption = text if (i == 0 and text and not own_text) else None
                if f.path is not None:
                    mid = await native.channel_send_file(channel_id, kind, f.path, caption=caption,
                                                         reply_to=reply_to_files if i == 0 else None,
                                                         expires_in=expiry_s, compress=f.compress)
                else:
                    mid = await native.channel_send_bytes(channel_id, kind, f.read(), f.filename, caption=caption,
                                                          reply_to=reply_to_files if i == 0 else None,
                                                          expires_in=expiry_s, compress=f.compress)
                message_id = mid if own_text else (message_id or mid)
        else:
            message_id = await native.channel_send(channel_id, kind, text, reply_to=reply_to,
                                                   expires_in=expiry_s, to_bot=to_bot)

        message = await state.sent_message(message_id, channel_id, kind, text, reply_to)
        if footer_text:
            first = message
            message_id = await native.channel_send(channel_id, kind, footer_text, reply_to=None,
                                                   expires_in=expiry_s, to_bot=to_bot)
            message = await state.sent_message(message_id, channel_id, kind, footer_text, None)
            if delete_after is not None:
                asyncio.ensure_future(first.delete(delay=delete_after))
        if view is not None:
            await view._start(message)
        if delete_after is not None:
            asyncio.ensure_future(message.delete(delay=delete_after))
        return message

    def typing(self) -> Typing:
        return Typing(self)

    async def trigger_typing(self) -> None:
        await Typing(self)._do()

    async def fetch_message(self, id: str, /) -> "Message":
        msg = await self._state.fetch_message(id)
        if msg is None:
            from .errors import NotFound

            raise NotFound(f"no message {id}", "message")
        return msg

    def get_partial_message(self, message_id: str, /) -> Any:
        from .message import PartialMessage

        return PartialMessage(channel=self, id=message_id)  # type: ignore[arg-type]

    async def history(
        self,
        *,
        limit: Optional[int] = 100,
        before: Optional[Any] = None,
        after: Optional[Any] = None,
        oldest_first: Optional[bool] = None,
        around: Any = None,
        fetch: bool = True,
    ) -> AsyncIterator["Message"]:
        """Iterate messages newest-first (``async for m in channel.history(limit=50)``).

        Reads what this device stores; for Community channels, when that runs out and
        ``fetch`` is true, older history is pulled from relays.
        """
        state = self._state
        channel_id, kind = await self._get_channel_target()
        channel = state.channel_for(channel_id, kind=kind)
        before_ts = _as_ms(before)
        after_ts = _as_ms(after)
        cursor: Optional[str] = None
        if before_ts is not None:
            cursor = f"{before_ts}:{'0' * 64}"
        out: List["Message"] = []
        yielded = 0
        remaining = limit if limit is not None else float("inf")
        synced_once = False
        done = False
        while remaining > 0 and not done:
            page_size = int(min(remaining, 100))
            raw = await state.native.channel_history(channel_id, kind, page_size, before=cursor)
            if not raw:
                if fetch and kind != "dm" and channel_id and not synced_once and state.native.channel_kind(channel_id) == "community":
                    synced_once = True
                    try:
                        got = await state.native.channel_sync(channel_id, 500, before=cursor)
                    except Exception:
                        got = 0
                    if got:
                        continue
                break
            raw.sort(key=lambda m: (m.get("at", 0), m.get("id", "")), reverse=True)
            for m in raw:
                if after_ts is not None and m.get("at", 0) <= after_ts:
                    done = True
                    break
                msg = state.message_from_raw(m, channel)
                if oldest_first:
                    out.append(msg)
                else:
                    yield msg
                    yielded += 1
                remaining -= 1
                if remaining <= 0:
                    break
            last = raw[-1]
            cursor = f"{last.get('at', 0)}:{last.get('id', '')}"
            if len(raw) < page_size:
                synced_once = synced_once or not fetch
                if not fetch or kind == "dm":
                    break
        if oldest_first:
            for msg in reversed(out):
                yield msg

    async def pins(self) -> List["Message"]:
        channel = await self._get_channel()
        return await channel.pins()


def _as_ms(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=datetime.timezone.utc)
        return int(value.timestamp() * 1000)
    created = getattr(value, "created_at", None)
    if isinstance(created, datetime.datetime):
        return int(created.timestamp() * 1000)
    return None


class GuildChannel:
    """Marker base for Community channels (``isinstance(ch, vector.abc.GuildChannel)``)."""

    __slots__ = ()


class PrivateChannel:
    """Marker base for DMs."""

    __slots__ = ()



import re as _re

# Discord's custom-emoji markup in text; Vector writes the same emoji as :code:
_DISCORD_EMOJI = _re.compile(r"<a?:(?P<name>[\w~-]+):\d*>")


async def _fetch_images(embeds: List[Any]) -> List[Any]:
    """Download http(s) embed images (max 8 MB each) so they can go out as real attachments. Failures are skipped
    and the embed falls back to showing the link."""
    import io
    import os
    import urllib.request
    from urllib.parse import urlparse

    from .file import File

    urls: List[str] = []
    for e in embeds:
        for u in e.image_urls():
            if u.startswith(("http://", "https://")) and u not in urls:
                urls.append(u)
    if not urls:
        return []

    def get(u: str) -> Optional[bytes]:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "vector-sdk-py"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = r.read(8 * 1024 * 1024 + 1)
            return data if 0 < len(data) <= 8 * 1024 * 1024 else None
        except Exception:
            return None

    loop = asyncio.get_running_loop()
    out: List[Any] = []
    for u in urls:
        data = await loop.run_in_executor(None, get, u)
        if data is None:
            return []  # keep it simple: if any image fails, every image stays a link
        name = os.path.basename(urlparse(u).path) or "image.png"
        out.append(File(io.BytesIO(data), filename=name))
    return out
