"""Evaluates parsed BDScript and sends the result."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from .context import Context
from .parser import Async, Call, If, Loop, Node, ParseError, Parser, Text, Try, escape, unescape
from .registry import FUNCTIONS, MAX_ITERATIONS, BDScriptError, BreakLoop, ContinueLoop, StopExecution, parser_names

log = logging.getLogger("vector.bdscript")

_PARSER: Optional[Parser] = None
_PARSER_SIZE = 0
_CACHE: Dict[str, List[Node]] = {}


def parser() -> Parser:
    global _PARSER, _PARSER_SIZE
    if _PARSER is None or _PARSER_SIZE != len(FUNCTIONS):
        from . import functions  # noqa: F401  (registers everything)

        _PARSER = Parser(parser_names())
        _PARSER_SIZE = len(FUNCTIONS)
        _CACHE.clear()
    return _PARSER


def compile_code(code: str) -> List[Node]:
    nodes = _CACHE.get(code)
    if nodes is None:
        nodes = parser().parse(code)
        if len(_CACHE) > 2048:
            _CACHE.clear()
        _CACHE[code] = nodes
    return nodes


class FunctionError(Exception):
    def __init__(self, call: Call, message: str) -> None:
        super().__init__(message)
        self.call, self.message = call, message

    def render(self) -> str:
        return f"❌ Function `${self.call.raw}` at {self.call.line}:{self.call.col} returned an error: {self.message}"


# -- evaluation ---------------------------------------------------------------------------------------------

async def evaluate(ctx: Context, nodes: Sequence[Node]) -> str:
    out: List[str] = []
    try:
        return await _evaluate(ctx, nodes, out)
    except StopExecution as s:
        s.partial = "".join(out) + s.partial
        raise


async def _evaluate(ctx: Context, nodes: Sequence[Node], out: List[str]) -> str:
    for node in nodes:
        if isinstance(node, Text):
            out.append(node.value)
        elif isinstance(node, Call):
            out.append(await call(ctx, node))
        elif isinstance(node, If):
            out.append(await _if(ctx, node))
        elif isinstance(node, Try):
            out.append(await _try(ctx, node))
        elif isinstance(node, Loop):
            out.append(await _loop(ctx, node))
        elif isinstance(node, Async):
            name = (await evaluate(ctx, node.call.args[0])) if node.call.args else ""

            async def run(body: Sequence[Node] = node.body) -> str:
                try:
                    return await evaluate(ctx, body)
                except (StopExecution, FunctionError) as e:
                    log.debug("async scope %s ended: %s", name, e)
                    return ""

            ctx.async_tasks[name.strip()] = asyncio.ensure_future(run())
    return "".join(out)


async def arg_text(ctx: Context, nodes: Sequence[Node]) -> str:
    return await evaluate(ctx, nodes)


async def call(ctx: Context, node: Call) -> str:
    f = FUNCTIONS.get(node.name)
    if f is None:
        return node.text
    if f.brackets == "required" and node.args is None:
        raise FunctionError(node, "missing brackets")
    try:
        if f.lazy:
            result = await f.impl(ctx, node, node.args or [])
        else:
            args: List[str] = []
            for a in node.args or []:
                args.append(await evaluate(ctx, a))
            if node.args is not None and len(args) < f.min_args:
                raise BDScriptError(f"expected at least {f.min_args} argument(s), got {len(args)}")
            lo, hi = _arity(f)
            if hi is not None and len(args) > hi:
                if len(args) == 1 and args[0] == "" or all(a == "" for a in args[hi:]):
                    args = args[:hi]   # $fn[] or trailing empty args
                else:
                    raise BDScriptError(f"too many arguments (at most {hi}, got {len(args)})")
            if len(args) < lo:
                raise BDScriptError(f"expected at least {lo} argument(s), got {len(args)}")
            result = f.impl(ctx, *args)
            if asyncio.iscoroutine(result):
                result = await result
    except BDScriptError as e:
        raise FunctionError(node, str(e)) from None
    except (StopExecution, FunctionError, BreakLoop, ContinueLoop, asyncio.CancelledError):
        raise
    except ValueError as e:
        raise FunctionError(node, str(e) or "invalid value") from None
    except Exception as e:  # a bug or an API failure: still report it BDFD-style
        log.exception("BDScript function $%s failed", node.raw)
        raise FunctionError(node, f"{type(e).__name__}: {e}") from None
    if result is None:
        return ""
    if isinstance(result, bool):
        return "true" if result else "false"
    return str(result)


_ARITY: Dict[Any, Any] = {}


def _arity(f: Any):
    """(required, maximum or None) positional BDScript arguments of a function implementation."""
    import inspect
    got = _ARITY.get(f.impl)
    if got is None:
        try:
            params = list(inspect.signature(f.impl).parameters.values())[1:]  # drop ctx
        except (TypeError, ValueError):
            params = []
        if any(p.kind is p.VAR_POSITIONAL for p in params):
            hi = None
        else:
            hi = sum(1 for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))
        lo = sum(1 for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty)
        got = _ARITY[f.impl] = (lo, hi)
    return got


async def _if(ctx: Context, node: If) -> str:
    from .conditions import check

    for cond_call, body in node.branches:
        text = await evaluate(ctx, cond_call.args[0]) if cond_call.args else ""
        try:
            ok = check(text)
        except BDScriptError as e:
            raise FunctionError(cond_call, str(e)) from None
        if ok:
            return await evaluate(ctx, body)
    if node.else_body is not None:
        return await evaluate(ctx, node.else_body)
    return ""


async def _loop_items(ctx: Context, node: Loop):
    args = [await evaluate(ctx, a) for a in (node.call.args or [])]
    if node.kind == "loop":
        try:
            n = int(float(args[0])) if args and args[0].strip() else 0
        except ValueError:
            raise FunctionError(node.call, f"invalid number '{args[0]}'") from None
        return None, [str(i) for i in range(1, n + 1)]
    if node.kind == "for":
        if not args:
            raise FunctionError(node.call, "missing iterator name")
        name, values = args[0].strip(), args[1:]
        if len(values) == 2 and all(v.strip().lstrip("-").isdigit() for v in values):
            a, b = int(values[0]), int(values[1])
            step = 1 if b >= a else -1
            values = [str(i) for i in range(a, b + step, step)]
        elif len(values) == 1 and "," in values[0]:
            values = [v.strip() for v in values[0].split(",")]
        return name, values
    if node.kind == "jsonforeach":
        from .functions.jsonhttp import _walk, _dump
        v, ok = _walk(ctx.json if ctx.json is not None else {}, [a for a in args if a != ""])
        if not ok:
            return None, []
        if isinstance(v, dict):
            return "__json__", [(k, _dump(x)) for k, x in v.items()]
        if isinstance(v, list):
            return "__json__", [(str(i), _dump(x)) for i, x in enumerate(v)]
        return None, []
    return None, None  # while


async def _loop(ctx: Context, node: Loop) -> str:
    out: List[str] = []
    name, items = await _loop_items(ctx, node)
    saved = dict(ctx.loop) if hasattr(ctx, "loop") else {}
    i = 0
    try:
        while True:
            if items is None:  # $while[cond]
                from .conditions import check
                cond = await evaluate(ctx, node.call.args[0]) if node.call.args else "false"
                try:
                    if not check(cond):
                        break
                except BDScriptError as e:
                    raise FunctionError(node.call, str(e)) from None
                value = str(i + 1)
            else:
                if i >= len(items):
                    break
                value = items[i]
            if i >= MAX_ITERATIONS:
                raise FunctionError(node.call, f"more than {MAX_ITERATIONS} iterations")
            if name == "__json__":
                ctx.loop = {"index": i, "count": len(items), "value": value[1], "key": value[0]}
            else:
                ctx.loop = {"index": i, "count": len(items) if items is not None else 0, "value": value, "key": str(i)}
                if name:
                    ctx.vars[name] = value
            try:
                out.append(await evaluate(ctx, node.body))
            except ContinueLoop:
                pass
            except BreakLoop:
                break
            i += 1
    finally:
        ctx.loop = saved
    return "".join(out)


async def _try(ctx: Context, node: Try) -> str:
    try:
        return await evaluate(ctx, node.body)
    except FunctionError as e:
        ctx.error = {"command": f"${e.call.raw}", "message": e.message, "source": e.call.source,
                     "row": str(e.call.line), "column": str(e.call.col)}
        return await evaluate(ctx, node.catch)


# -- running a command --------------------------------------------------------------------------------------

def clean_output(text: str, ctx: Context) -> str:
    if ctx.inner_space_removal:
        lines = [ln.strip() for ln in text.split("\n")]
        text = "\n".join(lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
    return unescape(text.strip(), ctx.special_escaping)


async def run(ctx: Context, code: str, *, send: bool = True) -> str:
    """Run ``code``; returns the final text. With ``send`` the response (text, embeds, buttons, ...) is sent."""
    from .output import send_response

    try:
        nodes = compile_code(code)
    except ParseError as e:
        text = f"❌ Syntax error at {e.line}:{e.col}: {e}"
        ctx.failure = text
        if send and ctx.channel is not None:
            await ctx.channel.send(text)
        return text
    error_text: Optional[str] = None
    try:
        text = await evaluate(ctx, nodes)
    except StopExecution as s:
        if s.message is None:
            # $stop: halt and send what was queued so far (text, embeds, buttons)
            text = s.partial
        else:
            # failed $onlyIf/$argsCheck/...: send only the error message
            ctx.response.embeds.clear()
            ctx.response.rows = [[]]
            ctx.response.reactions.clear()
            text = s.message
            ctx.failure = text or "stopped"
            if not text:
                ctx.response.suppress = True
    except FunctionError as e:
        if ctx.suppress_errors is not None:
            text = ctx.suppress_errors
            ctx.response.embeds.clear()
            ctx.response.rows = [[]]
            if ctx.embed_suppress_errors:
                ctx.response.embeds[1] = ctx.embed_suppress_errors["embed"]
        elif getattr(ctx.bot, "function_error_code", None) and not ctx.in_error_handler:
            # aoi.js functionErrorCommand: a custom handler renders the error
            ctx.in_error_handler = True
            ctx.error = {"function": f"${e.call.raw}", "command": getattr(ctx.command, "name", "") or "",
                         "error": e.message, "message": e.message, "row": str(e.call.line), "column": str(e.call.col)}
            ctx.response.embeds.clear()
            ctx.response.rows = [[]]
            try:
                text = await evaluate(ctx, compile_code(ctx.bot.function_error_code))
            except (FunctionError, StopExecution):
                text = e.render()
            ctx.failure = e.render()
        else:
            error_text = e.render()
            text = error_text
            ctx.failure = error_text
            ctx.response.embeds.clear()
            ctx.response.rows = [[]]
            ctx.response.mention_author = False
        log.info("BDScript error in %s: %s", getattr(ctx.command, "name", "?"), e.render())
    # wait for unawaited async scopes so their side effects finish before we reply
    for t in list(ctx.async_tasks.values()):
        try:
            await t
        except Exception:
            pass
    final = clean_output(text, ctx)
    if send:
        await send_response(ctx, final)
    return final


async def run_lazy_arg(ctx: Context, nodes: Sequence[Node]) -> str:
    return await evaluate(ctx, nodes)
