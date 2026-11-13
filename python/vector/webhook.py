"""``discord.Webhook`` / ``discord.SyncWebhook`` for Vector.

Two ways a webhook object works, both with discord.py's API:

* **Bot-side** (``await channel.create_webhook(name=...)``, ``channel.webhooks()``, ``guild.webhooks()``,
  ``Webhook.from_url(url, client=bot)``): sends go straight through the running bot. No HTTP server needed.
* **URL-only** (``Webhook.from_url(url)`` / ``SyncWebhook.from_url(url)`` with no client): sends go over HTTP to a
  ``vector-webhooks`` server (see ``docs/webhooks.md``), exactly like posting to a Discord webhook URL.

Webhook URLs look like Discord's: ``<base>/api/webhooks/<id>/<token>``. The base comes from
``Client(webhook_base_url=...)`` or ``$WEBHOOKS_BASE_URL`` (default ``http://localhost:8080``).
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import uuid
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .embeds import Embed
from .errors import Forbidden, HTTPException, NotFound
from .file import File

__all__ = ("Webhook", "SyncWebhook", "WebhookMessage", "SyncWebhookMessage")

_URL = re.compile(r"^(?P<base>https?://[^/]+(?:/.*?)?)/api(?:/v\d+)?/webhooks/(?P<id>\d{17,20})/(?P<token>[\w\-.]+)/?$")


class _Resp:
    def __init__(self, status: int, text: str) -> None:
        self.status, self.reason, self.text = status, "", text


def _raise(status: int, text: str) -> None:
    resp = _Resp(status, text)
    try:
        msg = json.loads(text).get("message", text)
    except ValueError:
        msg = text
    if status == 404:
        raise NotFound(resp, msg)
    if status in (401, 403):
        raise Forbidden(resp, msg)
    raise HTTPException(resp, msg)


# -- HTTP transport (stdlib only; tests swap ``_async_request``) --------------------------------------------

def _encode(payload: Dict[str, Any], files: Sequence[File]) -> Tuple[bytes, str]:
    if not files:
        return json.dumps(payload).encode(), "application/json"
    boundary = uuid.uuid4().hex
    out = io.BytesIO()

    def part(headers: str, body: bytes) -> None:
        out.write(f"--{boundary}\r\n{headers}\r\n\r\n".encode())
        out.write(body)
        out.write(b"\r\n")

    part('Content-Disposition: form-data; name="payload_json"\r\nContent-Type: application/json',
         json.dumps(payload).encode())
    for i, f in enumerate(files):
        part(f'Content-Disposition: form-data; name="files[{i}]"; filename="{f.filename}"\r\n'
             "Content-Type: application/octet-stream", f.read())
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


def _request(method: str, url: str, payload: Optional[Dict[str, Any]] = None,
             files: Sequence[File] = ()) -> Tuple[int, str]:
    data, ctype = (None, None) if payload is None and not files else _encode(payload or {}, files)
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"User-Agent": "vector-sdk-py", **({"Content-Type": ctype} if ctype else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


async def _async_request(method: str, url: str, payload: Optional[Dict[str, Any]] = None,
                         files: Sequence[File] = ()) -> Tuple[int, str]:
    return await asyncio.get_running_loop().run_in_executor(None, _request, method, url, payload, files)


# -- shared -------------------------------------------------------------------------------------------------

def _payload(content: Any, username: Optional[str], embed: Any, embeds: Any) -> Dict[str, Any]:
    p: Dict[str, Any] = {}
    if content is not None:
        p["content"] = str(content)
    if username:
        p["username"] = username
    all_embeds = list(embeds or []) + ([embed] if embed is not None else [])
    if all_embeds:
        p["embeds"] = [e.to_dict() for e in all_embeds]
    return p


def _files(file: Any, files: Any) -> List[File]:
    return list(files or []) + ([file] if file is not None else [])


def _base_url(client: Any = None) -> str:
    return (getattr(client, "_webhook_base_url", None) or os.environ.get("WEBHOOKS_BASE_URL")
            or "http://localhost:8080").rstrip("/")


class _BaseWebhookMessage:
    def __init__(self, webhook: Any, data: Dict[str, Any], message: Any = None) -> None:
        self._webhook, self._message = webhook, message
        self.id: str = data.get("id", "")
        self.content: str = data.get("content", "")
        self.channel_id: str = data.get("channel_id", webhook.channel_id)
        self.webhook_id: str = webhook.id
        self.embeds: List[Embed] = [Embed.from_dict(e) for e in data.get("embeds") or []]
        self.author_name: str = (data.get("author") or {}).get("username", webhook.name)

    @property
    def channel(self) -> Any:
        state = self._webhook._state
        return state.channel_for(self.channel_id) if state is not None and hasattr(state, "channel_for") else None

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.id!r}>"


class WebhookMessage(_BaseWebhookMessage):
    """A message a webhook sent (``discord.WebhookMessage``)."""

    async def edit(self, **kwargs: Any) -> "WebhookMessage":
        return await self._webhook.edit_message(self.id, **kwargs)

    async def delete(self, *, delay: Optional[float] = None) -> None:
        if delay:
            await asyncio.sleep(delay)
        await self._webhook.delete_message(self.id)


class SyncWebhookMessage(_BaseWebhookMessage):
    def edit(self, **kwargs: Any) -> "SyncWebhookMessage":
        return self._webhook.edit_message(self.id, **kwargs)

    def delete(self, *, delay: Optional[float] = None) -> None:
        if delay:
            import time
            time.sleep(delay)
        self._webhook.delete_message(self.id)


class _BaseWebhook:
    def __init__(self, data: Dict[str, Any], *, client: Any = None, base_url: Optional[str] = None) -> None:
        self.id: str = str(data["id"])
        self.token: Optional[str] = data.get("token")
        self.name: Optional[str] = data.get("name")
        self.channel_id: Optional[str] = data.get("channel_id")
        self.guild_id: Optional[str] = data.get("guild_id")
        self.avatar = None
        self.user = None
        self.source_guild = self.source_channel = None
        self._client = client
        self._state = getattr(client, "_connection", None)
        self._base = (base_url or _base_url(client)).rstrip("/")
        from . import WebhookType  # stub enum: ``WebhookType.incoming`` works

        self.type = WebhookType.incoming

    @property
    def url(self) -> str:
        return f"{self._base}/api/webhooks/{self.id}/{self.token}"

    @property
    def channel(self) -> Any:
        return self._client.get_channel(self.channel_id) if self._client and self.channel_id else None

    @property
    def guild(self) -> Any:
        return self._client.get_guild(self.guild_id) if self._client and self.guild_id else None

    def is_partial(self) -> bool:
        return self.channel_id is None

    def is_authenticated(self) -> bool:
        return self._client is not None

    def _local(self) -> bool:
        return self._client is not None and self._store() is not None and self._store().get(self.id) is not None

    def _store(self) -> Any:
        return getattr(self._client, "webhook_store", None) if self._client is not None else None

    def _api(self, path: str = "", wait: bool = False) -> str:
        return f"{self._base}/api/webhooks/{self.id}/{self.token}{path}" + ("?wait=true" if wait else "")

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, _BaseWebhook) and other.id == self.id

    def __hash__(self) -> int:
        return hash(self.id)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.id!r} name={self.name!r} channel_id={self.channel_id!r}>"


class Webhook(_BaseWebhook):
    """``discord.Webhook``. Get one from :meth:`TextChannel.create_webhook`, :meth:`TextChannel.webhooks`,
    :meth:`Community.webhooks` or :meth:`Webhook.from_url`."""

    @classmethod
    def from_url(cls, url: str, *, session: Any = None, client: Any = None, bot_token: Any = None) -> "Webhook":
        m = _URL.match(url.strip())
        if not m:
            raise ValueError("Invalid webhook URL given.")
        wh = cls({"id": m["id"], "token": m["token"]}, client=client, base_url=m["base"])
        if client is not None and getattr(client, "webhook_store", None) is not None:
            known = client.webhook_store.get(wh.id)
            if known is not None:
                wh.name, wh.channel_id, wh.guild_id = known.name, known.channel_id, known.community_id
        return wh

    @classmethod
    def partial(cls, id: Any, token: str, *, session: Any = None, client: Any = None, bot_token: Any = None) -> "Webhook":
        return cls.from_url(f"{_base_url(client)}/api/webhooks/{id}/{token}", client=client)

    @classmethod
    def _from_row(cls, row: Any, token: Optional[str], client: Any) -> "Webhook":
        return cls({"id": row.id, "token": token, "name": row.name, "channel_id": row.channel_id,
                    "guild_id": row.community_id}, client=client)

    async def fetch(self, *, prefer_auth: bool = True) -> "Webhook":
        if self._local():
            row = self._store().get(self.id)
            self.name, self.channel_id, self.guild_id = row.name, row.channel_id, row.community_id
            return self
        status, text = await _async_request("GET", self._api())
        if status >= 300:
            _raise(status, text)
        d = json.loads(text)
        self.name, self.channel_id, self.guild_id = d.get("name"), d.get("channel_id"), d.get("guild_id")
        return self

    async def send(self, content: Any = None, *, username: Optional[str] = None, avatar_url: Any = None,
                   tts: bool = False, ephemeral: bool = False, file: Optional[File] = None,
                   files: Optional[Sequence[File]] = None, embed: Optional[Embed] = None,
                   embeds: Optional[Sequence[Embed]] = None, allowed_mentions: Any = None, view: Any = None,
                   thread: Any = None, thread_name: Optional[str] = None, wait: bool = False,
                   suppress_embeds: bool = False, silent: bool = False, delete_after: Optional[float] = None,
                   **ignored: Any) -> Optional[WebhookMessage]:
        all_files = _files(file, files)
        if self._local():
            channel = self._client.get_channel(self.channel_id)
            if channel is None:
                raise NotFound(_Resp(404, ""), "Unknown Channel")
            text = None if content is None else str(content)
            name = username or None
            if name:
                text = f"**{name}**\n{text}" if text else f"**{name}**"
            all_embeds = list(embeds or []) + ([embed] if embed is not None else [])
            msg = await channel.send(text, embeds=all_embeds or None, files=all_files or None, view=view,
                                     delete_after=delete_after)
            self._store().add_message(msg.id, self.id, self.channel_id)
            if not wait:
                return None
            return WebhookMessage(self, {"id": msg.id, "content": text or "", "channel_id": self.channel_id,
                                         "embeds": [e.to_dict() for e in all_embeds],
                                         "author": {"username": username or self.name}}, msg)
        status, text = await _async_request("POST", self._api(wait=wait),
                                            _payload(content, username, embed, embeds), all_files)
        if status >= 300:
            _raise(status, text)
        return WebhookMessage(self, json.loads(text)) if wait and text else None

    async def _local_message(self, message_id: str) -> Any:
        chan = self._store().message_channel(message_id, self.id)
        if chan is None:
            raise NotFound(_Resp(404, ""), "Unknown Message")
        return await self._client.get_channel(chan).fetch_message(message_id)

    async def fetch_message(self, id: str, /, *, thread: Any = None) -> WebhookMessage:
        if self._local():
            msg = await self._local_message(id)
            return WebhookMessage(self, {"id": msg.id, "content": msg.content, "channel_id": self.channel_id}, msg)
        status, text = await _async_request("GET", self._api(f"/messages/{id}"))
        if status >= 300:
            _raise(status, text)
        return WebhookMessage(self, json.loads(text))

    async def edit_message(self, message_id: str, *, content: Any = ..., embed: Any = ..., embeds: Any = ...,
                           attachments: Any = ..., view: Any = ..., allowed_mentions: Any = None, thread: Any = None,
                           **ignored: Any) -> WebhookMessage:
        if self._local():
            msg = await self._local_message(message_id)
            kw: Dict[str, Any] = {}
            if content is not ...:
                kw["content"] = content
            if embed is not ...:
                kw["embed"] = embed
            elif embeds is not ...:
                kw["embeds"] = embeds
            if view is not ...:
                kw["view"] = view
            await msg.edit(**kw)
            return WebhookMessage(self, {"id": message_id, "content": "" if content in (..., None) else str(content),
                                         "channel_id": self.channel_id}, msg)
        payload = _payload(None if content is ... else content, None,
                           None if embed is ... else embed, None if embeds is ... else embeds)
        status, text = await _async_request("PATCH", self._api(f"/messages/{message_id}"), payload)
        if status >= 300:
            _raise(status, text)
        return WebhookMessage(self, json.loads(text))

    async def delete_message(self, message_id: str, /, *, thread: Any = None) -> None:
        if self._local():
            msg = await self._local_message(message_id)
            await msg.delete()
            self._store().drop_message(message_id)
            return
        status, text = await _async_request("DELETE", self._api(f"/messages/{message_id}"))
        if status >= 300:
            _raise(status, text)

    async def edit(self, *, name: Optional[str] = None, avatar: Any = None, channel: Any = None,
                   reason: Optional[str] = None, prefer_auth: bool = True) -> "Webhook":
        if self._local():
            if name:
                self._store().rename(self.id, name)
                self.name = name[:80]
            if channel is not None:
                raise NotImplementedError("moving a webhook to another channel isn't supported; create a new one")
            return self
        status, text = await _async_request("PATCH", self._api(), {"name": name} if name else {})
        if status >= 300:
            _raise(status, text)
        self.name = json.loads(text).get("name", self.name)
        return self

    async def delete(self, *, reason: Optional[str] = None, prefer_auth: bool = True) -> None:
        if self._local():
            self._store().delete(self.id)
            return
        status, text = await _async_request("DELETE", self._api())
        if status >= 300:
            _raise(status, text)


class SyncWebhook(_BaseWebhook):
    """``discord.SyncWebhook``: blocking, URL-only (talks to a ``vector-webhooks`` server)."""

    @classmethod
    def from_url(cls, url: str, *, session: Any = None, bot_token: Any = None) -> "SyncWebhook":
        m = _URL.match(url.strip())
        if not m:
            raise ValueError("Invalid webhook URL given.")
        return cls({"id": m["id"], "token": m["token"]}, base_url=m["base"])

    @classmethod
    def partial(cls, id: Any, token: str, *, session: Any = None, bot_token: Any = None) -> "SyncWebhook":
        return cls.from_url(f"{_base_url()}/api/webhooks/{id}/{token}")

    def _call(self, method: str, path: str = "", payload: Any = None, files: Sequence[File] = (),
              wait: bool = False) -> Optional[Dict[str, Any]]:
        status, text = _request(method, self._api(path, wait), payload, files)
        if status >= 300:
            _raise(status, text)
        return json.loads(text) if text else None

    def fetch(self, *, prefer_auth: bool = True) -> "SyncWebhook":
        d = self._call("GET") or {}
        self.name, self.channel_id, self.guild_id = d.get("name"), d.get("channel_id"), d.get("guild_id")
        return self

    def send(self, content: Any = None, *, username: Optional[str] = None, avatar_url: Any = None,
             file: Optional[File] = None, files: Optional[Sequence[File]] = None, embed: Optional[Embed] = None,
             embeds: Optional[Sequence[Embed]] = None, wait: bool = False, **ignored: Any) -> Optional[SyncWebhookMessage]:
        d = self._call("POST", "", _payload(content, username, embed, embeds), _files(file, files), wait=wait)
        return SyncWebhookMessage(self, d) if wait and d else None

    def fetch_message(self, id: str, /, *, thread: Any = None) -> SyncWebhookMessage:
        return SyncWebhookMessage(self, self._call("GET", f"/messages/{id}") or {})

    def edit_message(self, message_id: str, *, content: Any = None, embed: Any = None, embeds: Any = None,
                     **ignored: Any) -> SyncWebhookMessage:
        return SyncWebhookMessage(self, self._call("PATCH", f"/messages/{message_id}",
                                                   _payload(content, None, embed, embeds)) or {})

    def delete_message(self, message_id: str, /, *, thread: Any = None) -> None:
        self._call("DELETE", f"/messages/{message_id}")

    def edit(self, *, name: Optional[str] = None, **ignored: Any) -> "SyncWebhook":
        d = self._call("PATCH", "", {"name": name} if name else {}) or {}
        self.name = d.get("name", self.name)
        return self

    def delete(self, *, reason: Optional[str] = None, prefer_auth: bool = True) -> None:
        self._call("DELETE")
