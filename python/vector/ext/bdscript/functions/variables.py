"""Persistent variables (BDFD scopes + D.js-BDscript's $setVar[name;value;id;type]), leaderboards, cooldowns."""

from __future__ import annotations

from ..parser import escape
from ..registry import BDScriptError, StopExecution, fn
from ..util import fmt_num, human_duration, seconds, strip_mention, to_int, to_num, user_id


def _default(ctx, name):
    v = ctx.bot.variables_def.get(name)
    if v is None:
        if ctx.bot.auto_variables:
            return ""
        raise BDScriptError(f"variable '{name}' doesn't exist (declare it with bot.variables(...))")
    return str(v)


def _read(ctx, scope, name, key):
    v = ctx.bot.storage.get(scope, name, key)
    return v if v is not None else _default(ctx, name)


def _write(ctx, scope, name, key, value):
    _default(ctx, name)  # existence check
    t = ctx.bot.variable_types.get(name)
    if t in ("INTEGER", "NUMBER", "INT", "FLOAT") and value.strip():
        try:
            float(value)
        except ValueError:
            raise BDScriptError(f"variable '{name}' holds numbers, got '{value}'")
    ctx.bot.storage.set(scope, name, key, value)


_FORK_SCOPES = {"user": "user_global", "member": "user", "server": "server", "guild": "server", "channel": "channel",
                "global": "global"}


def _fork_key(ctx, scope, ident):
    if scope == "user":  # member in a server
        return f"{ctx.guild_id}:{strip_mention(ident) or ctx.author_id}"
    if scope == "user_global":
        return strip_mention(ident) or ctx.author_id
    if scope == "server":
        return ident.strip() or ctx.guild_id
    if scope == "channel":
        return strip_mention(ident) or ctx.channel_id
    return ""


@fn("setVar", min_args=2, brackets="required")
def _setvar(ctx, name, value, ident="", kind=""):
    if kind.strip():
        scope = _FORK_SCOPES.get(kind.strip().lower())
        if scope is None:
            raise BDScriptError(f"invalid variable type '{kind}' (user/member/server/channel/global)")
        _write(ctx, scope, name, _fork_key(ctx, scope, ident), value)
    elif ident.strip():
        _write(ctx, "user_global", name, strip_mention(ident), value)
    else:
        _write(ctx, "global", name, "", value)
    return ""


@fn("getVar", min_args=1, brackets="required")
def _getvar(ctx, name, ident="", kind=""):
    if kind.strip():
        scope = _FORK_SCOPES.get(kind.strip().lower())
        if scope is None:
            raise BDScriptError(f"invalid variable type '{kind}'")
        return escape(_read(ctx, scope, name, _fork_key(ctx, scope, ident)))
    if ident.strip():
        return escape(_read(ctx, "user_global", name, strip_mention(ident)))
    return escape(_read(ctx, "global", name, ""))


@fn("setUserVar", min_args=2, brackets="required")
def _setuservar(ctx, name, value, uid="", gid=""):
    _write(ctx, "user", name, f"{gid.strip() or ctx.guild_id}:{user_id(ctx, uid)}", value)
    return ""


@fn("getUserVar", min_args=1, brackets="required")
def _getuservar(ctx, name, uid="", gid=""):
    return escape(_read(ctx, "user", name, f"{gid.strip() or ctx.guild_id}:{user_id(ctx, uid)}"))


@fn("setServerVar", min_args=2, brackets="required")
def _setservervar(ctx, name, value, gid=""):
    _write(ctx, "server", name, gid.strip() or ctx.guild_id, value)
    return ""


@fn("getServerVar", min_args=1, brackets="required")
def _getservervar(ctx, name, gid=""):
    return escape(_read(ctx, "server", name, gid.strip() or ctx.guild_id))


@fn("setChannelVar", min_args=2, brackets="required")
def _setchannelvar(ctx, name, value, cid=""):
    _write(ctx, "channel", name, strip_mention(cid) or ctx.channel_id, value)
    return ""


@fn("getChannelVar", min_args=1, brackets="required")
def _getchannelvar(ctx, name, cid=""):
    return escape(_read(ctx, "channel", name, strip_mention(cid) or ctx.channel_id))


@fn("resetUserVar", min_args=1, brackets="required")
def _resetuservar(ctx, name, uid=""):
    _default(ctx, name)
    if uid.strip():
        ctx.bot.storage.delete("user", name, f"{ctx.guild_id}:{user_id(ctx, uid)}")
    else:
        for key, _ in ctx.bot.storage.rows("user", name, f"{ctx.guild_id}:"):
            ctx.bot.storage.delete("user", name, key)
    return ""


@fn("resetServerVar", min_args=1, brackets="required")
def _resetservervar(ctx, name):
    _default(ctx, name)
    ctx.bot.storage.delete("server", name)
    return ""


@fn("resetChannelVar", min_args=1, brackets="required")
def _resetchannelvar(ctx, name):
    _default(ctx, name)
    ctx.bot.storage.delete("channel", name)
    return ""


@fn("varExists", min_args=1, brackets="required")
def _varexists(ctx, name):
    return name in ctx.bot.variables_def


@fn("varExistError", min_args=1, brackets="required")
def _varexisterror(ctx, name, msg=""):
    if name not in ctx.bot.variables_def:
        raise StopExecution(msg or "")
    return ""


@fn("listVar")
def _listvar(ctx, sep=", "):
    return (sep or ", ").join(sorted(ctx.bot.variables_def))


@fn("variablesCount")
def _varcount(ctx, kind=""):
    k = kind.strip().lower()
    scope = {"user": "user", "server": "server", "channel": "channel", "global": "global"}.get(k)
    return str(ctx.bot.storage.count(scope)) if k else str(len(ctx.bot.variables_def))


# -- leaderboards ------------------------------------------------------------------------------------------
def _ranked(ctx, scope, name, prefix=""):
    _default(ctx, name)
    rows = []
    for key, value in ctx.bot.storage.rows(scope, name, prefix):
        try:
            rows.append((key[len(prefix):], float(value)))
        except ValueError:
            continue
    return rows


def _sort(rows, sort):
    return sorted(rows, key=lambda r: r[1], reverse=(sort.strip().lower() or "desc") != "asc")


def _who(ctx, ident, scope):
    if scope == "server":
        g = ctx.client.get_community(ident)
        return escape(g.name) if g else ident
    u = (ctx.guild.get_member(ident) if ctx.guild else None) or ctx.client.get_user(ident)
    return escape(getattr(u, "display_name", None) or getattr(u, "name", None) or ident)


def _board(ctx, rows, scope, fmt=None, per_page=10, page=1):
    out = []
    start = (page - 1) * per_page
    for i, (ident, value) in enumerate(rows[start:start + per_page], start=start + 1):
        line = (fmt or "{position}. {username} - {value}").replace("{position}", str(i)) \
            .replace("{username}", _who(ctx, ident, scope)).replace("{value}", fmt_num(value)).replace("{id}", ident)
        out.append(line)
    return "\n".join(out)


@fn("userLeaderboard", min_args=1, brackets="required")
def _userboard(ctx, name, sort="desc", page="1", per_page="10", fmt=""):
    rows = _sort(_ranked(ctx, "user", name, f"{ctx.guild_id}:"), sort)
    return _board(ctx, rows, "user", fmt or None, to_int(per_page or "10"), to_int(page or "1"))


@fn("globalUserLeaderboard", min_args=1, brackets="required")
def _globalboard(ctx, name, sort="desc", page="1", per_page="10", fmt=""):
    rows = _sort(_ranked(ctx, "user_global", name), sort)
    return _board(ctx, rows, "user_global", fmt or None, to_int(per_page or "10"), to_int(page or "1"))


@fn("serverLeaderboard", min_args=1, brackets="required")
def _serverboard(ctx, name, sort="desc", page="1", per_page="10", fmt=""):
    rows = _sort(_ranked(ctx, "server", name), sort)
    return _board(ctx, rows, "server", fmt or None, to_int(per_page or "10"), to_int(page or "1"))


def _board_rows(ctx, kind, name, sort):
    k = kind.strip().lower()
    if k == "user":
        return _sort(_ranked(ctx, "user", name, f"{ctx.guild_id}:"), sort), "user"
    if k in ("globaluser", "global"):
        return _sort(_ranked(ctx, "user_global", name), sort), "user_global"
    if k == "server":
        return _sort(_ranked(ctx, "server", name), sort), "server"
    raise BDScriptError(f"invalid variable type '{kind}' (user/globalUser/server)")


@fn("getLeaderboardPosition", min_args=3, brackets="required")
def _lbpos(ctx, kind, name, sort, ident=""):
    rows, scope = _board_rows(ctx, kind, name, sort)
    target = strip_mention(ident) or (ctx.guild_id if scope == "server" else ctx.author_id)
    for i, (k, _) in enumerate(rows, 1):
        if k == target:
            return str(i)
    return "0"


@fn("getLeaderboardValue", min_args=4, brackets="required")
def _lbvalue(ctx, kind, name, sort, position, ret="value"):
    rows, scope = _board_rows(ctx, kind, name, sort)
    i = to_int(position)
    if not 0 < i <= len(rows):
        return ""
    ident, value = rows[i - 1]
    r = ret.strip().lower() or "value"
    if r == "value":
        return fmt_num(value)
    if r in ("id", "userid", "serverid"):
        return ident
    if r in ("username", "name", "servername"):
        return _who(ctx, ident, scope)
    raise BDScriptError(f"invalid return type '{ret}' (value/id/username)")


# -- cooldowns ---------------------------------------------------------------------------------------------
def _cooldown(ctx, kind, key, duration, msg):
    cmd = getattr(ctx.command, "name", "") or "?"
    left = ctx.bot.storage.cooldown_left(kind, cmd, key)
    if left > 0:
        text = msg.replace("%time%", human_duration(left)).replace("%time-s%", str(int(left)))
        raise StopExecution(text or f"Please wait {human_duration(left)}.")
    ctx.bot.storage.set_cooldown(kind, cmd, key, seconds(duration))
    return ""


@fn("cooldown", min_args=1, brackets="required")
def _cd(ctx, duration, msg=""):
    return _cooldown(ctx, "user", f"{ctx.guild_id}:{ctx.author_id}", duration, msg)


@fn("serverCooldown", min_args=1, brackets="required")
def _scd(ctx, duration, msg=""):
    return _cooldown(ctx, "server", ctx.guild_id, duration, msg)


@fn("globalCooldown", min_args=1, brackets="required")
def _gcd(ctx, duration, msg=""):
    return _cooldown(ctx, "global", ctx.author_id, duration, msg)


@fn("getCooldown", min_args=1, brackets="required")
def _getcd(ctx, kind, cmd=""):
    k = kind.strip().lower()
    key = {"user": f"{ctx.guild_id}:{ctx.author_id}", "server": ctx.guild_id, "global": ctx.author_id}.get(k)
    if key is None:
        raise BDScriptError(f"invalid cooldown type '{kind}' (user/server/global)")
    return str(int(ctx.bot.storage.cooldown_left(k, cmd or getattr(ctx.command, "name", ""), key)))


@fn("changeCooldownTime", min_args=1, brackets="required")
def _changecd(ctx, days="0", hours="0", minutes="0", secs="0"):
    total = to_num(days or 0) * 86400 + to_num(hours or 0) * 3600 + to_num(minutes or 0) * 60 + to_num(secs or 0)
    cmd = getattr(ctx.command, "name", "") or "?"
    for kind, key in (("user", f"{ctx.guild_id}:{ctx.author_id}"), ("server", ctx.guild_id), ("global", ctx.author_id)):
        if ctx.bot.storage.cooldown_left(kind, cmd, key) > 0:
            ctx.bot.storage.set_cooldown(kind, cmd, key, total)
    return ""
