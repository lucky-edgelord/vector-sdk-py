"""Helpers shared by BDScript functions: lookups, permissions, durations, booleans."""

from __future__ import annotations

import datetime
import re
from typing import Any, Iterable, List, Optional

from .registry import BDScriptError

_MENTION = re.compile(r"^<[@#](?:!|&)?([^>]+)>$")

# BDFD permission names -> discord.py / vector names
PERMS = {
    "admin": "administrator", "administrator": "administrator", "kick": "kick_members", "kickmembers": "kick_members",
    "ban": "ban_members", "banmembers": "ban_members", "managechannels": "manage_channels",
    "managechannel": "manage_channels", "manageserver": "manage_guild", "manageguild": "manage_guild",
    "addreactions": "add_reactions", "viewauditlog": "view_audit_log", "auditlog": "view_audit_log",
    "priorityspeaker": "priority_speaker", "stream": "stream", "readmessages": "read_messages",
    "viewchannel": "view_channel", "sendmessages": "send_messages", "sendtts": "send_tts_messages",
    "managemessages": "manage_messages", "embedlinks": "embed_links", "attachfiles": "attach_files",
    "readmessagehistory": "read_message_history", "mentioneveryone": "mention_everyone",
    "externalemojis": "use_external_emojis", "useexternalemojis": "use_external_emojis", "connect": "connect",
    "speak": "speak", "mutemembers": "mute_members", "deafenmembers": "deafen_members",
    "movemembers": "move_members", "usevad": "use_voice_activation", "changenickname": "change_nickname",
    "managenicknames": "manage_nicknames", "manageroles": "manage_roles", "managewebhooks": "manage_webhooks",
    "manageemojis": "manage_emojis", "manageemojisandstickers": "manage_emojis", "useslashcommands": "use_application_commands",
    "usecommands": "use_application_commands", "requesttospeak": "request_to_speak", "manageevents": "manage_events",
    "managethreads": "manage_threads", "createpublicthreads": "create_public_threads",
    "createprivatethreads": "create_private_threads", "externalstickers": "use_external_stickers",
    "sendmessagesinthreads": "send_messages_in_threads", "moderatemembers": "moderate_members",
    "timeout": "moderate_members", "createinvite": "create_instant_invite", "createinstantinvite": "create_instant_invite",
}


def perm_name(p: str) -> str:
    key = p.strip().lower().replace("_", "").replace(" ", "")
    if key not in PERMS:
        raise BDScriptError(f"invalid permission '{p}'")
    return PERMS[key]


def perm_names(holder_perms: Any) -> List[str]:
    """BDFD-style names of every permission a Permissions object has."""
    rev = {}
    for k, v in PERMS.items():
        rev.setdefault(v, k)
    out = []
    for name, value in holder_perms:
        if value and name in rev:
            out.append(rev[name])
    return out


def strip_mention(text: str) -> str:
    text = text.strip()
    m = _MENTION.match(text)
    return m.group(1) if m else text


def truthy(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    s = str(v).strip().lower()
    if s == "":
        return default
    if s in ("yes", "true", "1", "on", "y"):
        return True
    if s in ("no", "false", "0", "off", "n"):
        return False
    raise BDScriptError(f"expected yes/no, got '{v}'")


def to_int(v: Any, what: str = "number") -> int:
    try:
        return int(float(str(v).strip().replace(",", "")))
    except ValueError:
        raise BDScriptError(f"invalid {what} '{v}'")


def to_num(v: Any, what: str = "number") -> float:
    try:
        return float(str(v).strip().replace(",", ""))
    except ValueError:
        raise BDScriptError(f"invalid {what} '{v}'")


def fmt_num(x: float) -> str:
    if isinstance(x, float) and x.is_integer() and abs(x) < 1e18:
        return str(int(x))
    return repr(round(x, 12)).rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


_DUR = re.compile(r"(\d+(?:\.\d+)?)\s*(ms|s|sec|secs|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?|w|weeks?|mo|months?|y|years?)?",
                  re.IGNORECASE)
_UNIT = {"ms": 0.001, "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "m": 60, "min": 60, "mins": 60,
         "minute": 60, "minutes": 60, "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600, "d": 86400,
         "day": 86400, "days": 86400, "w": 604800, "week": 604800, "weeks": 604800, "mo": 2592000, "month": 2592000,
         "months": 2592000, "y": 31536000, "year": 31536000, "years": 31536000}


def seconds(text: str) -> float:
    """``10s``, ``5m``, ``1h30m``, ``2d``; a bare number is seconds."""
    text = str(text).strip()
    if not text:
        raise BDScriptError("empty duration")
    total, found = 0.0, False
    for num, unit in _DUR.findall(text):
        found = True
        total += float(num) * _UNIT.get((unit or "s").lower(), 1)
    if not found:
        raise BDScriptError(f"invalid duration '{text}'")
    return total


def human_duration(secs: float) -> str:
    secs = int(secs)
    parts = []
    for name, size in (("day", 86400), ("hour", 3600), ("minute", 60), ("second", 1)):
        if secs >= size:
            n, secs = divmod(secs, size)
            parts.append(f"{n} {name}{'s' if n != 1 else ''}")
    return ", ".join(parts) or "0 seconds"


def now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# -- lookups ------------------------------------------------------------------------------------------------

def user_id(ctx: Any, value: Optional[str]) -> str:
    v = (value or "").strip()
    return strip_mention(v) if v else ctx.author_id


def get_user(ctx: Any, value: Optional[str] = None, required: bool = True) -> Any:
    uid = user_id(ctx, value)
    if not value and ctx.author is not None:
        return ctx.author
    u = None
    if ctx.guild is not None:
        u = ctx.guild.get_member(uid)
    if u is None:
        u = ctx.client.get_user(uid)
    if u is None and required:
        raise BDScriptError(f"invalid user ID '{uid}'")
    return u


def get_member(ctx: Any, value: Optional[str] = None, guild: Any = None, required: bool = True) -> Any:
    g = guild or ctx.guild
    if g is None:
        if required:
            raise BDScriptError("this only works in a community")
        return None
    uid = user_id(ctx, value)
    m = g.get_member(uid)
    if m is None and required:
        raise BDScriptError(f"invalid user ID '{uid}'")
    return m


def get_guild(ctx: Any, value: Optional[str] = None, required: bool = True) -> Any:
    v = (value or "").strip()
    if not v:
        if ctx.guild is None and required:
            raise BDScriptError("this only works in a community")
        return ctx.guild
    g = ctx.client.get_community(v)
    if g is None and required:
        raise BDScriptError(f"invalid server ID '{v}'")
    return g


def get_channel(ctx: Any, value: Optional[str] = None, required: bool = True) -> Any:
    v = strip_mention(value or "")
    if not v:
        return ctx.channel
    c = ctx.client.get_channel(v)
    if c is None and ctx.guild is not None:
        c = next((x for x in getattr(ctx.guild, "channels", []) if getattr(x, "name", None) == v), None)
    if c is None and required:
        raise BDScriptError(f"invalid channel ID '{v}'")
    return c


def get_role(ctx: Any, value: str, guild: Any = None, required: bool = True) -> Any:
    g = guild or ctx.guild
    if g is None:
        raise BDScriptError("this only works in a community")
    v = strip_mention(value)
    r = g.get_role(v)
    if r is None:
        r = next((x for x in g.roles if x.name == value.strip() or x.name.lower() == value.strip().lower()), None)
    if r is None and required:
        raise BDScriptError(f"invalid role '{value}'")
    return r


def ids(items: Iterable[Any]) -> List[str]:
    return [str(getattr(i, "id", i)) for i in items]


def ts(dt: Optional[datetime.datetime], unit: str = "s") -> str:
    if dt is None:
        return ""
    v = dt.timestamp()
    return str(int(v * 1000)) if unit in ("ms", "milliseconds") else str(int(v))


def bdfd_date(dt: Optional[datetime.datetime]) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""
