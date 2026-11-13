"""Sending, editing, deleting, reactions, DMs, emoji, tickets, threads, webhooks."""

from __future__ import annotations

import asyncio
import datetime

from ..parser import escape, unescape
from ..registry import BDScriptError, StopExecution, fn
from ..util import get_channel, get_member, get_user, seconds, strip_mention, to_int, truthy
from .embeds import colour_value


def _out(ctx, text: str) -> str:
    from ..interpreter import clean_output
    return clean_output(text, ctx)


async def _target_msg(ctx, cid, mid):
    if mid.strip():
        return await get_channel(ctx, cid).fetch_message(mid)
    if ctx.message is None:
        raise BDScriptError("no message here; give a channel and message ID")
    return ctx.message


@fn("sendMessage", brackets="required", lazy=True)
async def _sendmessage(ctx, node, args):
    """BDFD ``$sendMessage[text;(return ID?)]``; D.js-BDscript bare ``$sendMessage`` sends what's built so far."""
    from ..interpreter import evaluate
    text = await evaluate(ctx, args[0]) if args else ""
    ret = await evaluate(ctx, args[1]) if len(args) > 1 else "no"
    msg = await ctx.channel.send(_out(ctx, text) or "​")
    return str(msg.id) if truthy(ret) else ""


@fn("channelSendMessage", min_args=2, brackets="required")
async def _channelsend(ctx, cid, *text):
    await get_channel(ctx, cid).send(_out(ctx, ";".join(text)) or "​")
    return ""


@fn("reply", brackets="optional")
def _reply(ctx, cid_or_mention="", mid=""):
    """``$reply`` replies to the triggering message; ``$reply[channel;message]`` to another one.
    D.js-BDscript: ``$reply[yes/no]`` sets whether the reply pings."""
    r = ctx.response
    if mid.strip():
        r.channel_id = str(get_channel(ctx, cid_or_mention).id)
        r.reply_to = mid.strip()
    else:
        if cid_or_mention.strip().lower() in ("yes", "no", "true", "false"):
            r.reply_mention = truthy(cid_or_mention)
        r.reply_to = str(ctx.message.id) if ctx.message is not None else None
    r.mention_author = False
    return ""


fn("replyComplex")(_reply)


@fn("replyIn", min_args=1, brackets="required")
async def _replyin(ctx, duration):
    await asyncio.sleep(min(seconds(duration), 3600))
    return ""


@fn("editMessage", min_args=3, brackets="required")
async def _editmessage(ctx, cid, mid, content, title="", description="", color="", footer=""):
    from ....embeds import Embed
    msg = await get_channel(ctx, cid).fetch_message(mid)
    kw = {"content": _out(ctx, content) or None}
    if title or description or color or footer:
        e = Embed(title=title or None, description=description or None)
        if color:
            e.colour = colour_value(color)
        if footer:
            e.set_footer(text=footer)
        kw["embed"] = e
    await msg.edit(**kw)
    return ""


@fn("editIn", min_args=2, brackets="required")
def _editin(ctx, duration, *text):
    delay = seconds(duration)
    new = _out(ctx, ";".join(text))

    async def later():
        await asyncio.sleep(delay)
        for mid in ctx.sent_ids[:1]:
            try:
                await (await ctx.channel.fetch_message(mid)).edit(content=new)
            except Exception:
                pass
    ctx.bot.later(later())
    return ""


@fn("deleteMessage", min_args=2, brackets="required")
async def _deletemessage(ctx, cid, mid):
    msg = await get_channel(ctx, cid).fetch_message(mid)
    await msg.delete()
    return ""


@fn("deleteIn", min_args=1, brackets="required")
def _deletein(ctx, duration):
    ctx.response.delete_after = seconds(duration)
    return ""


@fn("deletecommand", brackets="optional")
def _deletecommand(ctx, duration=""):
    ctx.response.delete_command_after = seconds(duration) if duration.strip() else 0
    return ""


@fn("dm")
@fn("dmComplex")
def _dm(ctx, *uids):
    """Send the response to users' DMs instead of the channel."""
    targets = [u for u in uids if u.strip()] or [ctx.author_id]
    ctx.extras["dm_targets"] = targets
    return ""


@fn("sendDM", min_args=2, brackets="required")
async def _senddm(ctx, uid, *text):
    await get_user(ctx, uid).send(_out(ctx, ";".join(text)) or "\u200b")
    return ""


@fn("getMessage", min_args=2, brackets="required")
async def _getmessage(ctx, cid, mid, prop="content"):
    msg = await get_channel(ctx, cid).fetch_message(mid)
    p = prop.strip().lower() or "content"
    table = {"content": lambda: msg.content, "authorid": lambda: str(msg.author.id), "username": lambda: msg.author.name,
             "avatar": lambda: str(getattr(msg.author, "display_avatar", "") or ""),
             "timestamp": lambda: str(int(msg.created_at.timestamp())) if msg.created_at else ""}
    if p not in table:
        raise BDScriptError(f"invalid property '{prop}' (content/authorID/username/avatar/timestamp)")
    return escape(table[p]() or "")


@fn("pinMessage")
@fn("pinMessageComplex")
async def _pin(ctx, cid="", mid=""):
    msg = await _target_msg(ctx, cid, mid)
    await msg.pin()
    return ""


@fn("unpinMessage", min_args=0)
async def _unpin(ctx, cid="", mid=""):
    msg = await _target_msg(ctx, cid, mid)
    await msg.unpin()
    return ""


@fn("publishMessage", status="noop", note="no announcement channels on Vector")
def _publish(ctx, *a):
    return ""


@fn("addReactions", min_args=1, brackets="required")
def _addreactions(ctx, *emojis):
    ctx.response.reactions += [e.strip() for e in emojis if e.strip()]
    return ""


@fn("addCmdReactions", min_args=1, brackets="required")
def _addcmdreactions(ctx, *emojis):
    ctx.response.cmd_reactions += [e.strip() for e in emojis if e.strip()]
    return ""


@fn("addMessageReactions", min_args=3, brackets="required")
async def _addmsgreactions(ctx, cid, mid, *emojis):
    msg = await get_channel(ctx, cid).fetch_message(mid)
    for e in emojis:
        if e.strip():
            await msg.add_reaction(e.strip())
    return ""


@fn("clearReactions", min_args=2, brackets="required")
async def _clearreactions(ctx, cid, mid, emoji=""):
    msg = await get_channel(ctx, cid).fetch_message(mid)
    for r in list(getattr(msg, "reactions", [])):
        if not emoji.strip() or str(r.emoji) == emoji.strip():
            try:
                await r.clear()
            except Exception:
                await msg.remove_reaction(r.emoji, ctx.client.user)
    return ""


@fn("getReactions", min_args=2, brackets="required")
async def _getreactions(ctx, cid, mid, sep=", ", emoji="", option="ids"):
    msg = await get_channel(ctx, cid).fetch_message(mid)
    out = []
    for r in getattr(msg, "reactions", []):
        if emoji.strip() and str(r.emoji) != emoji.strip():
            continue
        if emoji.strip():
            async for u in r.users():
                out.append(str(u.id) if option != "names" else u.name)
        else:
            out.append(f"{r.emoji} {r.count}")
    return (sep or ", ").join(out)


@fn("userReacted", min_args=4, brackets="required")
async def _userreacted(ctx, cid, mid, uid, emoji):
    msg = await get_channel(ctx, cid).fetch_message(mid)
    target = strip_mention(uid)
    for r in getattr(msg, "reactions", []):
        if str(r.emoji) == emoji.strip():
            async for u in r.users():
                if str(u.id) == target:
                    return True
    return False


@fn("messageID", brackets="none")
def _messageid(ctx):
    m = ctx.message
    return str(m.id) if m is not None else ""


@fn("lastMessageID")
def _lastmessageid(ctx, cid=""):
    c = get_channel(ctx, cid)
    lm = getattr(c, "last_message", None)
    if lm is not None:
        return str(lm.id)
    return ctx.sent_ids[-1] if ctx.sent_ids else ""


@fn("repliedMessageID")
@fn("repliedMessageIDComplex")
async def _repliedid(ctx, cid="", mid=""):
    msg = await _target_msg(ctx, cid, mid)
    ref = getattr(msg, "reference", None)
    return str(getattr(ref, "message_id", "") or "")


@fn("isMessageEdited", min_args=2, brackets="required")
async def _isedited(ctx, cid, mid):
    msg = await get_channel(ctx, cid).fetch_message(mid)
    return getattr(msg, "edited_at", None) is not None


@fn("messageEditedTimestamp", min_args=2, brackets="required")
async def _editedts(ctx, cid, mid):
    msg = await get_channel(ctx, cid).fetch_message(mid)
    e = getattr(msg, "edited_at", None)
    return str(int(e.timestamp())) if e else ""


@fn("getAttachments")
def _getattachments(ctx, index=""):
    atts = list(getattr(ctx.message, "attachments", []) or [])
    if not index.strip():
        return ", ".join(a.url for a in atts)
    i = to_int(index)
    return atts[i - 1].url if 0 < i <= len(atts) else ""


@fn("botTyping", brackets="none")
async def _typing(ctx):
    trig = getattr(ctx.channel, "trigger_typing", None) or getattr(ctx.channel, "typing", None)
    if trig is not None:
        try:
            r = trig()
            if asyncio.iscoroutine(r):
                await r
        except Exception:
            pass
    return ""


# -- emoji -------------------------------------------------------------------------------------------------
@fn("addEmoji", min_args=2, brackets="required", status="partial", note="adds to the bot's own emoji pack")
async def _addemoji(ctx, name, url, return_emoji="no"):
    add = getattr(ctx.client, "add_pack_emoji", None)
    if add is None:
        raise BDScriptError("this SDK build can't add emoji yet")
    await add(name, url)
    return f":{name}:" if truthy(return_emoji) else ""


@fn("removeEmoji", min_args=1, brackets="required", status="partial")
async def _removeemoji(ctx, eid):
    rm = getattr(ctx.client, "remove_pack_emoji", None)
    if rm is None:
        raise BDScriptError("this SDK build can't remove emoji yet")
    await rm(eid.strip(":"))
    return ""


@fn("emojiExists", min_args=1, brackets="required")
def _emojiexists(ctx, eid):
    return ctx.client.get_emoji(eid) is not None


@fn("emojiName", min_args=1, brackets="required")
def _emojiname(ctx, eid):
    e = ctx.client.get_emoji(eid)
    return e.name if e else ""


@fn("customEmoji", min_args=1, brackets="required")
def _customemoji(ctx, name, *a):
    e = ctx.client.get_emoji(name)
    if e is None:
        raise BDScriptError(f"emoji '{name}' not found; equip its pack with subscribe_emoji_pack()")
    return str(e)


@fn("isEmojiAnimated", min_args=1, brackets="required")
def _isanimated(ctx, eid):
    e = ctx.client.get_emoji(eid)
    return bool(getattr(e, "animated", False)) if e else False


# -- tickets -----------------------------------------------------------------------------------------------
@fn("newTicket", min_args=1, brackets="required")
async def _newticket(ctx, category, no_question="", in_ticket="", to_user="", error="", number="", return_id="no"):
    g = ctx.guild
    if g is None:
        raise BDScriptError("tickets only work in a community")
    cat = g.get_category(category.strip()) or next((c for c in g.categories if c.name.lower() == category.strip().lower()), None)
    if cat is None:
        raise StopExecution(error or f"category '{category}' not found")
    question = " ".join(ctx.args)
    if not question and no_question:
        raise StopExecution(no_question)
    name = f"ticket-{number or ctx.author.name}".lower().replace(" ", "-")[:90]
    ch = await g.create_text_channel(name, category=cat, private=True)
    try:
        await ch.grant_access(ctx.author)
    except Exception:
        pass
    ctx.bot.tickets.add(str(ch.id))
    msg = await ch.send(_out(ctx, (in_ticket or "").replace("$question", question)) or f"Ticket by {ctx.author.mention}: {question}")
    if to_user:
        ctx.response.mention_author = False
        await ctx.channel.send(_out(ctx, to_user))
    return str(msg.id) if truthy(return_id) else ""


@fn("closeTicket", brackets="optional")
async def _closeticket(ctx, error=""):
    if ctx.channel_id not in ctx.bot.tickets:
        raise StopExecution(error or "This channel isn't a ticket.")
    ctx.bot.tickets.discard(ctx.channel_id)
    ctx.response.suppress = True
    await ctx.channel.delete()
    return ""


@fn("isTicket")
def _isticket(ctx, cid=""):
    return str(get_channel(ctx, cid).id) in ctx.bot.tickets


# -- threads (Vector has no threads: a thread becomes a channel in the same category) ------------------------
@fn("startThread", min_args=1, brackets="required", status="partial", note="creates a channel next to the parent")
async def _startthread(ctx, name, cid="", mid="", archive="", return_id="no"):
    parent = get_channel(ctx, cid)
    g = getattr(parent, "guild", None) or ctx.guild
    if g is None:
        raise BDScriptError("threads need a community")
    ch = await g.create_text_channel(name, category=getattr(parent, "category", None))
    ctx.bot.threads[str(ch.id)] = {"parent": str(parent.id), "members": set()}
    return str(ch.id) if truthy(return_id) else ""


@fn("editThread", min_args=1, brackets="required", status="partial")
async def _editthread(ctx, tid, name="", archived="", archive="", locked="", slowmode=""):
    ch = get_channel(ctx, tid)
    kw = {}
    if name:
        kw["name"] = name
    if locked.strip():
        kw["read_only"] = truthy(locked)
    if kw:
        await ch.edit(**kw)
    return ""


@fn("threadAddMember", min_args=2, brackets="required", status="partial")
async def _threadadd(ctx, tid, uid):
    ctx.bot.threads.setdefault(strip_mention(tid), {"members": set()})["members"].add(strip_mention(uid))
    return ""


@fn("threadRemoveMember", min_args=2, brackets="required", status="partial")
async def _threadremove(ctx, tid, uid):
    ctx.bot.threads.setdefault(strip_mention(tid), {"members": set()})["members"].discard(strip_mention(uid))
    return ""


@fn("threadMessageCount", brackets="optional", status="partial")
def _threadmsgs(ctx, tid=""):
    return str(ctx.bot.message_counts.get(str(get_channel(ctx, tid).id), 0))


@fn("threadUserCount", brackets="optional", status="partial")
def _threadusers(ctx, tid=""):
    t = ctx.bot.threads.get(str(get_channel(ctx, tid).id))
    return str(len(t["members"])) if t else "0"


# -- webhooks (vector.Webhook) -----------------------------------------------------------------------------
def _hook(ctx, url):
    from ....webhook import Webhook
    return Webhook.from_url(url.strip(), client=ctx.client)


def _pending(ctx, url):
    return ctx.extras.setdefault("webhooks", {}).setdefault(url.strip(), {"content": "", "embed": {}, "username": None})


@fn("webhookCreate", min_args=2, brackets="required")
async def _webhookcreate(ctx, cid, username, avatar=""):
    wh = await get_channel(ctx, cid).create_webhook(name=username)
    return wh.url


@fn("webhookSend", min_args=1, brackets="required")
async def _webhooksend(ctx, url, content="", title="", title_url="", description="", color="", author="",
                       author_icon="", footer="", footer_icon="", thumbnail="", image="", add_ts="no"):
    from ....embeds import Embed
    p = _pending(ctx, url)
    content = content or p["content"]
    pe = p["embed"]
    title, description, color, footer = title or pe.get("title", ""), description or pe.get("description", ""), \
        color or pe.get("color", ""), footer or pe.get("footer", "")
    e = None
    if title or description or footer or image or thumbnail or author:
        e = Embed(title=title or None, url=title_url or None, description=description or None)
        if color:
            e.colour = colour_value(color)
        if author:
            e.set_author(name=author, icon_url=author_icon or None)
        if footer:
            e.set_footer(text=footer, icon_url=footer_icon or None)
        if thumbnail:
            e.set_thumbnail(url=thumbnail)
        if image:
            e.set_image(url=image)
        if truthy(add_ts):
            e.timestamp = datetime.datetime.now(datetime.timezone.utc)
    await _hook(ctx, url).send(content or None, embed=e, username=p["username"])
    ctx.extras.get("webhooks", {}).pop(url.strip(), None)
    return ""


@fn("webhookDelete", min_args=1, brackets="required")
async def _webhookdelete(ctx, url):
    await _hook(ctx, url).delete()
    return ""


@fn("webhookContent", min_args=2, brackets="required")
def _whcontent(ctx, url, *text):
    _pending(ctx, url)["content"] = ";".join(text)
    return ""


def _whembed(key):
    def impl(ctx, url, *text):
        _pending(ctx, url)["embed"][key] = ";".join(text)
        return ""
    return impl


fn("webhookTitle", min_args=2, brackets="required")(_whembed("title"))
fn("webhookDescription", min_args=2, brackets="required")(_whembed("description"))
fn("webhookColor", min_args=2, brackets="required")(_whembed("color"))
fn("webhookFooter", min_args=2, brackets="required")(_whembed("footer"))


@fn("webhookUsername", min_args=2, brackets="required")
def _whusername(ctx, url, name):
    _pending(ctx, url)["username"] = name
    return ""


@fn("webhookAvatarURL", min_args=2, brackets="required", status="noop", note="Vector messages always use the bot's avatar")
def _whavatar(ctx, url, avatar):
    return ""
