"""Mini App (WebXDC) panels: a real UI for views, embeds and modals.

Reaction buttons are the default UI. Pass ``xdc=True`` and the same ``View`` and ``Embed`` are shown as
a Mini App instead: a tap-to-open card in chat that opens real buttons, drop-downs, a proper embed card
(colour, fields, images, footer) and form pop-ups. Your callbacks do not change::

    class Poll(ui.View):
        @ui.button(label="Yes", style=ui.ButtonStyle.success)
        async def yes(self, interaction, button):
            await interaction.response.edit_message(content="Yes wins")

    await ctx.send(embed=vector.Embed(title="Poll"), view=Poll(), xdc=True)

Or opt a whole view in: ``class Poll(ui.View): xdc = True``.

How it works: the bot ships one small bundled ``.xdc`` per panel (the app is in ``xdc_app/index.html`` and
the first render is baked into it, so it shows instantly even if the bot is offline). The app talks to the
bot over the Mini App's realtime channel; the SDK tells the bot who clicked (``verified_sender``), so a
click can't be forged in someone else's name. Clicks arrive as normal :class:`Interaction` objects.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import re
import shutil
import tempfile
import zipfile
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from ..utils import MISSING
from .interaction import Interaction, InteractionResponse, InteractionType
from .themes import Theme, get_theme

if TYPE_CHECKING:
    from ..message import Message
    from ..state import ConnectionState
    from ..xdc import XdcSession

_log = logging.getLogger("vector.ui.xdc")

APP_ID = "vector-ui"
_TEMPLATE = os.path.join(os.path.dirname(__file__), "xdc_app", "index.html")
_tmpdirs: List[str] = []

__all__ = ("Panel", "send_panel", "APP_ID")


def _cleanup() -> None:
    for d in _tmpdirs:
        shutil.rmtree(d, ignore_errors=True)


atexit.register(_cleanup)


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(name)) or "file"


def _text_of(embeds: Sequence[Any], content: Optional[str]) -> str:
    bits = [content] if content else []
    for e in embeds:
        bits.extend(x for x in (e.title, e.description) if x)
    return " — ".join(bits)[:300]


class Panel:
    """One Mini App panel: the state shown in it, who has it open, and the view behind it."""

    def __init__(self, state: "ConnectionState", *, content: Optional[str], embeds: Sequence[Any], view: Any,
                 assets: Dict[str, bytes], theme: Optional[Theme] = None):
        self._state = state
        self.theme: Theme = theme or get_theme(None)
        self.content = content
        self.embeds: List[Any] = list(embeds)
        self.view = view
        self.assets = assets
        self.sessions: "set[XdcSession]" = set()
        self.message: Any = None
        self.message_id: str = ""
        self.channel: Any = None
        self.closed = False
        self._modals: Dict[str, Any] = {}

    # -- what the app draws ---------------------------------------------------------------

    def spec(self) -> Dict[str, Any]:
        from .view import Button, Select

        embeds = []
        for e in self.embeds:
            d = e.to_dict()
            embeds.append(d)
        rows: Dict[int, List[Dict[str, Any]]] = {}
        auto_row, auto_width = 0, 0
        for c in (self.view.children if self.view is not None else []):
            if isinstance(c, Select):
                comp = {"type": "select", "id": c.custom_id, "placeholder": c.placeholder, "min": c.min_values,
                        "max": c.max_values, "disabled": c.disabled,
                        "options": [{"label": o.label, "value": o.value, "description": o.description,
                                     "emoji": str(o.emoji) if o.emoji else None,
                                     "default": bool(o.default)} for o in c.options]}
                width = 5
            elif isinstance(c, Button):
                comp = {"type": "button", "id": c.custom_id, "label": c.label, "style": _STYLE.get(int(c.style), "secondary"),
                        "disabled": c.disabled, "url": c.url, "emoji": _plain_emoji(c)}
                width = 1
            else:
                continue
            if c.row is not None:
                row = c.row
            else:
                if auto_width + width > 5:
                    auto_row, auto_width = auto_row + 1, 0
                row, auto_width = auto_row, auto_width + width
            rows.setdefault(row, []).append(comp)
        me = self._state.client.user
        return {"content": self.content, "embeds": embeds, "rows": [rows[r] for r in sorted(rows)],
                "closed": self.closed, "title": _text_of(self.embeds, self.content)[:60],
                "theme": self.theme.to_spec(), "bot": {"name": getattr(me, "name", None) or "Bot", "avatar": None}}

    async def broadcast(self, obj: Dict[str, Any]) -> None:
        for s in list(self.sessions):
            try:
                await s.send_json(obj)
            except Exception:
                self.sessions.discard(s)

    async def render(self) -> None:
        await self.broadcast({"t": "render", "spec": self.spec()})

    # -- changing it ---------------------------------------------------------------------

    async def update(self, *, content: Any = MISSING, embeds: Any = MISSING, view: Any = MISSING) -> None:
        if content is not MISSING:
            self.content = None if content is None else str(content)
        if embeds is not MISSING:
            self.embeds = list(embeds or [])
        if view is not MISSING and view is not self.view:
            if self.view is not None:
                self.view._xdc_panel = None
                self.view.stop()
            self.view = view
            if view is not None:
                view._xdc_panel = self
                view.message = self.message
                self._state._views[self.message_id] = view
                if view._stopped is None or view._stopped.done():
                    view._stopped = asyncio.get_running_loop().create_future()
                view._refresh_timeout()
        await self.render()

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        await self.broadcast({"t": "closed"})

    async def toast(self, npub: str, text: str) -> None:
        await self.broadcast({"t": "toast", "to": npub, "text": text})

    async def open_modal(self, npub: str, modal: Any) -> None:
        if not modal.custom_id:
            import uuid

            modal.custom_id = "m" + uuid.uuid4().hex[:12]
        self._modals[(npub, modal.custom_id)] = modal
        fields = [{"id": f.custom_id, "label": f.label, "style": "paragraph" if int(f.style) == 2 else "short",
                   "placeholder": f.placeholder, "default": f.default, "required": f.required,
                   "min": f.min_length, "max": f.max_length} for f in modal.children]
        await self.broadcast({"t": "modal", "to": npub, "modal": {"id": modal.custom_id, "title": modal.title,
                                                                    "fields": fields}})

    # -- what comes back ------------------------------------------------------------------

    async def _on_event(self, session: "XdcSession", ev: Any) -> None:
        if ev.type == "peer_join":
            await session.send_json({"t": "render", "spec": self.spec()})
            return
        if ev.type != "data":
            return
        try:
            msg = ev.json()
        except ValueError:
            return
        kind = msg.get("t")
        if kind == "hello":
            await session.send_json({"t": "render", "spec": self.spec()})
            return
        npub = ev.verified_sender
        if npub is None:
            return  # only act for a sender the SDK can prove
        try:
            if kind == "click":
                await self._click(npub, str(msg.get("id", "")), [str(v) for v in msg.get("values") or []])
            elif kind == "submit":
                await self._submit(npub, str(msg.get("modal", "")), msg.get("values") or {})
        except Exception:
            _log.exception("panel event failed")

    async def _user(self, npub: str) -> Any:
        community = getattr(self.channel, "community", None)
        if community is not None:
            await self._state.ensure_profile(npub)
            return community._member(npub)
        return await self._state.ensure_profile(npub)

    def _interaction(self, user: Any, data: Dict[str, Any], *, item: Any = None,
                     type: str = InteractionType.component) -> "XdcInteraction":
        return XdcInteraction(panel=self, client=self._state.client, user=user, message=self.message,
                              channel=self.channel, view=self.view, item=item, data=data, type=type)

    async def _click(self, npub: str, custom_id: str, values: List[str]) -> None:
        view = self.view
        if view is None or view.is_finished():
            return
        item = view.find_item(custom_id)
        if item is None:
            return
        user = await self._user(npub)
        data: Dict[str, Any] = {"custom_id": custom_id}
        if hasattr(item, "_selected"):
            item._selected[npub] = list(values)
            item._last_user = npub
            data["values"] = list(values)
        interaction = self._interaction(user, data, item=item)
        try:
            if not await view.interaction_check(interaction):
                await self.toast(npub, "That isn't for you.")
                return
            view._refresh_timeout()
            await item.callback(interaction)
        except Exception as e:
            await view.on_error(interaction, e, item)

    async def _submit(self, npub: str, modal_id: str, values: Dict[str, Any]) -> None:
        modal = self._modals.pop((npub, modal_id), None)
        if modal is None:
            return
        for f in modal.children:
            f._value = str(values.get(f.custom_id, f.default or ""))
        user = await self._user(npub)
        submit = self._interaction(user, {"custom_id": modal.custom_id,
                                          "components": {f.custom_id: f.value for f in modal.children}},
                                   type=InteractionType.modal_submit)
        try:
            if await modal.interaction_check(submit):
                await modal.on_submit(submit)
        except Exception as e:
            await modal.on_error(submit, e)


def _plain_emoji(button: Any) -> Optional[str]:
    # the reaction-mode auto letters (🇦 🇧 …) only exist to be tapped as reactions; a real button doesn't need them
    e = getattr(button, "emoji", None)
    if not e:
        return None
    e = str(e)
    if len(e) == 1 and 0x1F1E6 <= ord(e) <= 0x1F1FF:
        return None
    return e


_STYLE = {1: "primary", 2: "secondary", 3: "success", 4: "danger", 5: "link"}


class XdcResponse(InteractionResponse):
    """``interaction.response`` for a panel: edits redraw the panel, ephemeral replies are private toasts."""

    async def edit_message(self, *, content: Any = MISSING, embed: Any = MISSING, embeds: Any = MISSING,
                           view: Any = MISSING, **ignored: Any) -> Optional["Message"]:
        self._done = True
        panel = self._parent._panel
        new_embeds: Any = MISSING
        if embed is not MISSING or embeds is not MISSING:
            new_embeds = ([embed] if embed not in (MISSING, None) else []) + list(embeds if embeds not in (MISSING, None) else [])
        await panel.update(content=content, embeds=new_embeds, view=view)
        return panel.message

    async def send_message(self, content: Optional[Any] = None, *, embed: Any = None, embeds: Any = None,
                           ephemeral: bool = False, **kwargs: Any) -> Optional["Message"]:
        if ephemeral:
            self._done = True
            all_embeds = ([embed] if embed else []) + list(embeds or [])
            text = (str(content) if content else "") or _text_of(all_embeds, None) or "Done."
            await self._parent._panel.toast(self._parent.user.npub, text)
            return None
        return await super().send_message(content, embed=embed, embeds=embeds, ephemeral=False, **kwargs)

    async def send_modal(self, modal: Any, /) -> None:
        self._done = True
        await self._parent._panel.open_modal(self._parent.user.npub, modal)


class XdcInteraction(Interaction):
    def __init__(self, *, panel: Panel, **kwargs: Any):
        super().__init__(**kwargs)
        self._panel = panel
        self.response = XdcResponse(self)


# ----------------------------------------------------------------------------------------------------------------
# sending
# ----------------------------------------------------------------------------------------------------------------


def _build_xdc(panel: Panel, title: str) -> str:
    spec = json.dumps(panel.spec(), ensure_ascii=False).replace("</", "<\\/")
    with open(_TEMPLATE, "r", encoding="utf-8") as fh:
        page = fh.read().replace("/*SPEC*/", spec)
    d = tempfile.mkdtemp(prefix="vector-panel-")
    _tmpdirs.append(d)
    path = os.path.join(d, "panel.xdc")
    safe_title = (title or "Panel").replace('"', "'").replace("\n", " ")[:60]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("index.html", page)
        z.writestr("manifest.toml", f'name = "{safe_title}"\nid = "{APP_ID}"\nversion = "1.0.0"\n')
        for name, data in panel.assets.items():
            z.writestr("assets/" + name, data)
    return path


async def _handle_session(session: "XdcSession") -> None:
    state = session._state
    panel: Optional[Panel] = state._panels.get(session.app.message_id)
    if panel is None:
        return  # a panel from before this bot restarted: the app still shows its baked-in first render
    panel.sessions.add(session)
    try:
        await session.send_json({"t": "render", "spec": panel.spec()})
        async for ev in session:
            await panel._on_event(session, ev)
    finally:
        panel.sessions.discard(session)


def _ensure_handler(client: Any) -> None:
    if getattr(client, "_xdc_ui_ready", False):
        return
    client._xdc_ui_ready = True
    client._register_xdc(APP_ID, _handle_session, dict(join_when="opened", idle_timeout=600.0, quiet_timeout=1800.0,
                                                        max_sessions=64, max_per_chat=16, by_hash=False), None)


async def send_panel(destination: Any, *, content: Optional[Any], embeds: Sequence[Any], files: Sequence[Any],
                     view: Any, delete_after: Optional[float] = None, theme: Any = None) -> "Message":
    """Post a Mini App panel carrying ``content``/``embeds`` and ``view``. Used by ``Messageable.send(xdc=…)``.

    ``theme``: a theme name, :class:`Theme`, dict of CSS variables, or ``True``/``None`` for the client's ``ui_theme``."""
    state = destination._state
    client = state.client
    _ensure_handler(client)

    wanted = {n for e in embeds for n in e.attachment_names()}
    assets: Dict[str, bytes] = {}
    leftovers: List[Any] = []
    for f in files:
        if f.filename in wanted:
            assets[_safe_name(f.filename)] = f.read()
        else:
            leftovers.append(f)
    # the app serves bundled files from assets/<name>; rewrite the references to match
    embeds = [_with_assets(e, assets) for e in embeds]

    resolved = get_theme(theme, default=getattr(client, "_ui_theme", "vector"))
    panel = Panel(state, content=None if content is None else str(content), embeds=embeds, view=view, assets=assets,
                  theme=resolved)
    path = _build_xdc(panel, _text_of(embeds, panel.content))
    app = await destination.send_xdc(path)
    panel.message_id = app.message_id
    panel.channel = destination
    state._panels[app.message_id] = panel
    message = await app.fetch_message()
    panel.message = message or destination.get_partial_message(app.message_id)

    if view is not None:
        view._xdc_panel = panel
        await view._start(panel.message, add_reactions=False)
    for f in leftovers:
        await destination.send(file=f)
    if delete_after is not None and message is not None:
        asyncio.ensure_future(message.delete(delay=delete_after))
    return panel.message


def _with_assets(embed: Any, assets: Dict[str, bytes]) -> Any:
    import copy

    e = copy.copy(embed)
    for layer in ("_image", "_thumbnail"):
        data = dict(getattr(e, layer, {}) or {})
        url = data.get("url", "")
        if url.startswith("attachment://"):
            data["url"] = "attachment://" + _safe_name(url[len("attachment://"):])
            setattr(e, layer, data)
    return e
