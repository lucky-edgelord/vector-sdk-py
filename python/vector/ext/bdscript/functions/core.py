"""Control flow, scripting features and response flags."""

from __future__ import annotations

import asyncio
import time

from ..conditions import check
from ..parser import escape, unescape
from ..registry import BDScriptError, StopExecution, fn
from ..util import seconds, to_int


def _ev():
    from ..interpreter import evaluate
    return evaluate


# -- block markers (handled by the parser; a stray one is a no-op) ------------------------------------------
@fn("elseif", brackets="required")
@fn("else", brackets="none")
@fn("endif", brackets="none")
@fn("try", brackets="none")
@fn("catch", brackets="none")
@fn("endtry", brackets="none")
@fn("endasync", brackets="none")
@fn("endloop", brackets="none")
def _marker(ctx, *a):
    return ""


@fn("async", brackets="required")
def _async_marker(ctx, *a):
    return ""


@fn("c", brackets="required", lazy=True)
async def _comment(ctx, node, args):
    return ""


@fn("if", lazy=True, brackets="required")
async def _inline_if(ctx, node, args):
    """D.js-BDscript inline form ``$if[cond;then;else]`` (the block form is handled by the parser)."""
    ev = _ev()
    cond = await ev(ctx, args[0]) if args else ""
    if check(cond):
        return await ev(ctx, args[1]) if len(args) > 1 else ""
    return await ev(ctx, args[2]) if len(args) > 2 else ""


@fn("await", brackets="required", min_args=1)
async def _await(ctx, name):
    t = ctx.async_tasks.get(name.strip())
    if t is None:
        raise BDScriptError(f"no async scope named '{name}'")
    await t
    return ""


@fn("stop", brackets="none")
def _stop(ctx):
    raise StopExecution()


@fn("eval", lazy=True)
async def _eval(ctx, node, args):
    """``$eval[code]`` runs BDScript code; the fork's bare ``$eval`` evaluates the message arguments."""
    from ..interpreter import compile_code, evaluate

    if args:
        code = unescape(await evaluate(ctx, args[0]), False)
    else:
        code = " ".join(ctx.args)
    ctx.depth += 1
    if ctx.depth > 20:
        raise BDScriptError("$eval nested too deeply")
    try:
        return await evaluate(ctx, compile_code(code))
    finally:
        ctx.depth -= 1


@fn("optOff", lazy=True)
async def _optoff(ctx, node, args):
    return await _ev()(ctx, args[0]) if args else ""


@fn("var", min_args=1, brackets="required")
def _var(ctx, name, *value):
    if value:
        ctx.vars[name] = ";".join(value)
        return ""
    if name not in ctx.vars:
        raise BDScriptError(f"variable '{name}' not found")
    return ctx.vars[name]


@fn("let", min_args=2, brackets="required")
def _let(ctx, name, value, *rest):
    ctx.keywords[name] = ";".join((value,) + rest)
    return ""


@fn("get", min_args=1, brackets="required")
def _get(ctx, name):
    if name not in ctx.keywords:
        raise BDScriptError(f"keyword '{name}' not found")
    return ctx.keywords[name]


@fn("checkCondition", min_args=1, brackets="required")
def _checkcondition(ctx, cond):
    return check(cond)


@fn("and", min_args=1, brackets="required")
def _and(ctx, *conds):
    return all(check(c) for c in conds)


@fn("or", min_args=1, brackets="required")
def _or(ctx, *conds):
    return any(check(c) for c in conds)


@fn("onlyIf", min_args=1, brackets="required", lazy=True)
async def _onlyif(ctx, node, args):
    ev = _ev()
    cond = await ev(ctx, args[0])
    if not check(cond):
        msg = await ev(ctx, args[1]) if len(args) > 1 else ""
        raise StopExecution(msg or "")
    return ""


@fn("argsCheck", min_args=1, brackets="required")
def _argscheck(ctx, how, msg=""):
    how = how.strip().replace(" ", "")
    n = len(ctx.args)
    for op, f in ((">=", lambda a, b: a >= b), ("<=", lambda a, b: a <= b), ("==", lambda a, b: a == b),
                  ("!=", lambda a, b: a != b), (">", lambda a, b: a >= b), ("<", lambda a, b: a <= b)):
        if how.startswith(op):
            ok = f(n, to_int(how[len(op):]))
            break
    else:
        ok = n == to_int(how)
    if not ok:
        raise StopExecution(msg or "")
    return ""


@fn("error", "handleError", min_args=1, brackets="required")
def _error(ctx, kind):
    if kind not in ("command", "message", "source", "row", "column", "function", "error"):
        raise BDScriptError(f"invalid error type '{kind}'")
    return ctx.error.get(kind, "")


@fn("suppressErrors")
def _suppress(ctx, *msg):
    ctx.suppress_errors = ";".join(msg)
    return ""


@fn("suppressErrorsComplex")
def _suppress_complex(ctx, *msg):
    ctx.suppress_errors = ";".join(msg)
    return ""


@fn("embedSuppressErrors", min_args=1)
def _embed_suppress(ctx, title="", description="", color="", footer="", image=""):
    from ....embeds import Embed
    from .embeds import colour_value

    e = Embed(title=title or None, description=description or None)
    if color:
        e.colour = colour_value(color)
    if footer:
        e.set_footer(text=footer)
    if image:
        e.set_image(url=image)
    ctx.suppress_errors = ""
    ctx.embed_suppress_errors = {"embed": e}
    return ""


@fn("suppressErrorLogging", brackets="none")
def _suppress_logging(ctx):
    ctx.extras["no_error_log"] = True
    return ""


@fn("nomention", brackets="none")
def _nomention(ctx):
    ctx.response.mention_author = False
    return ""


@fn("disableInnerSpaceRemoval", brackets="none")
def _disable_isr(ctx):
    ctx.inner_space_removal = False
    return ""


@fn("disableSpecialEscaping", brackets="none")
def _disable_se(ctx):
    ctx.special_escaping = False
    return ""


@fn("alternativeParsing", brackets="none")
def _altparsing(ctx):
    return ""


@fn("unescape", min_args=0)
def _unescape(ctx, *text):
    return unescape(";".join(text))


@fn("scriptLanguage", brackets="none")
def _lang(ctx):
    return "BDScript 2"


@fn("executionTime", brackets="none")
def _exectime(ctx):
    return str(round((time.perf_counter() - ctx.started) * 1000, 2))


@fn("ping", brackets="none")
def _ping(ctx):
    lat = getattr(ctx.client, "latency", 0) or 0
    return str(int(lat * 1000))


@fn("uptime", brackets="optional")
def _uptime(ctx, unit=""):
    from ..util import human_duration
    secs = time.time() - ctx.bot.started_at
    if unit.lower() in ("s", "seconds"):
        return str(int(secs))
    if unit.lower() in ("ms", "milliseconds"):
        return str(int(secs * 1000))
    return human_duration(secs)


@fn("botNode", brackets="none")
def _botnode(ctx):
    return "vector-sdk-py"


@fn("nodeVersion", brackets="none")
@fn("nodeVersionComplex", brackets="optional")
def _nodeversion(ctx, *a):
    import platform
    return f"Python {platform.python_version()}"


@fn("wait", min_args=1, brackets="required")
async def _wait(ctx, duration):
    await asyncio.sleep(min(seconds(duration), 3600))
    return ""


@fn("log", brackets="required", status="full", note="logs to the bot's logger")
def _log(ctx, *text):
    import logging
    logging.getLogger("vector.bdscript.log").info(";".join(text))
    ctx.bot.log_lines.append(";".join(text))
    return ""


@fn("logQuota", brackets="none")
def _logquota(ctx):
    return "unlimited"


@fn("forEach", min_args=2, brackets="required", lazy=True)
async def _foreach(ctx, node, args):
    if len(args) < 2:
        raise BDScriptError("usage: $forEach[items;code;(separator)]")
    """D.js-BDscript: ``$forEach[a,b,c;code using $get[value] and $get[index];(separator)]`` (output joined)."""
    from ..interpreter import evaluate

    items_text = await evaluate(ctx, args[0])
    sep = await evaluate(ctx, args[2]) if len(args) > 2 else ","
    out = []
    for i, item in enumerate(items_text.split(sep) if items_text else []):
        ctx.keywords["value"], ctx.keywords["index"] = item.strip(), str(i + 1)
        out.append(await evaluate(ctx, args[1]))
    return "".join(out)


@fn("loop", min_args=2, brackets="required", lazy=True)
async def _loop(ctx, node, args):
    """``$loop[times;code]``, with ``$get[index]`` (a modern convenience)."""
    from ..interpreter import evaluate

    if len(args) < 2:
        raise BDScriptError("usage: $loop[times;code]")
    n = min(to_int(await evaluate(ctx, args[0])), 1000)
    out = []
    for i in range(n):
        ctx.keywords["index"] = str(i + 1)
        out.append(await evaluate(ctx, args[1]))
    return "".join(out)


@fn("tts", brackets="none")
def _tts(ctx):
    ctx.response.tts = True
    return ""


@fn("ephemeral", brackets="none")
def _ephemeral(ctx):
    ctx.response.ephemeral = True
    return ""


@fn("defer", brackets="optional")
async def _defer(ctx, *a):
    ctx.response.defer = True
    if ctx.interaction is not None and hasattr(ctx.interaction.response, "defer"):
        try:
            await ctx.interaction.response.defer()
        except Exception:
            pass
    return ""


@fn("allowMention", brackets="none")
def _allowmention(ctx):
    ctx.response.allowed_users = None
    ctx.response.allowed_roles = None
    return ""


@fn("allowUserMentions", brackets="optional")
def _allowusers(ctx, *ids):
    ctx.response.allowed_users = [i for i in ids if i]
    return ""


@fn("allowRoleMentions", brackets="optional")
def _allowroles(ctx, *ids):
    ctx.response.allowed_roles = [i for i in ids if i]
    return ""


@fn("enableDecimals", brackets="none")
def _decimals(ctx):
    ctx.extras["decimals"] = True
    return ""


@fn("exec", brackets="required", status="partial", note="disabled unless BDBot(allow_exec=True)")
async def _exec(ctx, *cmd):
    if not getattr(ctx.bot, "allow_exec", False):
        raise BDScriptError("$exec is disabled (BDBot(allow_exec=True) to enable)")
    proc = await asyncio.create_subprocess_shell(";".join(cmd), stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.STDOUT)
    out, _ = await asyncio.wait_for(proc.communicate(), 60)
    return escape(out.decode(errors="replace")[:4000])


@fn("data", min_args=1, brackets="required")
def _data(ctx, key, *value):
    """D.js-BDscript ``$data[key]``: values attached to the run (e.g. ``$forEach`` / handler data)."""
    if value:
        ctx.extras.setdefault("data", {})[key] = ";".join(value)
        return ""
    d = ctx.extras.get("data", {})
    if key not in d:
        raise BDScriptError(f"no data '{key}'")
    return str(d[key])
