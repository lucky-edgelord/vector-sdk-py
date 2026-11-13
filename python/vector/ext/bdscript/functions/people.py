"""Users, members, roles, permissions, and D.js-BDscript's condensed $user/$member/$role/$client."""

from __future__ import annotations

import random

from ..parser import escape
from ..registry import BDScriptError, fn
from ..util import (bdfd_date, get_member, get_role, get_user, ids, perm_name, perm_names, strip_mention, to_int,
                    truthy, ts, user_id)
from .timefn import go_format


def _name(u) -> str:
    return escape(getattr(u, "name", "") or "")


def _avatar(u) -> str:
    a = getattr(u, "display_avatar", None) or getattr(u, "avatar", None)
    return str(a) if a else ""


# -- identity ----------------------------------------------------------------------------------------------
@fn("authorID", brackets="none")
def _authorid(ctx):
    return ctx.author_id


@fn("username")
@fn("usernameComplex")
def _username(ctx, uid=""):
    return _name(get_user(ctx, uid))


@fn("userID", brackets="optional")
def _userid(ctx, name=""):
    if not name.strip():
        return ctx.author_id
    name = name.split("#")[0].strip().lower()
    pool = list(getattr(ctx.guild, "members", []) or []) + list(getattr(ctx.client, "users", []) or [])
    for u in pool:
        if name in ((getattr(u, "name", "") or "").lower(), (getattr(u, "display_name", "") or "").lower()):
            return str(u.id)
    raise BDScriptError(f"user '{name}' not found")


@fn("discriminator")
def _discriminator(ctx, uid=""):
    return "0"


@fn("displayName")
@fn("displayNameComplex")
def _displayname(ctx, uid=""):
    m = get_member(ctx, uid, required=False) if ctx.guild else None
    u = m or get_user(ctx, uid)
    return escape(getattr(u, "display_name", None) or getattr(u, "name", "") or "")


@fn("nickname")
@fn("nicknameComplex")
def _nickname(ctx, uid="", gid=""):
    from ..util import get_guild
    m = get_member(ctx, uid, guild=get_guild(ctx, gid), required=False)
    return escape(getattr(m, "nick", None) or (getattr(m, "name", "") if m else ""))


@fn("userAvatar")
def _useravatar(ctx, uid=""):
    return _avatar(get_user(ctx, uid))


@fn("authorAvatar", brackets="none")
def _authoravatar(ctx):
    return _avatar(ctx.author)


@fn("userServerAvatar")
def _serveravatar(ctx, uid="", gid=""):
    return _avatar(get_user(ctx, uid))


@fn("userBanner")
def _userbanner(ctx, uid=""):
    b = getattr(get_user(ctx, uid), "banner", None)
    return str(b) if b else ""


@fn("userBannerColor", status="noop", note="Vector profiles have no banner colour")
def _bannercolor(ctx, uid=""):
    return ""


@fn("userBadges", status="noop", note="no badges on Vector")
def _badges(ctx, uid="", sep=", "):
    u = get_user(ctx, uid)
    return "bot" if getattr(u, "bot", False) else ""


@fn("hypesquad", status="noop", note="no HypeSquad on Vector")
def _hypesquad(ctx, uid="", *a):
    return "none"


@fn("userInfo", min_args=0)
def _userinfo(ctx, *msg):
    u = get_user(ctx, "")
    from ....embeds import Embed
    e = ctx.response.embed(1)
    e.title = getattr(u, "display_name", None) or u.name
    e.set_thumbnail(url=_avatar(u) or None)
    e.add_field(name="ID", value=str(u.id), inline=False)
    m = get_member(ctx, "", required=False) if ctx.guild else None
    if m is not None:
        e.add_field(name="Roles", value=", ".join(r.name for r in m.roles if not r.is_default()) or "none", inline=False)
    if msg:
        e.description = ";".join(msg)
    return ""


@fn("userJoined", min_args=0)
def _userjoined(ctx, uid="", layout=""):
    m = get_member(ctx, uid)
    dt = getattr(m, "joined_at", None)
    if dt is None:
        return ""
    return go_format(dt, layout) if layout else bdfd_date(dt)


@fn("userJoinedDiscord", min_args=0)
def _userjoineddiscord(ctx, uid="", layout=""):
    dt = getattr(get_user(ctx, uid), "created_at", None)
    if dt is None:
        return ""
    return go_format(dt, layout) if layout else bdfd_date(dt)


@fn("userExists", min_args=1, brackets="required")
def _userexists(ctx, uid):
    return get_user(ctx, uid, required=False) is not None or bool(strip_mention(uid).startswith("npub1"))


@fn("isBot")
def _isbot(ctx, uid=""):
    return bool(getattr(get_user(ctx, uid), "bot", False))


@fn("isAdmin")
def _isadmin(ctx, uid=""):
    m = get_member(ctx, uid)
    return bool(m.is_admin() if callable(getattr(m, "is_admin", None)) else m.guild_permissions.administrator)


@fn("isBooster", status="noop", note="no boosting on Vector")
def _isbooster(ctx, *a):
    return False


@fn("isTimedOut")
def _istimedout(ctx, uid=""):
    m = get_member(ctx, uid)
    return bool(m.is_timed_out())


@fn("getUserStatus")
def _status(ctx, uid=""):
    u = get_user(ctx, uid)
    st = getattr(u, "status", None)
    return str(st) if st else "online"


@fn("getCustomStatus")
def _customstatus(ctx, uid=""):
    return escape(getattr(get_user(ctx, uid), "status_text", "") or "")


@fn("isUserDMEnabled")
def _dmenabled(ctx, uid=""):
    return True


@fn("authorOfMessage", min_args=2, brackets="required")
async def _authorof(ctx, cid, mid):
    from ..util import get_channel
    msg = await get_channel(ctx, cid).fetch_message(mid)
    return str(msg.author.id)


@fn("findUser", min_args=1, brackets="required")
def _finduser(ctx, query, return_author="yes"):
    q = strip_mention(query).lower()
    pool = list(getattr(ctx.guild, "members", []) or []) + list(getattr(ctx.client, "users", []) or [])
    for u in pool:
        if str(u.id).lower() == q:
            return str(u.id)
    for u in pool:
        if q in ((u.name or "").lower(), (getattr(u, "display_name", "") or "").lower(), (getattr(u, "nick", "") or "").lower()):
            return str(u.id)
    for u in pool:
        if q and q in (u.name or "").lower():
            return str(u.id)
    return ctx.author_id if truthy(return_author, True) else ""


def _members(ctx):
    if ctx.guild is None:
        raise BDScriptError("this only works in a community")
    return list(ctx.guild.members)


@fn("randomUser", brackets="none")
def _randomuser(ctx):
    return _name(random.choice(_members(ctx)))


@fn("randomUserID", brackets="none")
def _randomuserid(ctx):
    return str(random.choice(_members(ctx)).id)


@fn("randomMention", brackets="none")
def _randommention(ctx):
    return random.choice(_members(ctx)).mention


@fn("changeUsername", min_args=1, brackets="required")
async def _changenick(ctx, nick):
    await get_member(ctx, "").edit(nick=nick or None)
    return ""


@fn("changeUsernameWithID", min_args=2, brackets="required")
async def _changenickid(ctx, uid, nick):
    await get_member(ctx, uid).edit(nick=nick or None)
    return ""


# -- permissions & roles of members ------------------------------------------------------------------------
@fn("userPerms")
def _userperms(ctx, uid="", amount="-1", sep=", "):
    names = perm_names(get_member(ctx, uid).guild_permissions)
    n = to_int(amount) if amount.strip() else -1
    return (sep or ", ").join(names if n < 0 else names[:n])


@fn("checkUserPerms", min_args=2, brackets="required")
def _checkuserperms(ctx, uid, *perms):
    m = get_member(ctx, uid)
    return all(m.can(perm_name(p)) for p in perms)


@fn("userRoles")
def _userroles(ctx, uid="", gid="", option="ids", sep=", "):
    m = get_member(ctx, uid)
    roles = [r for r in m.roles if not r.is_default()]
    if option.strip().lower() in ("names", "name"):
        return (sep or ", ").join(r.name for r in roles)
    if option.strip().lower() in ("mentions", "mention"):
        return (sep or ", ").join(r.mention for r in roles)
    return (sep or ", ").join(str(r.id) for r in roles)


@fn("hasRole", min_args=2, brackets="required")
def _hasrole(ctx, uid, role, gid=""):
    m = get_member(ctx, uid)
    r = get_role(ctx, role)
    return any(str(x.id) == str(r.id) for x in m.roles)


def _sorted_roles(m):
    return sorted([r for r in m.roles if not r.is_default()], key=lambda r: getattr(r, "position", 0))


@fn("highestRole")
@fn("highestRoleComplex")
def _highestrole(ctx, uid="", gid=""):
    roles = _sorted_roles(get_member(ctx, uid))
    return str(roles[-1].id) if roles else ""


@fn("lowestRole")
@fn("lowestRoleComplex")
def _lowestrole(ctx, uid="", gid=""):
    roles = _sorted_roles(get_member(ctx, uid))
    return str(roles[0].id) if roles else ""


def _roles_with(ctx, perms):
    wanted = [perm_name(p) for p in perms if p.strip()]
    m = get_member(ctx, "")
    return [r for r in _sorted_roles(m) if all(getattr(r.permissions, w, False) for w in wanted)]


@fn("highestRoleWithPerms", min_args=1, brackets="required")
def _highestwith(ctx, *perms):
    r = _roles_with(ctx, perms)
    return str(r[-1].id) if r else ""


@fn("lowestRoleWithPerms", min_args=1, brackets="required")
def _lowestwith(ctx, *perms):
    r = _roles_with(ctx, perms)
    return str(r[0].id) if r else ""


# -- D.js-BDscript condensed functions ---------------------------------------------------------------------
def _user_props(u):
    return {
        "id": lambda: str(u.id), "username": lambda: u.name, "tag": lambda: u.name, "discriminator": lambda: "0",
        "avatar": lambda: _avatar(u), "bot": lambda: "true" if getattr(u, "bot", False) else "false",
        "badges": lambda: "", "createdTimestamp": lambda: ts(getattr(u, "created_at", None), "ms"),
        "lastMessageChannelID": lambda: "", "lastMessageID": lambda: "", "mention": lambda: u.mention,
        "displayName": lambda: getattr(u, "display_name", u.name), "npub": lambda: getattr(u, "npub", ""),
        "about": lambda: getattr(u, "about", "") or "", "banner": lambda: str(getattr(u, "banner", "") or ""),
        "status": lambda: getattr(u, "status_text", "") or "",
    }


def _member_props(m):
    top = getattr(m, "top_role", None)
    return {
        "guildID": lambda: str(m.guild.id), "voiceChannelID": lambda: str(getattr(getattr(m, "voice", None), "channel", "") and m.voice.channel.id or ""),
        "nickname": lambda: m.nick or "", "displayName": lambda: m.display_name,
        "joinedTimestamp": lambda: ts(m.joined_at, "ms"), "id": lambda: str(m.id),
        "hexColor": lambda: f"#{m.colour.value:06x}" if getattr(m, "colour", None) else "#000000",
        "color": lambda: str(m.colour.value) if getattr(m, "colour", None) else "0",
        "highestRoleID": lambda: str(top.id) if top else "",
        "permissions": lambda: ", ".join(perm_names(m.guild_permissions)),
        "roles": lambda: ", ".join(str(r.id) for r in m.roles if not r.is_default()),
        "isAdmin": lambda: "true" if m.is_admin() else "false", "timedOut": lambda: "true" if m.is_timed_out() else "false",
    }


def _role_props(r):
    return {
        "permissions": lambda: ", ".join(perm_names(r.permissions)), "name": lambda: r.name, "id": lambda: str(r.id),
        "position": lambda: str(getattr(r, "position", 0)), "isEveryoneRole": lambda: "true" if r.is_default() else "false",
        "isMentionable": lambda: "true" if getattr(r, "mentionable", True) else "false",
        "members": lambda: ", ".join(str(m.id) for m in r.members), "mention": lambda: r.mention,
        "hexColor": lambda: f"#{r.colour.value:06x}" if r.colour else "#000000", "color": lambda: str(r.colour.value if r.colour else 0),
        "hoist": lambda: "true" if getattr(r, "hoist", False) else "false",
    }


def _prop(table, prop, what):
    if prop not in table:
        raise BDScriptError(f"invalid {what} property '{prop}'. Valid: {', '.join(table)}")
    return escape(str(table[prop]() or ""))


@fn("user", min_args=1, brackets="required")
def _user(ctx, uid, prop="username"):
    return _prop(_user_props(get_user(ctx, uid)), prop.strip(), "user")


@fn("member", min_args=1, brackets="required")
def _member(ctx, uid, prop="displayName"):
    return _prop(_member_props(get_member(ctx, uid)), prop.strip(), "member")


@fn("role", min_args=1, brackets="required")
def _role(ctx, rid, prop="name"):
    return _prop(_role_props(get_role(ctx, rid)), prop.strip(), "role")


@fn("client", min_args=1, brackets="required")
def _client(ctx, prop):
    c = ctx.client
    users = list(getattr(c, "users", []) or [])
    table = {
        "id": lambda: str(c.user.id), "users": lambda: str(len(users)), "guilds": lambda: str(len(c.communities)),
        "channels": lambda: str(sum(1 for _ in c.get_all_channels())), "emojis": lambda: str(len(c.emojis)),
        "commands": lambda: str(len(ctx.bot.commands)), "guildCount": lambda: str(len(c.communities)),
        "userCount": lambda: str(len(users)), "botCount": lambda: str(sum(1 for u in users if getattr(u, "bot", False))),
        "channelCount": lambda: str(sum(1 for _ in c.get_all_channels())),
        "owners": lambda: ", ".join(ctx.bot.owners), "name": lambda: c.user.name, "npub": lambda: c.npub,
        "ping": lambda: str(int((c.latency or 0) * 1000)),
    }
    return _prop(table, prop.strip(), "client")


@fn("server", min_args=1, brackets="required")
def _server(ctx, gid, prop="name"):
    """D.js-BDscript ``$server[guildID;property]`` (empty ID = current community)."""
    from ..util import get_guild
    g = get_guild(ctx, gid)
    table = {
        "id": lambda: str(g.id), "name": lambda: g.name, "description": lambda: g.description or "",
        "ownerID": lambda: str(g.owner_id or ""), "memberCount": lambda: str(g.member_count),
        "members": lambda: ", ".join(str(m.id) for m in g.members), "roles": lambda: ", ".join(str(r.id) for r in g.roles),
        "channels": lambda: ", ".join(str(c.id) for c in g.channels), "emojis": lambda: ", ".join(str(e) for e in g.emojis),
        "systemChannelID": lambda: str(getattr(g.system_channel, "id", "") or ""), "available": lambda: "true",
        "afkChannelID": lambda: "", "afkTimeout": lambda: "0", "rulesChannelID": lambda: "", "region": lambda: "nostr",
        "verificationLevel": lambda: "none", "premiumTier": lambda: "0", "premiumSubscriptionCount": lambda: "0",
        "isPartnered": lambda: "false", "mfaLevel": lambda: "none", "preferredLocale": lambda: "en-US",
        "features": lambda: "", "publicUpdatesChannelID": lambda: "", "explicitContentFilter": lambda: "disabled",
        "defaultMessageNotifications": lambda: "all", "commands": lambda: str(len(ctx.bot.commands)),
        "bans": lambda: ", ".join(ctx.client.native.community_banned(g.id)) if hasattr(ctx.client, "native") else "",
        "relays": lambda: ", ".join(g.relays), "admins": lambda: ", ".join(str(getattr(a, "id", a)) for a in g.admins),
    }
    return _prop(table, prop.strip(), "server")


@fn("channel", min_args=1, brackets="required")
def _channel(ctx, cid, prop="name"):
    """D.js-BDscript ``$channel[channelID;property]``."""
    from ..util import get_channel
    c = get_channel(ctx, cid)
    table = {
        "id": lambda: str(c.id), "name": lambda: getattr(c, "name", "") or "",
        "type": lambda: type(c).__name__.replace("Channel", "").lower(), "topic": lambda: getattr(c, "topic", "") or "",
        "position": lambda: str(getattr(c, "position", 0)), "parentID": lambda: str(getattr(c, "category_id", "") or ""),
        "guildID": lambda: str(getattr(getattr(c, "guild", None), "id", "") or ""), "mention": lambda: getattr(c, "mention", ""),
        "nsfw": lambda: "false", "deleteable": lambda: "true", "manageable": lambda: "true",
        "readOnly": lambda: "true" if getattr(c, "read_only", False) else "false",
    }
    return _prop(table, prop.strip(), "channel")
