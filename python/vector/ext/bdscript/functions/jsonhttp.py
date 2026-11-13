"""JSON and HTTP functions (BDScript 2)."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request

from ..parser import escape, unescape
from ..registry import BDScriptError, fn
from ..util import to_int


def _parse_value(v: str):
    s = v.strip()
    if s in ("true", "false"):
        return s == "true"
    if s == "null":
        return None
    try:
        return int(s) if s.lstrip("-").isdigit() else float(s) if s.replace(".", "", 1).lstrip("-").isdigit() else v
    except ValueError:
        return v


def _key(k: str):
    return int(k) if k.strip().lstrip("-").isdigit() else k


def _walk(root, keys, create=False):
    cur = root
    for k in keys:
        kk = _key(k)
        if isinstance(cur, list) and isinstance(kk, int):
            if not -len(cur) <= kk < len(cur):
                if create:
                    raise BDScriptError(f"index {kk} out of range")
                return None, False
            cur = cur[kk]
        elif isinstance(cur, dict):
            if k not in cur:
                if not create:
                    return None, False
                cur[k] = {}
            cur = cur[k]
        else:
            return None, False
    return cur, True


def _dump(v) -> str:
    if isinstance(v, str):
        return v
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (int, float)):
        return str(v)
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def _root(ctx):
    if ctx.json is None:
        ctx.json = {}
    return ctx.json


@fn("jsonParse", min_args=1, brackets="required")
def _jsonparse(ctx, *text):
    try:
        ctx.json = json.loads(unescape(";".join(text), False))
    except ValueError as e:
        raise BDScriptError(f"invalid JSON: {e}")
    return ""


@fn("json", brackets="required")
def _json(ctx, *keys):
    keys = [k for k in keys if k != ""] if keys != ("",) else []
    v, ok = _walk(_root(ctx), keys)
    return escape(_dump(v)) if ok else ""


@fn("jsonExists", min_args=1, brackets="required")
def _jsonexists(ctx, *keys):
    return _walk(_root(ctx), keys)[1]


def _set(ctx, keys, value):
    if not keys:
        raise BDScriptError("no key")
    parent, ok = _walk(_root(ctx), keys[:-1], create=True)
    last = _key(keys[-1])
    if isinstance(parent, list) and isinstance(last, int):
        parent[last] = value
    elif isinstance(parent, dict):
        parent[keys[-1]] = value
    else:
        raise BDScriptError("can't set a key on a non-object")


@fn("jsonSet", min_args=2, brackets="required")
def _jsonset(ctx, *args):
    *keys, value = args
    _set(ctx, keys, _parse_value(value))
    return ""


@fn("jsonSetString", min_args=2, brackets="required")
def _jsonsetstring(ctx, *args):
    *keys, value = args
    _set(ctx, keys, value)
    return ""


@fn("jsonUnset", min_args=1, brackets="required")
def _jsonunset(ctx, *keys):
    parent, ok = _walk(_root(ctx), keys[:-1])
    if ok:
        last = _key(keys[-1])
        if isinstance(parent, dict):
            parent.pop(keys[-1], None)
        elif isinstance(parent, list) and isinstance(last, int) and -len(parent) <= last < len(parent):
            parent.pop(last)
    return ""


@fn("jsonClear", brackets="none")
def _jsonclear(ctx):
    ctx.json = {}
    return ""


@fn("jsonStringify", brackets="none")
def _jsonstringify(ctx):
    return escape(json.dumps(_root(ctx), ensure_ascii=False, separators=(",", ":")))


@fn("jsonPretty")
def _jsonpretty(ctx, indent="2"):
    return escape(json.dumps(_root(ctx), ensure_ascii=False, indent=to_int(indent or "2")))


def _array(ctx, keys, create=False):
    if not keys and isinstance(ctx.json, list):
        return ctx.json
    v, ok = _walk(_root(ctx), keys)
    if not ok and create:
        _set(ctx, keys, [])
        v, ok = _walk(_root(ctx), keys)
    if not isinstance(v, list):
        raise BDScriptError(f"'{'.'.join(keys)}' isn't an array")
    return v


@fn("jsonArray", min_args=1, brackets="required")
def _jsonarray(ctx, *keys):
    _set(ctx, list(keys), [])
    return ""


@fn("jsonArrayCount", min_args=1, brackets="required")
def _jsonarraycount(ctx, *keys):
    v, ok = _walk(_root(ctx), keys)
    return str(len(v)) if ok and isinstance(v, list) else "0"


@fn("jsonArrayIndex", min_args=2, brackets="required")
def _jsonarrayindex(ctx, *args):
    *keys, value = args
    arr = _array(ctx, keys)
    target = _parse_value(value)
    for i, x in enumerate(arr):
        if x == target or _dump(x) == value:
            return str(i)
    return "-1"


@fn("jsonArrayAppend", min_args=2, brackets="required")
def _jsonarrayappend(ctx, *args):
    *keys, value = args
    _array(ctx, keys, create=True).append(_parse_value(value))
    return ""


@fn("jsonArrayUnshift", min_args=2, brackets="required")
def _jsonarrayunshift(ctx, *args):
    *keys, value = args
    _array(ctx, keys, create=True).insert(0, _parse_value(value))
    return ""


@fn("jsonArrayPop", min_args=1, brackets="required")
def _jsonarraypop(ctx, *keys):
    arr = _array(ctx, keys)
    return escape(_dump(arr.pop())) if arr else ""


@fn("jsonArrayShift", min_args=1, brackets="required")
def _jsonarrayshift(ctx, *keys):
    arr = _array(ctx, keys)
    return escape(_dump(arr.pop(0))) if arr else ""


@fn("jsonArraySort", min_args=1, brackets="required")
def _jsonarraysort(ctx, *keys):
    arr = _array(ctx, keys)
    try:
        arr.sort()
    except TypeError:
        arr.sort(key=_dump)
    return ""


@fn("jsonArrayReverse", min_args=1, brackets="required")
def _jsonarrayreverse(ctx, *keys):
    _array(ctx, keys).reverse()
    return ""


@fn("jsonJoinArray", min_args=2, brackets="required")
def _jsonjoinarray(ctx, *args):
    *keys, sep = args
    return escape(sep.join(_dump(x) for x in _array(ctx, keys)))


# -- HTTP --------------------------------------------------------------------------------------------------
@fn("httpAddHeader", min_args=2, brackets="required")
def _httpaddheader(ctx, name, value):
    ctx.http["headers"][name] = value
    return ""


async def _request(ctx, method, url, body=None):
    if not getattr(ctx.bot, "allow_http", True):
        raise BDScriptError("HTTP functions are disabled for this bot")
    n = ctx.extras.get("http_count", 0) + 1
    if n > ctx.bot.http_limit:
        raise BDScriptError(f"at most {ctx.bot.http_limit} HTTP requests per command")
    ctx.extras["http_count"] = n
    headers = {"User-Agent": "vector-sdk-py BDScript", **ctx.http["headers"]}
    data = None
    if body is not None:
        data = unescape(body, False).encode()
        headers.setdefault("Content-Type", "application/json" if body.strip()[:1] in "{[" else "text/plain")

    def go():
        req = urllib.request.Request(url.strip(), data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=35) as r:
                return r.status, r.read(5 * 1024 * 1024).decode(errors="replace"), dict(r.headers.items())
        except urllib.error.HTTPError as e:
            return e.code, e.read(1024 * 1024).decode(errors="replace"), dict(e.headers.items())
        except Exception as e:
            raise BDScriptError(f"request failed: {e}")

    status, text, rheaders = await asyncio.get_running_loop().run_in_executor(None, go)
    ctx.http["status"], ctx.http["result"] = status, text
    ctx.http["response_headers"] = {k.lower(): v for k, v in rheaders.items()}
    try:
        ctx.http["json"] = json.loads(text)
    except ValueError:
        ctx.http["json"] = None
    return ""


@fn("httpGet", min_args=1, brackets="required")
async def _httpget(ctx, url):
    return await _request(ctx, "GET", url)


@fn("httpPost", min_args=1, brackets="required")
async def _httppost(ctx, url, *body):
    return await _request(ctx, "POST", url, ";".join(body))


@fn("httpPut", min_args=1, brackets="required")
async def _httpput(ctx, url, *body):
    return await _request(ctx, "PUT", url, ";".join(body))


@fn("httpPatch", min_args=1, brackets="required")
async def _httppatch(ctx, url, *body):
    return await _request(ctx, "PATCH", url, ";".join(body))


@fn("httpDelete", min_args=1, brackets="required")
async def _httpdelete(ctx, url, *body):
    return await _request(ctx, "DELETE", url, ";".join(body) if body else None)


@fn("httpResult")
def _httpresult(ctx, *keys):
    keys = [k for k in keys if k != ""]
    if not keys:
        return escape(ctx.http["result"])
    data = ctx.http.get("json")
    if data is None:
        return ""
    v, ok = _walk(data, keys)
    return escape(_dump(v)) if ok else ""


@fn("httpStatus", brackets="none")
def _httpstatus(ctx):
    return str(ctx.http["status"])


@fn("httpRemoveHeader", min_args=1, brackets="required")
def _httpremoveheader(ctx, name):
    for k in list(ctx.http["headers"]):
        if k.lower() == name.strip().lower():
            del ctx.http["headers"][k]
    return ""


@fn("httpGetHeader", min_args=1, brackets="required")
def _httpgetheader(ctx, name):
    return escape(ctx.http.get("response_headers", {}).get(name.strip().lower(), ""))
