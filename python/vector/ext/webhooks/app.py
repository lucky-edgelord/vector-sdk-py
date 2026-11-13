"""A Discord-compatible webhook server for Vector, built on FastAPI.

Anything that can post to a Discord webhook (CI, Grafana, GitHub, uptime monitors, scripts) can post to a Vector
channel by swapping the URL for ``https://your-host/api/webhooks/<id>/<token>``. Supported:

* ``POST /api/webhooks/{id}/{token}``: Discord execute (JSON or multipart ``payload_json`` + files), ``?wait=true``
* ``POST .../slack`` and ``POST .../github``: Slack- and GitHub-format bodies
* ``GET/PATCH/DELETE /api/webhooks/{id}/{token}``: the webhook itself
* ``GET/PATCH/DELETE .../messages/{message_id}``: read, edit and delete messages the webhook sent
* ``/api/v9``, ``/api/v10`` prefixes, ``Retry-After`` rate limiting, Discord-shaped JSON errors
* ``/admin/webhooks``: create, list and delete webhooks with a bearer key
"""

from __future__ import annotations

import io
import json
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from ... import File
from .compat import PayloadError, discord_payload, github_payload, message_json, slack_payload
from .store import Webhook, WebhookStore

_PREFIXES = ("/api", "/api/v10", "/api/v9", "/api/v8")
_RATE = (5, 2.0)  # 5 requests per 2 seconds, per webhook (Discord's own limit)
_MAX_FILE = 25 * 1024 * 1024


def _err(status: int, message: str, code: int = 0, **extra: Any) -> JSONResponse:
    headers = {"Retry-After": str(extra["retry_after"])} if "retry_after" in extra else None
    return JSONResponse({"message": message, "code": code, **extra}, status_code=status, headers=headers)


class _Limiter:
    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str) -> Optional[float]:
        now, (n, per) = time.monotonic(), _RATE
        q = self._hits[key]
        while q and now - q[0] > per:
            q.popleft()
        if len(q) >= n:
            return round(per - (now - q[0]), 3)
        q.append(now)
        return None


def create_app(client: Any, store: WebhookStore, *, admin_key: Optional[str] = None, base_url: str = "") -> FastAPI:
    """Build the FastAPI app. ``client`` is a logged-in (or logging-in) ``vector.Client``."""
    app = FastAPI(title="Vector webhooks", docs_url=None, redoc_url=None, openapi_url=None)
    limiter = _Limiter()

    # -- helpers ------------------------------------------------------------------------------------------

    def auth(wid: str, token: str) -> Webhook:
        wh = store.verify(wid, token)
        if wh is None:
            raise HTTPException(401 if store.get(wid) else 404, "Invalid Webhook Token" if store.get(wid) else "Unknown Webhook")
        return wh

    def channel_for(wh: Webhook) -> Any:
        ch = client.get_channel(wh.channel_id)
        if ch is None:
            raise HTTPException(404, "Unknown Channel")
        return ch

    async def read_body(request: Request) -> Tuple[Dict[str, Any], List[Tuple[str, bytes]]]:
        ctype = request.headers.get("content-type", "")
        files: List[Tuple[str, bytes]] = []
        if ctype.startswith("multipart/form-data"):
            form = await request.form()
            payload = json.loads(form.get("payload_json") or "{}")
            for key, value in form.multi_items():
                if hasattr(value, "read") and key != "payload_json":
                    data = await value.read()
                    if len(data) > _MAX_FILE:
                        raise PayloadError("files: file too large", 40005)
                    files.append((value.filename or key, data))
            return payload, files
        if ctype.startswith("application/x-www-form-urlencoded"):
            form = await request.form()
            return (json.loads(form["payload"]) if "payload" in form else dict(form)), files
        raw = await request.body()
        try:
            return (json.loads(raw) if raw else {}), files
        except ValueError:
            raise PayloadError("Cannot parse request body as JSON", 50109)

    def public(wh: Webhook) -> Dict[str, Any]:
        return {"id": wh.id, "type": 1, "name": wh.name, "avatar": None, "channel_id": wh.channel_id,
                "guild_id": wh.community_id, "application_id": None, "token": None}

    async def deliver(wh: Webhook, text: str, embeds: List[Any], files: List[Tuple[str, bytes]], wait: bool,
                      shown: Optional[str] = None, username: Optional[str] = None) -> Response:
        if not text and not embeds and not files:
            return _err(400, "Cannot send an empty message", 50006)
        retry = limiter.check(wh.id)
        if retry is not None:
            return _err(429, "You are being rate limited.", 0, retry_after=retry, **{"global": False})
        channel = channel_for(wh)
        vfiles = [File(io.BytesIO(data), filename=name) for name, data in files]
        embed_msg = None
        if text or embeds:
            embed_msg = await channel.send(text or None, embeds=embeds) if embeds else await channel.send(text)
        sent = embed_msg
        for f in vfiles:
            sent = await channel.send(file=f)
        assert sent is not None
        store.add_message(sent.id, wh.id, wh.channel_id)
        if not wait:
            return Response(status_code=204)
        return JSONResponse(message_json(msg_id=sent.id, channel_id=wh.channel_id, webhook_id=wh.id,
                                         name=username or wh.name, content=text if shown is None else shown,
                                         embeds=embeds))

    # -- Discord-compatible routes -------------------------------------------------------------------------

    def routes(prefix: str) -> None:
        base = prefix + "/webhooks/{wid}/{token}"

        @app.post(base)
        async def execute(wid: str, token: str, request: Request, wait: bool = False) -> Response:
            wh = auth(wid, token)
            try:
                payload, files = await read_body(request)
                text, embeds = discord_payload(payload)
            except PayloadError as e:
                return _err(400, str(e), e.code)
            return await deliver(wh, text, embeds, files, wait, shown=payload.get("content") or "",
                                 username=payload.get("username"))

        @app.post(base + "/slack")
        async def execute_slack(wid: str, token: str, request: Request, wait: bool = False) -> Response:
            wh = auth(wid, token)
            try:
                payload, files = await read_body(request)
                text, embeds = slack_payload(payload)
            except PayloadError as e:
                return _err(400, str(e), e.code)
            return await deliver(wh, text, embeds, files, wait)

        @app.post(base + "/github")
        async def execute_github(wid: str, token: str, request: Request, wait: bool = False) -> Response:
            wh = auth(wid, token)
            event = request.headers.get("x-github-event", "")
            try:
                payload, _ = await read_body(request)
            except PayloadError as e:
                return _err(400, str(e), e.code)
            result = github_payload(event, payload)
            if result is None:
                return Response(status_code=204)  # an event we don't render; GitHub just needs a 2xx
            return await deliver(wh, result[0], result[1], [], wait)

        @app.get(base)
        async def get_webhook(wid: str, token: str) -> Dict[str, Any]:
            return public(auth(wid, token))

        @app.patch(base)
        async def modify_webhook(wid: str, token: str, request: Request) -> Dict[str, Any]:
            wh = auth(wid, token)
            body = await request.json()
            if body.get("name"):
                store.rename(wh.id, str(body["name"]))
                wh.name = str(body["name"])[:80]
            return public(wh)

        @app.delete(base)
        async def delete_webhook(wid: str, token: str) -> Response:
            store.delete(auth(wid, token).id)
            return Response(status_code=204)

        mbase = base + "/messages/{mid}"

        async def fetch(wh: Webhook, mid: str) -> Any:
            chan_id = store.message_channel(mid, wh.id)
            if chan_id is None:
                raise HTTPException(404, "Unknown Message")
            channel = client.get_channel(chan_id)
            if channel is None:
                raise HTTPException(404, "Unknown Channel")
            return await channel.fetch_message(mid)

        @app.get(mbase)
        async def get_message(wid: str, token: str, mid: str) -> Dict[str, Any]:
            wh = auth(wid, token)
            msg = await fetch(wh, mid)
            return message_json(msg_id=msg.id, channel_id=wh.channel_id, webhook_id=wh.id, name=wh.name,
                                content=msg.content, embeds=[], timestamp=getattr(msg, "created_at", None))

        @app.patch(mbase)
        async def edit_message(wid: str, token: str, mid: str, request: Request) -> Response:
            wh = auth(wid, token)
            msg = await fetch(wh, mid)
            try:
                payload, _ = await read_body(request)
                text, embeds = discord_payload(payload)
            except PayloadError as e:
                return _err(400, str(e), e.code)
            if embeds:
                await msg.edit(content=text or None, embed=embeds[0])
            else:
                await msg.edit(content=text)
            return JSONResponse(message_json(msg_id=mid, channel_id=wh.channel_id, webhook_id=wh.id, name=wh.name,
                                             content=text, embeds=embeds, edited=True))

        @app.delete(mbase)
        async def delete_message(wid: str, token: str, mid: str) -> Response:
            wh = auth(wid, token)
            msg = await fetch(wh, mid)
            await msg.delete()
            store.drop_message(mid)
            return Response(status_code=204)

    for p in _PREFIXES:
        routes(p)

    # -- errors -------------------------------------------------------------------------------------------

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        code = {401: 50027, 404: 10015}.get(exc.status_code, 0)
        if exc.detail == "Unknown Channel":
            code = 10003
        elif exc.detail == "Unknown Message":
            code = 10008
        return JSONResponse({"message": exc.detail, "code": code}, status_code=exc.status_code)

    # -- admin & health -----------------------------------------------------------------------------------

    def admin(request: Request) -> None:
        if not admin_key:
            raise HTTPException(403, "admin API is disabled (no admin key configured)")
        got = request.headers.get("authorization", "")
        import hmac
        if not hmac.compare_digest(got, f"Bearer {admin_key}"):
            raise HTTPException(401, "Unauthorized")

    def url_for(wid: str, token: str) -> str:
        return f"{base_url.rstrip('/')}/api/webhooks/{wid}/{token}"

    @app.post("/admin/webhooks")
    async def admin_create(request: Request) -> Dict[str, Any]:
        admin(request)
        body = await request.json()
        channel_id = str(body.get("channel_id", ""))
        channel = client.get_channel(channel_id)
        if channel is None:
            raise HTTPException(404, "Unknown Channel")
        community = getattr(getattr(channel, "guild", None), "id", None)
        wh, token = store.create(str(body.get("name") or "webhook"), channel_id, community, body.get("created_by"))
        return {**public(wh), "token": token, "url": url_for(wh.id, token)}

    @app.get("/admin/webhooks")
    async def admin_list(request: Request, channel_id: Optional[str] = None) -> List[Dict[str, Any]]:
        admin(request)
        return [public(w) for w in store.list(channel_id=channel_id)]

    @app.delete("/admin/webhooks/{wid}")
    async def admin_delete(wid: str, request: Request) -> Response:
        admin(request)
        if not store.delete(wid):
            raise HTTPException(404, "Unknown Webhook")
        return Response(status_code=204)

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {"ok": True, "ready": client.is_ready() if hasattr(client, "is_ready") else True}

    return app
