"""Command restrictions, bot info, awaited commands, callbacks and premium functions."""

from __future__ import annotations

import asyncio
import json
import os
import random

from ..parser import escape
from ..registry import BDScriptError, StopExecution, fn
from ..util import get_channel, get_member, perm_name, strip_mention, to_int, truthy


def _split_last(args):
    """``[a;b;c;Error message]`` -> ([a,b,c], message)."""
    if len(args) <= 1:
        return list(args), ""
    return list(args[:-1]), args[-1]


def _deny(msg):
    raise StopExecution(msg or "")


# -- restrictions ------------------------------------------------------------------------------------------
@fn("onlyAdmin", brackets="optional")
def _onlyadmin(ctx, msg=""):
    m = get_member(ctx, "", required=False)
    if m is None or not (m.is_admin() if callable(getattr(m, "is_admin", None)) else m.guild_permissions.administrator):
        _deny(msg)
    return ""


@fn("onlyPerms", min_args=1, brackets="required")
def _onlyperms(ctx, *args):
    perms, msg = _split_last(args)
    m = get_member(ctx, "", required=False)
    if m is None or not all(m.can(perm_name(p)) for p in perms if p.strip()):
        _deny(msg)
    return ""


@fn("onlyBotPerms", min_args=1, brackets="required")
def _onlybotperms(ctx, *args):
    perms, msg = _split_last(args)
    me = getattr(ctx.guild, "me", None)
    if me is None or not all(me.can(perm_name(p)) for p in perms if p.strip()):
        _deny(msg)
    return ""


@fn("onlyBotChannelPerms", min_args=2, brackets="required")
def _onlybotchannelperms(ctx, cid, *args):
    perms, msg = _split_last(args)
    ch = get_channel(ctx, cid)
    me = getattr(ctx.guild, "me", None)
    if me is None:
        _deny(msg)
    p = ch.permissions_for(me) if hasattr(ch, "permissions_for") else None
    if p is None or not all(getattr(p, perm_name(x), False) for x in perms if x.strip()):
        _deny(msg)
    return ""


def _only_in(values, items, msg):
    if values not in [i.strip() for i in items if i.strip()]:
        _deny(msg)


@fn("onlyForIDs", min_args=1, brackets="required")
def _onlyforids(ctx, *args):
    ids, msg = _split_last(args)
    if ctx.author_id not in [strip_mention(i) for i in ids] and ctx.author_id not in ctx.bot.owners:
        _deny(msg)
    return ""


@fn("onlyForUsers", min_args=1, brackets="required")
def _onlyforusers(ctx, *args):
    names, msg = _split_last(args)
    if ctx.author.name not in [n.strip() for n in names]:
        _deny(msg)
    return ""


@fn("onlyForChannels", min_args=1, brackets="required")
def _onlyforchannels(ctx, *args):
    ids, msg = _split_last(args)
    if ctx.channel_id not in [strip_mention(i) for i in ids]:
        _deny(msg)
    return ""


@fn("onlyForCategories", min_args=1, brackets="required")
def _onlyforcategories(ctx, *args):
    ids, msg = _split_last(args)
    if str(getattr(ctx.channel, "category_id", "") or "") not in [i.strip() for i in ids]:
        _deny(msg)
    return ""


@fn("onlyForServers", min_args=1, brackets="required")
def _onlyforservers(ctx, *args):
    ids, msg = _split_last(args)
    if ctx.guild_id not in [i.strip() for i in ids]:
        _deny(msg)
    return ""


def _role_hit(ctx, items, by_name):
    m = get_member(ctx, "", required=False)
    if m is None:
        return False
    keys = {r.name.lower() if by_name else str(r.id) for r in m.roles}
    return any((i.strip().lower() if by_name else strip_mention(i)) in keys for i in items if i.strip())


@fn("onlyForRoles", min_args=1, brackets="required")
def _onlyforroles(ctx, *args):
    names, msg = _split_last(args)
    if not _role_hit(ctx, names, True):
        _deny(msg)
    return ""


@fn("onlyForRoleIDs", min_args=1, brackets="required")
def _onlyforroleids(ctx, *args):
    ids, msg = _split_last(args)
    if not _role_hit(ctx, ids, False):
        _deny(msg)
    return ""


@fn("onlyIfMessageContains", min_args=2, brackets="required")
def _onlyifcontains(ctx, text, *args):
    words, msg = _split_last(args)
    if not any(w in text for w in words if w):
        _deny(msg)
    return ""


@fn("onlyNSFW", brackets="optional")
def _onlynsfw(ctx, msg=""):
    if not (ctx.channel.is_nsfw() if hasattr(ctx.channel, "is_nsfw") else False):
        _deny(msg)
    return ""


@fn("blackListIDs", min_args=1, brackets="required")
def _blacklistids(ctx, *args):
    ids, msg = _split_last(args)
    if ctx.author_id in [strip_mention(i) for i in ids]:
        _deny(msg)
    return ""


@fn("blackListUsers", min_args=1, brackets="required")
def _blacklistusers(ctx, *args):
    names, msg = _split_last(args)
    if ctx.author.name in [n.strip() for n in names]:
        _deny(msg)
    return ""


@fn("blackListServers", min_args=1, brackets="required")
def _blacklistservers(ctx, *args):
    ids, msg = _split_last(args)
    if ctx.guild_id in [i.strip() for i in ids]:
        _deny(msg)
    return ""


@fn("blackListRoles", min_args=1, brackets="required")
def _blacklistroles(ctx, *args):
    names, msg = _split_last(args)
    if _role_hit(ctx, names, True):
        _deny(msg)
    return ""


@fn("blackListRolesIDs", min_args=1, brackets="required")
def _blacklistroleids(ctx, *args):
    ids, msg = _split_last(args)
    if _role_hit(ctx, ids, False):
        _deny(msg)
    return ""


@fn("ignoreChannels", min_args=1, brackets="required")
def _ignorechannels(ctx, *args):
    ids, msg = _split_last(args)
    if ctx.channel_id in [strip_mention(i) for i in ids]:
        _deny(msg)
    return ""


@fn("ignoreLinks", brackets="none")
def _ignorelinks(ctx):
    import re
    if re.search(r"https?://", " ".join(ctx.args)):
        _deny("")
    return ""


@fn("enabled", min_args=1, brackets="required")
def _enabled(ctx, value, msg=""):
    if not truthy(value, True):
        _deny(msg)
    return ""


# -- bot & command info ------------------------------------------------------------------------------------
@fn("botID", brackets="none")
def _botid(ctx):
    return str(ctx.client.user.id)


@fn("botOwnerID", brackets="optional")
def _botownerid(ctx, sep=", "):
    return (sep or ", ").join(ctx.bot.owners)


@fn("commandName", brackets="none")
def _commandname(ctx):
    return getattr(ctx.command, "name", "") or ""


@fn("commandTrigger", brackets="none")
def _commandtrigger(ctx):
    return getattr(ctx.command, "trigger", "") or getattr(ctx.command, "name", "") or ""


@fn("commandFolder", brackets="none")
def _commandfolder(ctx):
    return getattr(ctx.command, "folder", "") or ""


@fn("commandsCount", brackets="none")
def _commandscount(ctx):
    return str(len(ctx.bot.commands))


@fn("botCommands", brackets="optional")
def _botcommands(ctx, sep=", "):
    return (sep or ", ").join(c.trigger or c.name for c in ctx.bot.commands if c.kind == "message")


@fn("commandInfo", min_args=1, brackets="required")
def _commandinfo(ctx, name, prop="code"):
    """D.js-BDscript ``$commandInfo[name;property]``."""
    c = ctx.bot.get_command(name)
    if c is None:
        raise BDScriptError(f"no command '{name}'")
    v = {"code": c.code, "name": c.name, "trigger": c.trigger, "aliases": ", ".join(c.aliases), "type": c.type,
         "description": c.description, "folder": c.folder}.get(prop.strip())
    if v is None:
        raise BDScriptError(f"invalid command property '{prop}'")
    return escape(str(v or ""))


@fn("updateCommands", brackets="none")
def _updatecommands(ctx):
    ctx.bot.reload()
    return ""


@fn("shardID")
@fn("shardIDComplex")
def _shardid(ctx, *a):
    return "0"


@fn("premiumExpireTime", status="noop", note="no premium tier: everything is enabled")
@fn("hostingExpireTime", status="noop")
@fn("hostingExpireTimeComplex", status="noop")
def _expire(ctx, *a):
    return "never"


@fn("botListDescription", status="noop")
@fn("botListHide", brackets="none", status="noop")
def _botlist(ctx, *a):
    return ""


# -- awaited commands & callbacks --------------------------------------------------------------------------
@fn("awaitFunc", min_args=1, brackets="required")
def _awaitfunc(ctx, name, uid="", cid=""):
    ctx.bot.await_command(name.strip(), strip_mention(uid) or ctx.author_id, strip_mention(cid) or ctx.channel_id, ctx)
    return ""


@fn("awaitReactions", min_args=1, brackets="required")
def _awaitreactions(ctx, *pairs):
    """``$awaitReactions[cmd;emoji;cmd;emoji...]``: when the author reacts on the response, run that awaited command."""
    it = iter([p for p in pairs if p != ""])
    mapping = {}
    for cmd in it:
        try:
            emoji = next(it)
        except StopIteration:
            raise BDScriptError("each awaited command needs an emoji")
        mapping[emoji.strip()] = cmd.strip()
    ctx.extras["await_reactions"] = mapping
    ctx.response.reactions += [e for e in mapping if e not in ctx.response.reactions]
    return ""


for _n in ("onJoined", "onLeave", "onInteraction", "onInteractionComplex", "awaitedCommand", "awaitedCommandError",
           "onBanAdd", "onBanRemove", "onMessageDelete", "alwaysReply", "ignoreTriggerCase", "messageContains",
           "reaction"):
    fn(_n)(lambda ctx, *a: "")


@fn("usedEmoji", brackets="none")
def _usedemoji(ctx):
    return ctx.extras.get("emoji", "")


# -- AI (premium in BDFD; here: bring your own model) ------------------------------------------------------
async def _ai(ctx, prompt, system="", max_tokens="", history=None):
    provider = getattr(ctx.bot, "ai", None)
    if provider is None:
        raise BDScriptError("no AI provider: pass BDBot(ai=...) or set ANTHROPIC_API_KEY")
    n = to_int(max_tokens) if str(max_tokens).strip() else 512
    out = provider(prompt=prompt, system=system or None, max_tokens=n, history=history or [])
    if asyncio.iscoroutine(out):
        out = await out
    return escape(str(out))


async def _history(ctx, limit=20):
    out = []
    try:
        async for m in ctx.channel.history(limit=limit):
            role = "assistant" if str(m.author.id) == str(ctx.client.user.id) else "user"
            out.append({"role": role, "content": f"{m.author.name}: {m.content}" if role == "user" else m.content})
    except Exception:
        pass
    return list(reversed(out))


@fn("ai", min_args=1, brackets="required")
async def _ai_fn(ctx, prompt, system="", max_tokens=""):
    return await _ai(ctx, prompt, system, max_tokens)


@fn("aiWithCtx", min_args=1, brackets="required")
async def _aictx(ctx, prompt, system="", max_tokens=""):
    return await _ai(ctx, prompt, system, max_tokens, await _history(ctx))


@fn("aiAgent", min_args=1, brackets="required", status="partial", note="functions list is passed to the model as text")
async def _aiagent(ctx, prompt, system="", functions="", max_tokens=""):
    sys = (system + "\n" if system else "") + (f"You may mention these bot functions: {functions}" if functions else "")
    return await _ai(ctx, prompt, sys, max_tokens)


async def _decide(ctx, question, content="", history=None):
    ans = await _ai(ctx, (f"Content:\n{content}\n\n" if content else "") + f"Question: {question}\nAnswer only yes or no.",
                    "Answer with exactly one word: yes or no.", "5", history)
    return "true" if ans.strip().lower().startswith("y") else "false"


@fn("aiDecide", min_args=2, brackets="required")
async def _aidecide(ctx, content, question):
    return await _decide(ctx, question, content)


@fn("aiDecideWithCtx", min_args=1, brackets="required")
async def _aidecidectx(ctx, question):
    return await _decide(ctx, question, "", await _history(ctx))


@fn("aiQuota", brackets="none")
def _aiquota(ctx):
    return "unlimited"


@fn("customImage", min_args=1, brackets="required")
def _customimage(ctx, tag):
    url = ctx.bot.custom_images.get(tag.strip())
    if url is None:
        raise BDScriptError(f"no custom image '{tag}' (BDBot(custom_images={{...}}))")
    return url


@fn("sendNotification", min_args=1, brackets="required")
async def _notify(ctx, message, image=""):
    for owner in ctx.bot.owners:
        u = ctx.client.get_user(owner)
        if u is not None:
            try:
                await u.send(message + (f"\n{image}" if image else ""))
            except Exception:
                pass
    return ""
