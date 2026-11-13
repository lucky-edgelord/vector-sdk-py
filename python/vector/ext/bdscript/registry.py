"""Function registry: ``@fn("name", ...)`` registers a BDScript function implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple


class BDScriptError(Exception):
    """A function failed; reported like BDFD: "Function `$x` at 1:5 returned an error: ..."."""


class StopExecution(Exception):
    """``$stop``, a failed ``$onlyIf`` and friends: end the command quietly (after sending ``message``)."""

    def __init__(self, message: Optional[str] = None) -> None:
        super().__init__(message or "")
        self.message = message
        self.partial = ""   # output produced before $stop (sent, like BDFD)


class BreakLoop(Exception):
    """``$break``"""


class ContinueLoop(Exception):
    """``$continue``"""


MAX_ITERATIONS = 10_000


@dataclass
class Function:
    name: str
    impl: Callable[..., Any]
    brackets: str = "optional"     # "none" | "optional" | "required"
    lazy: bool = False             # receives unevaluated argument node lists
    min_args: int = 0
    max_args: Optional[int] = None
    status: str = "full"           # "full" | "partial" | "noop" (Discord-only, harmless default)
    note: str = ""


FUNCTIONS: Dict[str, Function] = {}


def fn(*names: str, brackets: str = "optional", lazy: bool = False, min_args: int = 0, max_args: Optional[int] = None,
       status: str = "full", note: str = "") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register ``impl(ctx, *args)`` under every name in ``names`` (first one is canonical for errors)."""

    def deco(impl: Callable[..., Any]) -> Callable[..., Any]:
        for n in names:
            FUNCTIONS[n.lower()] = Function(n, impl, brackets, lazy, min_args, max_args, status, note)
        return impl

    return deco


def alias(new: str, existing: str) -> None:
    f = FUNCTIONS[existing.lower()]
    FUNCTIONS[new.lower()] = Function(new, f.impl, f.brackets, f.lazy, f.min_args, f.max_args, f.status, f.note)


def parser_names() -> Dict[str, Tuple[str, str]]:
    return {k: (k, f.brackets) for k, f in FUNCTIONS.items()}
