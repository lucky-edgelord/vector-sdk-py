"""Date and time."""

from __future__ import annotations

import datetime
import time

from ..registry import BDScriptError, fn
from ..util import to_int

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

# Go reference layout tokens (BDFD formats use Go's) -> strftime
_GO = [("2006", "%Y"), ("January", "%B"), ("Monday", "%A"), ("Jan", "%b"), ("Mon", "%a"), ("MST", "%Z"),
       ("-07:00", "%:z"), ("-0700", "%z"), ("15", "%H"), ("06", "%y"), ("01", "%m"), ("02", "%d"), ("03", "%I"),
       ("04", "%M"), ("05", "%S"), ("PM", "%p"), ("_2", "%e"), ("1", "%-m"), ("2", "%-d"), ("3", "%-I"),
       ("4", "%-M"), ("5", "%-S")]


def go_format(dt: datetime.datetime, layout: str) -> str:
    out, i = [], 0
    while i < len(layout):
        for tok, rep in _GO:
            if layout.startswith(tok, i):
                if rep == "%:z":
                    z = dt.strftime("%z")
                    out.append(z[:3] + ":" + z[3:] if z else "")
                else:
                    try:
                        out.append(dt.strftime(rep))
                    except ValueError:
                        out.append(dt.strftime(rep.replace("-", "")).lstrip("0") or "0")
                i += len(tok)
                break
        else:
            out.append(layout[i])
            i += 1
    return "".join(out)


def _now(ctx) -> datetime.datetime:
    tz = ctx.extras.get("timezone")
    if tz and ZoneInfo is not None:
        return datetime.datetime.now(ZoneInfo(tz))
    return datetime.datetime.now(datetime.timezone.utc)


@fn("time", min_args=1, brackets="required")
def _time(ctx, tz):
    if ZoneInfo is None:
        raise BDScriptError("timezones need Python 3.9+")
    try:
        ZoneInfo(tz.strip())
    except Exception:
        raise BDScriptError(f"invalid timezone '{tz}'")
    ctx.extras["timezone"] = tz.strip()
    return ""


@fn("date", brackets="none")
def _date(ctx):
    return _now(ctx).strftime("%m/%d/%Y")


@fn("day", brackets="none")
def _day(ctx):
    return str(_now(ctx).day)


@fn("month", brackets="none")
def _month(ctx):
    return str(_now(ctx).month)


@fn("year", brackets="none")
def _year(ctx):
    return str(_now(ctx).year)


@fn("hour", brackets="none")
def _hour(ctx):
    return f"{_now(ctx).hour:02d}"


@fn("minute", brackets="none")
def _minute(ctx):
    return f"{_now(ctx).minute:02d}"


@fn("second", brackets="none")
def _second(ctx):
    return f"{_now(ctx).second:02d}"


@fn("getTimestamp")
@fn("getTimestampComplex")
def _timestamp(ctx, unit="s"):
    t = time.time_ns()
    u = unit.strip().lower() or "s"
    if u in ("s", "sec", "seconds"):
        return str(t // 10 ** 9)
    if u in ("ms", "milliseconds"):
        return str(t // 10 ** 6)
    if u in ("us", "µs", "microseconds"):
        return str(t // 10 ** 3)
    if u in ("ns", "nanoseconds"):
        return str(t)
    raise BDScriptError(f"invalid time unit '{unit}' (s, ms, us, ns)")


def id_time(value: str) -> datetime.datetime:
    """Creation time for an ID. Discord snowflakes encode it; Vector IDs don't, so we use the cache."""
    v = value.strip()
    if v.isdigit() and 15 <= len(v) <= 20:
        ms = (int(v) >> 22) + 1420070400000
        return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc)
    raise BDScriptError(f"can't read a creation time from ID '{value}'")


@fn("creationDate", min_args=1, brackets="required")
def _creation(ctx, oid, layout=""):
    from ..util import strip_mention, get_user
    v = strip_mention(oid)
    dt = None
    u = ctx.client.get_user(v) if hasattr(ctx.client, "get_user") else None
    if u is not None and getattr(u, "created_at", None):
        dt = u.created_at
    m = ctx.client._connection._messages.get(v) if hasattr(ctx.client, "_connection") and hasattr(ctx.client._connection, "_messages") else None
    if dt is None and m is not None:
        dt = getattr(m, "created_at", None)
    if dt is None:
        dt = id_time(v)
    return go_format(dt, layout) if layout else dt.strftime("%a %b %d %Y %H:%M:%S GMT%z")


@fn("dateStamp", brackets="optional")
def _datestamp(ctx, *a):
    """D.js-BDscript: current time in milliseconds."""
    return str(int(time.time() * 1000))


@fn("parseTime", min_args=1, brackets="required")
def _parsetime(ctx, ms):
    """D.js-BDscript: milliseconds -> "1h 2m 3s"."""
    from ..util import human_duration
    return human_duration(to_int(ms) / 1000)


@fn("parseDuration", min_args=1, brackets="required")
def _parseduration(ctx, text):
    """``10m`` -> seconds (modern helper)."""
    from ..util import seconds
    return str(int(seconds(text)))


@fn("formatTime", min_args=1, brackets="required")
def _formattime(ctx, ts, layout="2006-01-02 15:04:05"):
    """``$formatTime[unix seconds;(Go layout)]`` (modern helper)."""
    dt = datetime.datetime.fromtimestamp(int(float(ts)), datetime.timezone.utc)
    if ctx.extras.get("timezone") and ZoneInfo:
        dt = dt.astimezone(ZoneInfo(ctx.extras["timezone"]))
    return go_format(dt, layout)
