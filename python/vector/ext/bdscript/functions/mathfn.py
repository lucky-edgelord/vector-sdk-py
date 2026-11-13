"""Math functions (and D.js-BDscript's $math)."""

from __future__ import annotations

import ast
import math
import operator
import random

from ..registry import BDScriptError, fn
from ..util import fmt_num, to_int, to_num

_LIMIT = 2 ** 128


def _check(x: float) -> float:
    if abs(x) > _LIMIT:
        raise BDScriptError("number too large")
    return x


@fn("sum", min_args=1, brackets="required")
def _sum(ctx, *n):
    return fmt_num(_check(sum(to_num(x) for x in n)))


@fn("sub", min_args=1, brackets="required")
def _sub(ctx, *n):
    vals = [to_num(x) for x in n]
    r = vals[0]
    for v in vals[1:]:
        r -= v
    return fmt_num(_check(r))


@fn("multi", min_args=1, brackets="required")
def _multi(ctx, *n):
    r = 1.0
    for x in n:
        r *= to_num(x)
    return fmt_num(_check(r))


@fn("divide", min_args=1, brackets="required")
@fn("div", min_args=1, brackets="required")
def _divide(ctx, *n):
    vals = [to_num(x) for x in n]
    r = vals[0]
    for v in vals[1:]:
        if v == 0:
            raise BDScriptError("division by zero")
        r /= v
    return fmt_num(_check(r))


@fn("modulo", min_args=2, brackets="required")
def _modulo(ctx, *n):
    vals = [to_num(x) for x in n]
    r = vals[0]
    for v in vals[1:]:
        if v == 0:
            raise BDScriptError("division by zero")
        r = math.fmod(r, v)
    return fmt_num(r)


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Mod: operator.mod, ast.Pow: operator.pow, ast.FloorDiv: operator.floordiv, ast.USub: operator.neg,
        ast.UAdd: operator.pos, ast.BitXor: operator.xor, ast.BitAnd: operator.and_, ast.BitOr: operator.or_,
        ast.LShift: operator.lshift, ast.RShift: operator.rshift}
_FUNCS = {"sqrt": math.sqrt, "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil, "sin": math.sin,
          "cos": math.cos, "tan": math.tan, "log": math.log, "log10": math.log10, "min": min, "max": max,
          "pow": pow, "exp": math.exp}
_CONST = {"pi": math.pi, "e": math.e}


def safe_eval(expr: str) -> float:
    expr = expr.replace("^", "**").replace("×", "*").replace("÷", "/").replace(",", "")

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(b) > 512:
                raise BDScriptError("exponent too large")
            return _OPS[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS:
            return _FUNCS[n.func.id](*[ev(a) for a in n.args])
        if isinstance(n, ast.Name) and n.id in _CONST:
            return _CONST[n.id]
        raise BDScriptError("invalid expression")

    try:
        return _check(float(ev(ast.parse(expr.strip(), mode="eval"))))
    except BDScriptError:
        raise
    except ZeroDivisionError:
        raise BDScriptError("division by zero")
    except Exception:
        raise BDScriptError(f"invalid expression '{expr}'")


@fn("calculate", min_args=1, brackets="required")
@fn("math", min_args=1, brackets="required")
def _calc(ctx, *expr):
    return fmt_num(safe_eval(";".join(expr)))


@fn("round", min_args=1, brackets="required")
def _round(ctx, n, places="0"):
    return fmt_num(round(to_num(n), to_int(places or "0")))


@fn("ceil", min_args=1, brackets="required")
def _ceil(ctx, n):
    return str(math.ceil(to_num(n)))


@fn("floor", min_args=1, brackets="required")
def _floor(ctx, n):
    return str(math.floor(to_num(n)))


@fn("sqrt", min_args=1, brackets="required")
def _sqrt(ctx, n):
    x = to_num(n)
    if x < 0:
        raise BDScriptError("square root of a negative number")
    return fmt_num(math.sqrt(x))


@fn("max", min_args=1, brackets="required")
def _max(ctx, *n):
    return fmt_num(max(to_num(x) for x in n))


@fn("min", min_args=1, brackets="required")
def _min(ctx, *n):
    return fmt_num(min(to_num(x) for x in n))


@fn("random")
@fn("randomComplex")
def _random(ctx, a="", b="", *rest):
    # BDScript 2 optimisation: identical $random[...] calls in one run give the same value ($'random never does)
    key = ("random", a, b)
    if not ctx.extras.get("no_cache") and key in ctx.random_cache:
        return ctx.random_cache[key]
    v = _random_value(a, b)
    if not ctx.extras.get("no_cache"):
        ctx.random_cache[key] = v
    return v


def _random_value(a, b):
    if a == "" and b == "":
        return str(random.randint(0, 2 ** 31))
    if b == "":
        a, b = "0", a
    lo, hi = to_num(a), to_num(b)
    if lo > hi:
        lo, hi = hi, lo
    if lo.is_integer() and hi.is_integer() and "." not in a + b:
        # BDFD: max is exclusive
        return str(random.randrange(int(lo), int(hi)) if hi > lo else int(lo))
    return fmt_num(random.uniform(lo, hi))


@fn("abs", min_args=1, brackets="required")
def _abs(ctx, n):
    return fmt_num(abs(to_num(n)))
