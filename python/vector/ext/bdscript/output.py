"""Turns a finished :class:`Response` into Vector messages (text, embeds, buttons, menus, reactions)."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, List, Optional

from .context import ButtonSpec, Context, SelectSpec

log = logging.getLogger("vector.bdscript")

_STYLES = {"primary": 1, "blurple": 1, "secondary": 2, "grey": 2, "gray": 2, "success": 3, "green": 3,
           "danger": 4, "red": 4, "link": 5, "url": 5}
_LINK = re.compile(r"https?://\S+")


def build_view(ctx: Context, rows: List[List[Any]]) -> Any:
    """Buttons and select menus from ``$addButton``/``$newSelectMenu`` as a reaction ``View``. Clicks run the bot's
    ``$onInteraction`` handlers (or ``on_interaction`` commands) with ``$customID`` set."""
    from ... import ui

    bot = ctx.bot
    if not any(rows):
        return None
    view = ui.View(timeout=None)
    for r, row in enumerate(rows):
        for spec in row:
            if isinstance(spec, ButtonSpec):
                b = ui.Button(label=spec.label or None, style=_STYLES.get(spec.style.lower(), 2), disabled=spec.disabled,
                              emoji=spec.emoji or None, url=spec.url, custom_id=None if spec.url else spec.custom_id)
                if not spec.url:
                    async def on_click(interaction: Any, cid: str = spec.custom_id) -> None:
                        await bot.dispatch_interaction(cid, interaction)
                    b.callback = on_click
                view.add_item(b)
            elif isinstance(spec, SelectSpec):
                s = ui.Select(custom_id=spec.custom_id, placeholder=spec.placeholder or None,
                              min_values=spec.min_values, max_values=spec.max_values, disabled=spec.disabled)
                for o in spec.options:
                    s.add_option(label=o["label"], value=o.get("value") or o["label"], description=o.get("description"),
                                 emoji=o.get("emoji") or None, default=o.get("default", False))

                async def on_select(interaction: Any, cid: str = spec.custom_id, sel: Any = s) -> None:
                    await bot.dispatch_interaction(cid, interaction, values=list(sel.values))
                s.callback = on_select
                view.add_item(s)
    view.bdscript_rows = rows  # so $editButton/$removeButtons can rebuild it
    return view


def _apply_text_options(ctx: Context, text: str) -> str:
    resp = ctx.response
    if resp.remove_links:
        text = _LINK.sub("", text)
    return text


async def send_response(ctx: Context, text: str) -> Optional[Any]:
    resp = ctx.response
    if resp.suppress:
        return None
    text = _apply_text_options(ctx, text)
    embeds = [e for _, e in sorted(resp.embeds.items()) if not _empty_embed(e)]
    view = build_view(ctx, resp.rows)
    msg = None

    # interaction replies (buttons, menus, slash): reply to the interaction
    if ctx.interaction is not None and (text or embeds or view or resp.files or resp.modal):
        msg = await _reply_interaction(ctx, text, embeds, view)
    elif text or embeds or resp.files:
        channel = ctx.channel
        dms = ctx.extras.get("dm_targets")
        if dms:
            for uid in dms:
                u = ctx.client.get_user(uid.strip().strip("<@!>"))
                if u is not None:
                    msg = await u.send(text or None, embeds=embeds or None, files=resp.files or None)
            return msg
        if resp.channel_id:
            channel = ctx.client.get_channel(resp.channel_id) or channel
        if channel is None:
            return None
        if resp.mention_author and ctx.author is not None and text and resp.reply_to is None and ctx.message is not None \
                and not getattr(ctx.command, "is_event", False):
            text = f"{ctx.author.mention} {text}"
        reference = None
        if resp.reply_to:
            reference = await _fetch(ctx, channel, resp.reply_to)
        msg = await channel.send(text or None, embeds=embeds or None, files=resp.files or None, view=view,
                                 reference=reference, delete_after=resp.delete_after, tts=resp.tts, expires_in=resp.expires_in,
                                 mention_author=resp.reply_mention)
    elif view is not None and ctx.channel is not None:
        msg = await ctx.channel.send("​", view=view)

    if msg is not None:
        ctx.sent_ids.append(str(msg.id))
        if view is not None and hasattr(ctx.bot, "remember_view"):
            ctx.bot.remember_view(str(msg.id), view)
        waits = ctx.extras.get("await_reactions")
        if waits and hasattr(ctx.bot, "_reaction_waits"):
            ctx.bot._reaction_waits[str(msg.id)] = {"user": ctx.author_id, "map": waits}
        for uid in ctx.extras.get("dm_targets") or []:
            pass
        for r in resp.reactions:
            try:
                await msg.add_reaction(r)
            except Exception as e:  # unknown emoji etc. shouldn't kill the reply
                log.warning("add reaction %s failed: %s", r, e)
    if ctx.message is not None:
        for r in resp.cmd_reactions:
            try:
                await ctx.message.add_reaction(r)
            except Exception as e:
                log.warning("add reaction %s failed: %s", r, e)
        if resp.delete_command_after is not None:
            asyncio.ensure_future(_delete_later(ctx.message, resp.delete_command_after))
    return msg


async def _reply_interaction(ctx: Context, text: str, embeds: List[Any], view: Any) -> Any:
    resp = ctx.response
    inter = ctx.interaction
    if resp.modal is not None:
        await inter.response.send_modal(ctx.bot._build_modal(ctx, resp.modal))
        return None
    if resp.edit_target == "interaction" and inter.message is not None:
        return await inter.response.edit_message(content=text or None, embeds=embeds or None, view=view)
    return await inter.response.send_message(text or None, embeds=embeds or None, view=view,
                                             ephemeral=resp.ephemeral, files=resp.files or None)


async def _fetch(ctx: Context, channel: Any, message_id: str) -> Any:
    try:
        return await channel.fetch_message(message_id)
    except Exception:
        return None


async def _delete_later(message: Any, seconds: float) -> None:
    await asyncio.sleep(seconds)
    try:
        await message.delete()
    except Exception:
        pass


def _empty_embed(e: Any) -> bool:
    d = e.to_dict()
    return not any(d.get(k) for k in ("title", "description", "fields", "image", "thumbnail", "author", "footer"))
