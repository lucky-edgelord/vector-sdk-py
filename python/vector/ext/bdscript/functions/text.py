"""Message arguments, text manipulation, text splitting."""

from __future__ import annotations

import random
import re
import string
import urllib.parse

from ..parser import escape
from ..registry import BDScriptError, fn
from ..util import fmt_num, strip_mention, to_int, to_num

_LINK = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def _msg_text(ctx) -> str:
    return " ".join(ctx.args)


@fn("message")
def _message(ctx, index="", name=""):
    """``$message`` (all arguments), ``$message[n]`` (nth argument), ``$message[>]`` (last); for slash commands
    ``$message[;name]`` or ``$message[name]`` reads an option."""
    opts = ctx.extras.get("options") or {}
    if name and name in opts:
        return escape(str(opts[name]))
    if index and not index.strip().lstrip("-").isdigit() and index.strip() != ">":
        return escape(str(opts.get(index, "")))
    if index == "":
        return escape(_msg_text(ctx))
    if index.strip() == ">":
        return escape(ctx.args[-1]) if ctx.args else ""
    i = to_int(index)
    if i <= 0:
        return escape(_msg_text(ctx))
    return escape(ctx.args[i - 1]) if i <= len(ctx.args) else ""


fn("messageComplex")(_message)


def _no_mentions(text: str) -> str:
    return re.sub(r"<[@#][!&]?[^>]+>", "", text).strip()


@fn("noMentionMessage")
@fn("noMentionMessageComplex")
def _nomention_message(ctx, index=""):
    args = [a for a in ctx.args if not re.fullmatch(r"<[@#][!&]?[^>]+>", a)]
    if index == "":
        return escape(_no_mentions(" ".join(args)))
    if index.strip() == ">":
        return escape(args[-1]) if args else ""
    i = to_int(index)
    return escape(args[i - 1]) if 0 < i <= len(args) else ""


@fn("argCount")
def _argcount(ctx, *text):
    t = ";".join(text) if text else _msg_text(ctx)
    return str(len(t.split())) if t.strip() else "0"


@fn("replaceText", min_args=3, brackets="required")
def _replace(ctx, text, sample, new, amount="-1"):
    n = to_int(amount) if amount.strip() else -1
    return text.replace(sample, new, n if n >= 0 else -1)


@fn("toLowercase", brackets="required")
def _lower(ctx, *t):
    return ";".join(t).lower()


@fn("toUppercase", brackets="required")
def _upper(ctx, *t):
    return ";".join(t).upper()


@fn("toTitleCase", brackets="required")
def _title(ctx, *t):
    return " ".join(w[:1].upper() + w[1:].lower() for w in ";".join(t).split(" "))


@fn("toTitle", brackets="required")
def _totitle(ctx, text, sep=" "):
    """D.js-BDscript ``$toTitle[text;(separator)]``."""
    return (sep or " ").join(w[:1].upper() + w[1:] for w in text.split(sep or " "))


@fn("cropText", min_args=2, brackets="required")
def _crop(ctx, text, maxc, ending=""):
    m = to_int(maxc)
    return text if len(text) <= m else text[:m] + ending


@fn("charCount")
def _charcount(ctx, *t):
    return str(len(";".join(t) if t else _msg_text(ctx)))


@fn("linesCount")
def _lines(ctx, *t):
    text = ";".join(t) if t else _msg_text(ctx)
    return str(len(text.split("\n"))) if text else "0"


@fn("byteCount", brackets="required")
def _bytes(ctx, *t):
    return str(len(";".join(t).encode()))


@fn("trimContent", brackets="none")
def _trimcontent(ctx):
    return escape(_msg_text(ctx).strip())


@fn("trimSpace", brackets="required")
def _trimspace(ctx, *t):
    return ";".join(t).strip()


@fn("randomString", min_args=1, brackets="required")
def _randstr(ctx, length):
    n = max(0, min(to_int(length), 2000))
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(n))


@fn("randomText", min_args=1, brackets="required")
def _randtext(ctx, *options):
    return random.choice(options)


@fn("removeContains", min_args=1, brackets="required")
def _removecontains(ctx, *words):
    amount = -1
    if len(words) > 1 and words[-1].strip().lstrip("-").isdigit():
        amount, words = int(words[-1]), words[:-1]
    text = _msg_text(ctx)
    for w in words:
        text = text.replace(w, "", amount if amount >= 0 else -1)
    return escape(text)


@fn("removeLinks")
@fn("removeLinksComplex")
def _removelinks(ctx, *text):
    if text:
        return _LINK.sub("", ";".join(text)).strip()
    ctx.response.remove_links = True
    return ""


@fn("url", min_args=1, brackets="required")
def _url(ctx, mode, *text):
    t = ";".join(text)
    m = mode.strip().lower()
    if m.startswith(("http://", "https://")):  # $url[url;(index)]: embed title link
        ctx.response.embed(t if t.strip().isdigit() else "").url = mode.strip()
        return ""
    if m == "encode":
        return urllib.parse.quote(t, safe="")
    if m == "decode":
        return urllib.parse.unquote(t)
    raise BDScriptError(f"invalid mode '{mode}' (encode/decode)")


@fn("numberSeparator", min_args=1, brackets="required")
def _numsep(ctx, number, sep=","):
    x = to_num(number)
    whole, _, frac = fmt_num(x).partition(".")
    neg = whole.startswith("-")
    whole = whole.lstrip("-")
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    out = (sep if sep != "" else ",").join(groups)
    return ("-" if neg else "") + out + ("." + frac if frac else "")


@fn("isNumber", brackets="required")
def _isnumber(ctx, *v):
    try:
        float(";".join(v).strip())
        return True
    except ValueError:
        return False


@fn("isInteger", brackets="required")
def _isinteger(ctx, *v):
    return bool(re.fullmatch(r"[+-]?\d+", ";".join(v).strip()))


@fn("isBoolean", brackets="required")
def _isbool(ctx, *v):
    return ";".join(v).strip().lower() in ("true", "false", "yes", "no")


@fn("isValidHex", brackets="required")
def _ishex(ctx, *v):
    return bool(re.fullmatch(r"#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", ";".join(v).strip()))


@fn("checkContains", min_args=2, brackets="required")
def _checkcontains(ctx, text, *phrases):
    return any(p in text for p in phrases)


@fn("sort", min_args=1, brackets="required")
def _sort(ctx, *args):
    """``$sort[n;n;...;(asc/desc);(amount);(separator)]``."""
    items = list(args)
    direction, amount, sep = "asc", None, ", "
    tail = []
    while items and len(tail) < 3 and not _isnum(items[-1]):
        tail.insert(0, items.pop())
    for t in tail:
        if t.lower() in ("asc", "desc", "ascending", "descending"):
            direction = t.lower()
        elif t:
            sep = t
    nums = []
    for x in items:
        if x.strip() == "":
            continue
        nums.append(to_num(x))
    nums.sort(reverse=direction.startswith("desc"))
    return sep.join(fmt_num(n) for n in nums[: amount or None])


def _isnum(x: str) -> bool:
    try:
        float(x)
        return True
    except ValueError:
        return False


@fn("repeatMessage", min_args=2, brackets="required")
def _repeat(ctx, amount, *text):
    return ";".join(text) * max(0, min(to_int(amount), 2000))


# -- text splitting ----------------------------------------------------------------------------------------
@fn("textSplit", min_args=1, brackets="required")
def _textsplit(ctx, text, sep=""):
    ctx.split = list(text) if sep == "" else text.split(sep)
    return ""


@fn("splitText", min_args=1, brackets="required")
def _splittext(ctx, index):
    if index.strip() == "<":
        return ctx.split[0] if ctx.split else ""
    if index.strip() == ">":
        return ctx.split[-1] if ctx.split else ""
    i = to_int(index)
    return ctx.split[i - 1] if 0 < i <= len(ctx.split) else ""


@fn("getTextSplitIndex", min_args=1, brackets="required")
def _splitindex(ctx, value):
    return str(ctx.split.index(value) + 1) if value in ctx.split else "-1"


@fn("getTextSplitLength", brackets="none")
def _splitlen(ctx):
    return str(len(ctx.split))


@fn("joinSplitText", brackets="required")
def _joinsplit(ctx, sep=""):
    return sep.join(ctx.split)


@fn("editSplitText", min_args=2, brackets="required")
def _editsplit(ctx, index, value):
    i = to_int(index)
    if not 0 < i <= len(ctx.split):
        raise BDScriptError(f"index {i} out of range")
    ctx.split[i - 1] = value
    return ""


@fn("removeSplitTextElement", min_args=1, brackets="required")
def _removesplit(ctx, index):
    i = to_int(index)
    if 0 < i <= len(ctx.split):
        ctx.split.pop(i - 1)
    return ""


# -- mentions ----------------------------------------------------------------------------------------------
def _mention_ids(ctx, kind: str):
    msg = ctx.message
    if msg is None:
        return []
    if kind == "user":
        return [str(u.id) for u in getattr(msg, "mentions", [])] or \
            [strip_mention(a) for a in ctx.args if re.fullmatch(r"<@!?[^>&]+>", a)]
    if kind == "channel":
        return [str(c.id) for c in getattr(msg, "channel_mentions", [])]
    return [str(r.id) for r in getattr(msg, "role_mentions", [])]


@fn("mentioned", min_args=1, brackets="required")
def _mentioned(ctx, n, return_author="no"):
    from ..util import truthy
    ids = _mention_ids(ctx, "user")
    i = 1 if n.strip() == ">" else to_int(n)
    if n.strip() == ">":
        return ids[-1] if ids else (ctx.author_id if truthy(return_author) else "")
    return ids[i - 1] if 0 < i <= len(ids) else (ctx.author_id if truthy(return_author) else "")


@fn("mentionedChannels", min_args=1, brackets="required")
def _mentionedchannels(ctx, n, return_current="no"):
    from ..util import truthy
    ids = _mention_ids(ctx, "channel")
    i = to_int(n)
    return ids[i - 1] if 0 < i <= len(ids) else (ctx.channel_id if truthy(return_current) else "")


@fn("mentionedRoles", min_args=1, brackets="required")
def _mentionedroles(ctx, n):
    ids = _mention_ids(ctx, "role")
    i = to_int(n)
    return ids[i - 1] if 0 < i <= len(ids) else ""


@fn("isMentioned", min_args=1, brackets="required")
def _ismentioned(ctx, uid):
    return strip_mention(uid) in _mention_ids(ctx, "user")
