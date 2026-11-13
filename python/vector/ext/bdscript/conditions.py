"""Condition checks shared by $if, $elseif, $onlyIf, $checkCondition, $and, $or."""

from __future__ import annotations

from .parser import unescape
from .registry import BDScriptError

OPERATORS = ("==", "!=", ">=", "<=", ">", "<")


def _num(x: str):
    try:
        return float(x.replace(",", "")) if x.strip() else None
    except ValueError:
        return None


def check(cond: str) -> bool:
    """``a==b``, ``a!=b``, ``a>b`` ... ; also accepts plain ``true``/``false``."""
    raw = cond
    cond = unescape(cond, False)
    best = None
    for op in OPERATORS:
        i = cond.find(op)
        if i != -1 and (best is None or i < best[0] or (i == best[0] and len(op) > len(best[1]))):
            best = (i, op)
    if best is None:
        low = cond.strip().lower()
        if low in ("true", "yes", "1"):
            return True
        if low in ("false", "no", "0", ""):
            return False
        raise BDScriptError(f"invalid condition '{raw.strip()}': no operator (==, !=, <, >, <=, >=)")
    i, op = best
    a, b = cond[:i].strip(), cond[i + len(op):].strip()
    if op == "==":
        na, nb = _num(a), _num(b)
        return na == nb if na is not None and nb is not None else a == b
    if op == "!=":
        na, nb = _num(a), _num(b)
        return na != nb if na is not None and nb is not None else a != b
    na, nb = _num(a), _num(b)
    if na is None or nb is None:
        raise BDScriptError(f"can't compare '{a}' {op} '{b}': {op} needs numbers")
    return {">": na > nb, "<": na < nb, ">=": na >= nb, "<=": na <= nb}[op]


def truthy(value: str) -> bool:
    return value.strip().lower() in ("yes", "true", "1", "on")
