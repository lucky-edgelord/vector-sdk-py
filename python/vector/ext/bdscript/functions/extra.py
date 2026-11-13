"""Newer BDFD functions (Components V2 selects, autocomplete, uncached $' variants) and D.js-BDscript music."""

from __future__ import annotations

import asyncio
import random

from ..context import ButtonSpec, SelectSpec
from ..parser import escape
from ..registry import FUNCTIONS, BDScriptError, Function, fn
from ..util import get_channel, strip_mention, to_int, truthy


# -- uncached random variants: $'random, $'randomText ... (BDFD caches identical calls; these never do) -----
def _uncached(name):
    base = FUNCTIONS[name.lower()]

    import functools

    @functools.wraps(base.impl)
    def impl(ctx, *args):
        ctx.extras["no_cache"] = True
        try:
            return base.impl(ctx, *args)
        finally:
            ctx.extras.pop("no_cache", None)
    FUNCTIONS["'" + name.lower()] = Function("'" + name, impl, base.brackets, base.lazy, base.min_args, base.max_args)


def register_uncached():
    for n in ("random", "randomText", "randomUser", "randomMention", "randomUserID", "randomString", "randomChannelID"):
        if "'" + n.lower() not in FUNCTIONS or n == "randomChannelID":
            _uncached(n)


@fn("getSplitText", min_args=1, brackets="required")
def _getsplittext(ctx, index):
    return FUNCTIONS["splittext"].impl(ctx, index)


# -- Components V2 -----------------------------------------------------------------------------------------
@fn("addButtonCV2", min_args=4, brackets="required")
async def _addbuttoncv2(ctx, *args):
    return await FUNCTIONS["addbutton"].impl(ctx, *args)


def _entity_select(ctx, cid, placeholder, mn, mx, options, kind):
    spec = SelectSpec(custom_id=cid, placeholder=placeholder, min_values=to_int(mn or "1"), max_values=to_int(mx or "1"),
                      options=options[:25])
    spec.kind = kind  # type: ignore[attr-defined]
    rows = ctx.response.rows
    if rows[-1]:
        rows.append([])
    rows[-1].append(spec)
    rows.append([])


def _member_options(ctx):
    g = ctx.guild
    if g is None:
        raise BDScriptError("user selects need a community")
    return [{"label": m.display_name, "value": str(m.id)} for m in list(g.members)[:25]]


def _role_options(ctx):
    g = ctx.guild
    if g is None:
        raise BDScriptError("role selects need a community")
    return [{"label": r.name, "value": str(r.id)} for r in g.roles if not r.is_default()][:25]


@fn("addUserSelect", min_args=1, brackets="required")
def _adduserselect(ctx, cid, placeholder="", mn="1", mx="1", *a):
    _entity_select(ctx, cid, placeholder, mn, mx, _member_options(ctx), "user")
    return ""


@fn("addRoleSelect", min_args=1, brackets="required")
def _addroleselect(ctx, cid, placeholder="", mn="1", mx="1", *a):
    _entity_select(ctx, cid, placeholder, mn, mx, _role_options(ctx), "role")
    return ""


@fn("addMentionableSelect", min_args=1, brackets="required")
def _addmentionableselect(ctx, cid, placeholder="", mn="1", mx="1", *a):
    _entity_select(ctx, cid, placeholder, mn, mx, (_member_options(ctx) + _role_options(ctx))[:25], "mentionable")
    return ""


def _values(ctx):
    return list(ctx.extras.get("values") or [])


def _nth(ctx, index):
    v = _values(ctx)
    i = to_int(index or "1")
    return v[i - 1] if 0 < i <= len(v) else ""


for _kind in ("UserSelectUser", "RoleSelectRole", "MentionableSelectUser"):
    fn(f"get{_kind}ID")(lambda ctx, index="1": _nth(ctx, index))
    fn(f"get{_kind}IDs")(lambda ctx, sep=", ": (sep or ", ").join(_values(ctx)))
    fn(f"get{_kind}Count", brackets="optional")(lambda ctx, *a: str(len(_values(ctx))))


# -- slash autocomplete ------------------------------------------------------------------------------------
@fn("appendOptionSuggestion", min_args=2, brackets="required", status="partial",
    note="collected; shown if the client supports autocomplete")
def _suggest(ctx, label, value):
    s = ctx.extras.setdefault("suggestions", [])
    if len(s) >= 25:
        raise BDScriptError("at most 25 suggestions")
    s.append({"label": label, "value": value})
    return ""


@fn("autoCompleteOptionName", brackets="none")
def _acname(ctx):
    return ctx.extras.get("ac_option", "")


@fn("autoCompleteOptionValue", brackets="none")
def _acvalue(ctx):
    return escape(ctx.extras.get("ac_value", ""))


fn("onAutoComplete")(lambda ctx, *a: "")


# -- music (D.js-BDscript; Vector voice) -------------------------------------------------------------------
def _audio(ctx):
    return ctx.bot.audio


async def _voice_channel(ctx, cid=""):
    if cid.strip():
        ch = get_channel(ctx, cid)
        if not hasattr(ch, "connect"):
            raise BDScriptError(f"'{cid}' isn't a voice channel")
        return ch
    m = ctx.member()
    vs = getattr(m, "voice", None)
    ch = getattr(vs, "channel", None)
    if ch is None:
        raise BDScriptError("join a voice channel first, or give a channel ID")
    return ch


@fn("joinVoice", brackets="optional")
@fn("joinVC", brackets="optional")
async def _joinvoice(ctx, cid=""):
    await _audio(ctx).join(ctx, await _voice_channel(ctx, cid))
    return ""


@fn("leaveVoice", brackets="optional")
@fn("leaveVC", brackets="optional")
async def _leavevoice(ctx, cid=""):
    await _audio(ctx).leave(ctx.guild_id)
    return ""


@fn("playSong", min_args=1, brackets="required")
@fn("playTrack", min_args=1, brackets="required")
async def _playsong(ctx, *query):
    track = await _audio(ctx).add(ctx, ";".join(query))
    return escape(track.title)


@fn("skipSong", brackets="none")
@fn("skipTrack", brackets="none")
def _skip(ctx):
    _audio(ctx).skip(ctx.guild_id)
    return ""


@fn("stopSong", brackets="none")
@fn("stopMusic", brackets="none")
def _stopsong(ctx):
    _audio(ctx).stop(ctx.guild_id)
    return ""


@fn("pauseSong", brackets="none")
def _pause(ctx):
    _audio(ctx).pause(ctx.guild_id)
    return ""


@fn("resumeSong", brackets="none")
def _resume(ctx):
    _audio(ctx).resume(ctx.guild_id)
    return ""


@fn("queueLength", brackets="none")
def _queuelen(ctx):
    return str(len(_audio(ctx).queue(ctx.guild_id)))


@fn("queue", brackets="optional")
def _queue(ctx, sep="\n"):
    q = _audio(ctx).queue(ctx.guild_id)
    return (sep or "\n").join(f"{i}. {t.title}" for i, t in enumerate(q, 1))


@fn("songInfo", brackets="optional")
@fn("trackInfo", brackets="optional")
def _songinfo(ctx, prop="title"):
    t = ctx.extras.get("track") or _audio(ctx).current(ctx.guild_id)
    if t is None:
        return ""
    return escape(str(getattr(t, prop.strip() or "title", "") or ""))


@fn("say", min_args=1, brackets="required")
async def _say(ctx, *text):
    """Speak text in the current voice channel (Vector's built-in TTS)."""
    vc = _audio(ctx).client_for(ctx.guild_id)
    if vc is None:
        raise BDScriptError("not in a voice channel ($joinVoice first)")
    await vc.say_and_wait(";".join(text)) if hasattr(vc, "say_and_wait") else vc.say(";".join(text))
    return ""
