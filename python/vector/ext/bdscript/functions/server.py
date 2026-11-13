"""Servers (Vector communities), channels, roles, moderation."""

from __future__ import annotations

import datetime
import random

from ..parser import escape
from ..registry import BDScriptError, fn
from ..util import (get_channel, get_guild, get_member, get_role, perm_name, perm_names, seconds, strip_mention,
                    to_int, truthy)
from .embeds import colour_value


def _g(ctx, gid=""):
    return get_guild(ctx, gid)


# -- servers -----------------------------------------------------------------------------------------------
@fn("serverName")
def _servername(ctx, gid=""):
    return escape(_g(ctx, gid).name or "")


@fn("guildID")
@fn("guildIDComplex")
def _guildid(ctx, name=""):
    if not name.strip():
        return ctx.guild_id
    for g in ctx.client.communities:
        if g.name == name or (g.name or "").lower() == name.strip().lower():
            return str(g.id)
    return ""


@fn("serverIcon")
@fn("serverIconComplex")
def _servericon(ctx, gid="", *a):
    g = _g(ctx, gid)
    u = getattr(g, "icon_url", None)
    return str(u) if u else ""


@fn("serverOwner")
@fn("serverOwnerComplex")
def _serverowner(ctx, gid=""):
    return str(_g(ctx, gid).owner_id or "")


@fn("membersCount")
@fn("membersCountComplex")
@fn("allMembersCount")
def _memberscount(ctx, gid_or_presence="", *a):
    g = ctx.guild
    if gid_or_presence and gid_or_presence.lower() not in ("online", "idle", "dnd", "offline", "invisible"):
        g = _g(ctx, gid_or_presence)
    if g is None:
        return str(sum(c.member_count for c in ctx.client.communities))
    return str(g.member_count)


@fn("roleCount")
def _rolecount(ctx, gid=""):
    return str(len([r for r in _g(ctx, gid).roles if not r.is_default()]))


@fn("channelCount")
def _channelcount(ctx, gid=""):
    return str(len(_g(ctx, gid).channels))


@fn("categoryCount")
@fn("categoryCountComplex")
def _categorycount(ctx, gid=""):
    return str(len(_g(ctx, gid).categories))


@fn("serverInfo")
def _serverinfo(ctx, msg="", thumb="yes"):
    g = _g(ctx)
    e = ctx.response.embed(1)
    e.title = g.name
    e.add_field(name="Owner", value=str(g.owner_id or "?"), inline=True)
    e.add_field(name="Members", value=str(g.member_count), inline=True)
    e.add_field(name="Channels", value=str(len(g.channels)), inline=True)
    e.add_field(name="Roles", value=str(len(g.roles)), inline=True)
    if msg:
        e.description = msg
    return ""


@fn("serverDescription")
@fn("serverDescriptionComplex")
def _serverdescription(ctx, gid=""):
    return escape(_g(ctx, gid).description or "")


@fn("serverRegion", status="noop", note="Vector has relays instead of regions")
def _region(ctx, *a):
    return "nostr"


@fn("serverVerificationLvl", status="noop")
def _verif(ctx, *a):
    return "none"


@fn("boostCount", status="noop", note="no boosts on Vector")
@fn("boostCountComplex", status="noop")
@fn("boostLevel", status="noop")
def _boosts(ctx, *a):
    return "0"


@fn("guildBanner")
def _guildbanner(ctx, gid=""):
    u = getattr(_g(ctx, gid), "banner_url", None)
    return str(u) if u else ""


@fn("afkChannelID", status="noop")
@fn("afkTimeout", status="noop")
@fn("rulesChannelID", status="noop")
def _afk(ctx, *a):
    return ""


@fn("systemChannelID")
def _systemchannel(ctx, gid=""):
    c = _g(ctx, gid).system_channel
    return str(c.id) if c else ""


@fn("serverEmojis")
def _serveremojis(ctx, gid="", sep=", "):
    return (sep or ", ").join(str(e) for e in _g(ctx, gid).emojis)


@fn("emoteCount", brackets="optional")
def _emotecount(ctx, gid=""):
    return str(len(_g(ctx, gid).emojis))


@fn("serverChannelExists", min_args=1, brackets="required")
@fn("channelExists", min_args=1, brackets="required")
def _channelexists(ctx, cid):
    return get_channel(ctx, cid, required=False) is not None


@fn("guildExists", min_args=1, brackets="required")
def _guildexists(ctx, gid):
    return ctx.client.get_community(gid.strip()) is not None


@fn("serverCount", brackets="none")
def _servercount(ctx):
    return str(len(ctx.client.communities))


@fn("serverNames")
@fn("serverNamesComplex")
def _servernames(ctx, amount="", sep=", "):
    names = [g.name for g in ctx.client.communities]
    n = to_int(amount) if amount.strip() else len(names)
    return (sep or ", ").join(names[:n])


@fn("randomGuildID", brackets="none")
def _randomguild(ctx):
    gs = ctx.client.communities
    return str(random.choice(gs).id) if gs else ""


@fn("botLeave")
@fn("botLeaveComplex")
async def _botleave(ctx, gid=""):
    await _g(ctx, gid).leave()
    return ""


@fn("getServerInvite")
@fn("getServerInviteComplex")
async def _serverinvite(ctx, gid="", *a):
    inv = await _g(ctx, gid).create_invite()
    return str(getattr(inv, "url", inv))


@fn("getInviteInfo", min_args=2, brackets="required")
async def _inviteinfo(ctx, code, prop):
    inv = await ctx.client.fetch_invite(code)
    p = prop.strip().lower()
    table = {"guildid": lambda: str(getattr(inv.guild, "id", "")), "guildname": lambda: getattr(inv.guild, "name", ""),
             "code": lambda: getattr(inv, "code", code), "url": lambda: getattr(inv, "url", ""),
             "inviterid": lambda: str(getattr(getattr(inv, "inviter", None), "id", "")),
             "uses": lambda: str(getattr(inv, "uses", 0) or 0), "maxuses": lambda: str(getattr(inv, "max_uses", 0) or 0)}
    if p not in table:
        raise BDScriptError(f"invalid invite property '{prop}'")
    return escape(table[p]())


@fn("getBotInvite", brackets="none")
def _botinvite(ctx):
    return f"https://vectorapp.io/u/{ctx.client.npub}"


# -- channels ----------------------------------------------------------------------------------------------
@fn("channelID")
@fn("channelIDComplex")
@fn("channelIDFromName", min_args=1)
def _channelid(ctx, name=""):
    if not name.strip():
        return ctx.channel_id
    g = _g(ctx)
    c = next((c for c in g.channels if c.name == name.strip() or c.name.lower() == name.strip().lower()), None)
    return str(c.id) if c else ""


@fn("channelName")
def _channelname(ctx, cid=""):
    c = get_channel(ctx, cid)
    return escape(getattr(c, "name", None) or "DM")


@fn("channelNames")
def _channelnames(ctx, sep=", ", gid=""):
    return (sep or ", ").join(c.name for c in _g(ctx, gid).channels)


@fn("channelPosition")
@fn("channelPositionComplex")
def _channelposition(ctx, cid=""):
    return str(getattr(get_channel(ctx, cid), "position", 0))


@fn("channelTopic")
@fn("channelTopicComplex")
def _channeltopic(ctx, cid=""):
    return escape(getattr(get_channel(ctx, cid), "topic", None) or "")


@fn("channelType")
def _channeltype(ctx, cid=""):
    c = get_channel(ctx, cid)
    t = type(c).__name__
    return {"TextChannel": "text", "VoiceChannel": "voice", "CategoryChannel": "category", "DMChannel": "dm",
            "ForumChannel": "forum"}.get(t, "text")


@fn("categoryChannels", min_args=1, brackets="required")
def _categorychannels(ctx, cat, sep=", ", option="ids"):
    g = _g(ctx)
    c = g.get_category(strip_mention(cat)) if hasattr(g, "get_category") else None
    if c is None:
        raise BDScriptError(f"invalid category '{cat}'")
    if option.strip().lower() in ("names", "name"):
        return (sep or ", ").join(x.name for x in c.channels)
    if option.strip().lower() == "count":
        return str(len(c.channels))
    return (sep or ", ").join(str(x.id) for x in c.channels)


@fn("categoryID", min_args=1, brackets="required")
def _categoryid(ctx, name):
    c = next((c for c in _g(ctx).categories if c.name.lower() == name.strip().lower()), None)
    return str(c.id) if c else ""


@fn("parentID")
@fn("parentIDComplex")
def _parentid(ctx, cid=""):
    c = get_channel(ctx, cid)
    return str(getattr(c, "category_id", None) or "")


@fn("createChannel", min_args=2, brackets="required")
async def _createchannel(ctx, name, kind, category="", return_id="no"):
    g = _g(ctx)
    cat = g.get_category(category.strip()) if category.strip() else None
    k = kind.strip().lower()
    if k in ("text", "chat"):
        c = await g.create_text_channel(name, category=cat)
    elif k == "voice":
        c = await g.create_voice_channel(name, category=cat)
    elif k == "category":
        c = await g.create_category(name)
    elif k == "forum":
        c = await g.create_forum(name, category=cat)
    else:
        raise BDScriptError(f"invalid channel type '{kind}' (text/voice/category/forum)")
    ctx.extras["last_channel_id"] = str(c.id)
    return str(c.id) if truthy(return_id) else ""


@fn("deleteChannels", min_args=1, brackets="required")
async def _deletechannels(ctx, *cids):
    for cid in cids:
        await get_channel(ctx, cid).delete()
    return ""


@fn("deleteChannelsByName", min_args=1, brackets="required")
async def _deletebyname(ctx, *names):
    g = _g(ctx)
    for n in names:
        for c in [c for c in g.channels if c.name == n]:
            await c.delete()
    return ""


@fn("modifyChannel", min_args=1, brackets="required")
async def _modifychannel(ctx, cid, name="", topic="", nsfw="", position="", category=""):
    c = get_channel(ctx, cid)
    if not hasattr(c, "edit"):
        raise BDScriptError(f"'{cid}' isn't a community channel")
    kw = {}
    if name:
        kw["name"] = name
    if topic:
        kw["topic"] = topic
    if position.strip():
        kw["position"] = to_int(position)
    if category.strip():
        kw["category"] = _g(ctx).get_category(category.strip())
    await c.edit(**kw)
    return ""


def _parse_perm_list(items):
    allow, deny = {}, {}
    for p in items:
        p = p.strip()
        if not p:
            continue
        sign = p[0]
        name = perm_name(p[1:] if sign in "+-/" else p)
        if sign == "-":
            deny[name] = False
        elif sign == "/":
            allow[name] = None
        else:
            allow[name] = True
    return {**allow, **deny}


def _target(ctx, tid):
    g = _g(ctx)
    t = strip_mention(tid)
    return g.get_role(t) or g.get_member(t) or (g.default_role if t == str(g.id) or t.lower() == "everyone" else None)


@fn("modifyChannelPerms", min_args=3, brackets="required")
async def _modifychannelperms(ctx, cid, *rest):
    # BDFD: $modifyChannelPerms[channel;perms...;user/role] (target last)
    *perms, tid = rest
    target = _target(ctx, tid)
    if target is None:
        raise BDScriptError(f"invalid user/role '{tid}'")
    await get_channel(ctx, cid).set_permissions(target, **_parse_perm_list(perms))
    return ""


@fn("editChannelPerms", min_args=3, brackets="required")
async def _editchannelperms(ctx, cid, tid, *perms):
    target = _target(ctx, tid)
    if target is None:
        raise BDScriptError(f"invalid user/role '{tid}'")
    await get_channel(ctx, cid).set_permissions(target, **_parse_perm_list(perms))
    return ""


@fn("slowmode", min_args=2, brackets="required", status="partial", note="stored; Vector has no slowmode yet")
async def _slowmode(ctx, cid, duration):
    c = get_channel(ctx, cid)
    ctx.bot.slowmodes[str(c.id)] = int(seconds(duration)) if duration.strip() not in ("0", "") else 0
    return ""


@fn("getSlowmode")
def _getslowmode(ctx, cid=""):
    c = get_channel(ctx, cid)
    return str(ctx.bot.slowmodes.get(str(c.id), getattr(c, "slowmode_delay", 0) or 0))


@fn("isNSFW")
def _isnsfw(ctx, cid=""):
    c = get_channel(ctx, cid)
    return bool(c.is_nsfw()) if hasattr(c, "is_nsfw") else False


@fn("findChannel", min_args=1, brackets="required")
def _findchannel(ctx, query, return_current="yes"):
    q = strip_mention(query).lower()
    g = ctx.guild
    if g is not None:
        for c in g.channels:
            if str(c.id).lower() == q or c.name.lower() == q:
                return str(c.id)
        for c in g.channels:
            if q and q in c.name.lower():
                return str(c.id)
    return ctx.channel_id if truthy(return_current, True) else ""


@fn("randomChannelID", brackets="none")
@fn("'randomChannelID", brackets="none")
def _randomchannel(ctx):
    cs = _g(ctx).text_channels
    return str(random.choice(cs).id) if cs else ""


@fn("randomCategoryID")
def _randomcategory(ctx, gid=""):
    cs = _g(ctx, gid).categories
    return str(random.choice(cs).id) if cs else ""


@fn("lastPinTimestamp")
async def _lastpin(ctx, cid=""):
    pins = await get_channel(ctx, cid).pins()
    if not pins:
        return ""
    dt = getattr(pins[0], "created_at", None)
    return str(int(dt.timestamp())) if dt else ""


@fn("dmChannelID", min_args=0)
async def _dmchannelid(ctx, uid=""):
    from ..util import get_user
    dm = await get_user(ctx, uid).create_dm()
    return str(dm.id)


@fn("voiceUserLimit")
def _voicelimit(ctx, cid=""):
    return str(getattr(get_channel(ctx, cid), "user_limit", 0) or 0)


@fn("useChannel", min_args=1, brackets="required")
def _usechannel(ctx, cid):
    ctx.response.channel_id = str(get_channel(ctx, cid).id)
    return ""


# -- roles -------------------------------------------------------------------------------------------------
@fn("roleID", min_args=1, brackets="required")
def _roleid(ctx, name):
    r = get_role(ctx, name, required=False)
    return str(r.id) if r else ""


@fn("roleName", min_args=1, brackets="required")
def _rolename(ctx, rid):
    return escape(get_role(ctx, rid).name)


@fn("roleNames", brackets="optional")
def _rolenames(ctx, sep=", "):
    return (sep or ", ").join(r.name for r in _g(ctx).roles if not r.is_default())


@fn("rolePerms", min_args=1, brackets="required")
def _roleperms(ctx, *a):
    # $rolePerms[(Guild ID;)Role ID;(Separator)]
    if len(a) >= 2 and ctx.client.get_community(a[0].strip()) is not None:
        g, rid, sep = ctx.client.get_community(a[0].strip()), a[1], (a[2] if len(a) > 2 else ", ")
    else:
        g, rid, sep = ctx.guild, a[0], (a[1] if len(a) > 1 else ", ")
    return (sep or ", ").join(perm_names(get_role(ctx, rid, guild=g).permissions))


@fn("rolePosition", min_args=1, brackets="required")
def _roleposition(ctx, rid):
    return str(getattr(get_role(ctx, rid), "position", 0))


@fn("roleExists", min_args=1, brackets="required")
def _roleexists(ctx, rid):
    return get_role(ctx, rid, required=False) is not None


@fn("roleInfo", min_args=1, brackets="required")
def _roleinfo(ctx, rid, *msg):
    r = get_role(ctx, rid)
    e = ctx.response.embed(1)
    e.title = r.name
    e.add_field(name="ID", value=str(r.id), inline=True)
    e.add_field(name="Members", value=str(len(r.members)), inline=True)
    e.add_field(name="Permissions", value=", ".join(perm_names(r.permissions)) or "none", inline=False)
    return ""


@fn("getRoleColor", min_args=1, brackets="required")
def _getrolecolor(ctx, rid):
    r = get_role(ctx, rid)
    return f"{r.colour.value:06x}" if r.colour else "000000"


@fn("isHoisted", min_args=1, brackets="required")
def _ishoisted(ctx, rid):
    return bool(getattr(get_role(ctx, rid), "hoist", False))


@fn("isMentionable", min_args=1, brackets="required")
def _ismentionable(ctx, rid):
    return bool(getattr(get_role(ctx, rid), "mentionable", True))


@fn("createRole", min_args=1, brackets="required")
async def _createrole(ctx, name, color="", hoist="no", mentionable="no", return_id="no"):
    kw = {"name": name, "hoist": truthy(hoist), "mentionable": truthy(mentionable)}
    if color.strip():
        kw["colour"] = colour_value(color)
    r = await _g(ctx).create_role(**kw)
    return str(r.id) if truthy(return_id) else ""


@fn("deleteRole", min_args=1, brackets="required")
async def _deleterole(ctx, rid):
    await get_role(ctx, rid).delete()
    return ""


async def _give(ctx, a, b, add: bool):
    if b.strip():
        m, r = get_member(ctx, a), get_role(ctx, b)
    else:
        m, r = get_member(ctx, ""), get_role(ctx, a)
    await (m.add_roles(r) if add else m.remove_roles(r))


@fn("giveRole", min_args=1, brackets="required")
async def _giverole(ctx, a, b=""):
    await _give(ctx, a, b, True)
    return ""


@fn("takeRole", min_args=1, brackets="required")
async def _takerole(ctx, a, b=""):
    await _give(ctx, a, b, False)
    return ""


@fn("roleGrant", min_args=2, brackets="required")
async def _rolegrant(ctx, uid, *changes):
    m = get_member(ctx, uid)
    for c in changes:
        c = c.strip()
        if not c:
            continue
        if c[0] == "-":
            await m.remove_roles(get_role(ctx, c[1:]))
        elif c[0] == "!":
            r = get_role(ctx, c[1:])
            has = any(str(x.id) == str(r.id) for x in m.roles)
            await (m.remove_roles(r) if has else m.add_roles(r))
        else:
            await m.add_roles(get_role(ctx, c[1:] if c[0] == "+" else c))
    return ""


@fn("setUserRoles", min_args=1, brackets="required")
async def _setuserroles(ctx, uid, *rids):
    m = get_member(ctx, uid)
    wanted = {str(get_role(ctx, r).id) for r in rids if r.strip()}
    have = {str(r.id) for r in m.roles if not r.is_default()}
    for rid in have - wanted:
        await m.remove_roles(get_role(ctx, rid))
    for rid in wanted - have:
        await m.add_roles(get_role(ctx, rid))
    return ""


@fn("modifyRole", min_args=1, brackets="required")
async def _modifyrole(ctx, rid, name="", color="", hoist="", mentionable=""):
    kw = {}
    if name:
        kw["name"] = name
    if color.strip():
        kw["colour"] = colour_value(color)
    if hoist.strip():
        kw["hoist"] = truthy(hoist)
    if mentionable.strip():
        kw["mentionable"] = truthy(mentionable)
    await get_role(ctx, rid).edit(**kw)
    return ""


@fn("modifyRolePerms", min_args=2, brackets="required")
async def _modifyroleperms(ctx, rid, *perms):
    from ....permissions import Permissions
    r = get_role(ctx, rid)
    p = Permissions(r.permissions.value)
    for k, v in _parse_perm_list(perms).items():
        setattr(p, k, bool(v))
    await r.edit(permissions=p)
    return ""


@fn("colorRole", min_args=1, brackets="required")
async def _colorrole(ctx, color, rid=""):
    from .people import _sorted_roles
    r = get_role(ctx, rid) if rid.strip() else (_sorted_roles(get_member(ctx, ""))[-1:] or [None])[0]
    if r is None:
        raise BDScriptError("no role to colour")
    await r.edit(colour=colour_value(color))
    return ""


@fn("findRole", min_args=1, brackets="required")
def _findrole(ctx, query):
    q = strip_mention(query).lower()
    for r in _g(ctx).roles:
        if str(r.id).lower() == q or r.name.lower() == q:
            return str(r.id)
    for r in _g(ctx).roles:
        if q and q in r.name.lower():
            return str(r.id)
    return ""


@fn("randomRoleID")
def _randomrole(ctx, gid=""):
    rs = [r for r in _g(ctx, gid).roles if not r.is_default()]
    return str(random.choice(rs).id) if rs else ""


# -- moderation --------------------------------------------------------------------------------------------
def _first_mention(ctx):
    from .text import _mention_ids
    ids = _mention_ids(ctx, "user")
    if not ids:
        raise BDScriptError("no user mentioned")
    return ids[0]


def _looks_like_user(ctx, v: str) -> bool:
    v = strip_mention(v or "")
    if not v:
        return False
    if v.startswith("npub1") or (len(v) == 64 and all(c in "0123456789abcdef" for c in v.lower())) or (v.isdigit() and len(v) >= 15):
        return True
    return ctx.guild is not None and ctx.guild.get_member(v) is not None


@fn("ban")
@fn("banComplex")
async def _ban(ctx, a="", b="", *rest):
    """``$ban`` / ``$ban[reason]`` ban the first mentioned user (BDFD); ``$ban[userID;reason;deleteDays]`` also works."""
    if _looks_like_user(ctx, a):
        uid, reason = a, b
    else:
        uid, reason = _first_mention(ctx), a
    await _g(ctx).ban(get_member(ctx, uid, required=False) or strip_mention(uid), reason=reason or None)
    return ""


@fn("banID")
@fn("banIDComplex")
async def _banid(ctx, a="", b="", *rest):
    """``$banID[reason;(userID)]`` (BDFD) or ``$banID[userID;(reason)]``; without a user, the first argument."""
    if _looks_like_user(ctx, a):
        target, reason = a, b
    else:
        target, reason = b.strip() or (ctx.args[0] if ctx.args else ""), a
    if not target:
        raise BDScriptError("no user ID")
    await _g(ctx).ban(get_member(ctx, target, required=False) or strip_mention(target), reason=reason or None)
    return ""


@fn("kick")
@fn("kickComplex")
async def _kick(ctx, uid="", reason=""):
    target = uid.strip() or _first_mention(ctx)
    await _g(ctx).kick(get_member(ctx, target, required=False) or strip_mention(target), reason=reason or None)
    return ""


@fn("kickMention")
async def _kickmention(ctx, reason=""):
    await _g(ctx).kick(get_member(ctx, _first_mention(ctx)), reason=reason or None)
    return ""


@fn("unban", brackets="optional")
async def _unban(ctx, uid="", *a):
    target = uid.strip() or (ctx.args[0] if ctx.args else "")
    if not target:
        raise BDScriptError("no user ID in the message")
    await _g(ctx).unban(strip_mention(target))
    return ""


@fn("unbanID")
@fn("unbanIDComplex")
async def _unbanid(ctx, uid="", *a):
    target = uid.strip() or (ctx.args[0] if ctx.args else "")
    await _g(ctx).unban(strip_mention(target))
    return ""


@fn("timeout", min_args=1, brackets="required")
async def _timeout(ctx, duration, uid="", *reason):
    if _looks_like_user(ctx, duration) and not _looks_like_user(ctx, uid):  # $timeout[userID;duration;reason]
        duration, uid = uid, duration
    m = get_member(ctx, uid)
    await m.timeout(datetime.timedelta(seconds=seconds(duration)), reason=";".join(reason) or None)
    return ""


@fn("untimeout")
async def _untimeout(ctx, uid="", *a):
    await get_member(ctx, uid).timeout(None)
    return ""


@fn("mute", min_args=1, brackets="required")
async def _mute(ctx, role_name, uid=""):
    target = uid.strip() or _first_mention(ctx)
    await get_member(ctx, target).add_roles(get_role(ctx, role_name))
    return ""


@fn("unmute", min_args=1, brackets="required")
async def _unmute(ctx, role_name, uid=""):
    target = uid.strip() or _first_mention(ctx)
    await get_member(ctx, target).remove_roles(get_role(ctx, role_name))
    return ""


@fn("isBanned", min_args=1, brackets="required")
async def _isbanned(ctx, uid, gid=""):
    g = _g(ctx, gid)
    try:
        await g.fetch_ban(strip_mention(uid))
        return True
    except Exception:
        return False


@fn("getBanReason", min_args=1, brackets="required")
async def _banreason(ctx, uid, gid=""):
    try:
        b = await _g(ctx, gid).fetch_ban(strip_mention(uid))
        return escape(getattr(b, "reason", None) or "")
    except Exception:
        return ""


@fn("clear")
@fn("clearComplex")
async def _clear(ctx, amount="", uid="", remove_pinned="no", cid=""):
    n = to_int(amount) if amount.strip() else (to_int(ctx.args[0]) if ctx.args else 0)
    if n <= 0:
        raise BDScriptError("amount must be at least 1")
    ch = get_channel(ctx, cid)
    target = strip_mention(uid) if uid.strip() else None
    keep_pinned = not truthy(remove_pinned)

    def check(m):
        if target and str(m.author.id) != target:
            return False
        if keep_pinned and getattr(m, "pinned", False):
            return False
        return True

    deleted = await ch.purge(limit=min(n, 1000), check=check)
    return ""
