"""BDScript parser.

Handles BDScript 2 (Bot Designer for Discord) and the D.js-BDscript dialect:

* ``$name`` and ``$name[arg;arg;...]``, nested calls, case-insensitive names, longest-name matching
  (``$authorID`` is not ``$author`` + ``ID``); an unknown ``$word`` stays as text
* escapes (backslash before ``$ ; [ ]`` or a backslash) and the special escapes ``%{DOL}%``, ``%{-SEMICOL-}%``, ``%{-LEFT-}%``,
  ``%{-RIGHT-}%`` (resolved when output is produced, so they survive nested evaluation)
* blocks: ``$if[..] $elseif[..] $else $endif``, ``$try $catch $endtry``, ``$async[name] $endasync``;
  a ``$if`` with two or three arguments is the D.js-BDscript inline form ``$if[cond;then;else]``
* ``$c[...]`` comments are dropped
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

# Placeholders for escaped characters, so they are never mistaken for syntax by nested evaluation.
ESC = {"$": "\x00D", ";": "\x00S", "[": "\x00L", "]": "\x00R", "\\": "\x00B"}
SPECIAL = {"%{DOL}%": "$", "%{-SEMICOL-}%": ";", "%semi%": ";", "%{-LEFT-}%": "[", "%{-RIGHT-}%": "]", "%{-BSLASH-}%": "\\"}


def unescape(text: str, special: bool = True) -> str:
    """Turn escape placeholders (and, unless disabled, special escapes) into the characters they stand for."""
    for ch, ph in ESC.items():
        text = text.replace(ph, ch)
    if special:
        for k, v in SPECIAL.items():
            text = text.replace(k, v)
    return text


def escape(text: str) -> str:
    """Protect characters in function output so later evaluation treats them as text."""
    out = []
    for ch in text:
        out.append(ESC.get(ch, ch) if ch in "$;[]" else ch)
    return "".join(out)


class ParseError(Exception):
    def __init__(self, message: str, line: int = 0, col: int = 0) -> None:
        super().__init__(message)
        self.line, self.col = line, col


@dataclass
class Text:
    value: str


@dataclass
class Call:
    name: str                         # canonical (registry) name
    raw: str                          # as written
    args: Optional[List[List["Node"]]]
    line: int = 1
    col: int = 1
    source: str = ""                  # the source line, for $error[source]
    text: str = ""                    # the whole call as written


@dataclass
class If:
    branches: List[Tuple[Call, List["Node"]]]   # ($if/$elseif call, body)
    else_body: Optional[List["Node"]] = None


@dataclass
class Try:
    body: List["Node"]
    catch: List["Node"] = field(default_factory=list)


@dataclass
class Loop:
    kind: str          # "for" | "while" | "loop" | "jsonforeach"
    call: Call
    body: List["Node"]


@dataclass
class Async:
    call: Call
    body: List["Node"]


Node = Union[Text, Call, If, Try, Async, Loop]


_LOOPS = {"for": "endfor", "while": "endwhile", "loop": "endloop", "jsonforeach": "endjsonforeach"}


class Parser:
    """``lookup(name_lower) -> (canonical, brackets)`` where brackets is ``"none" | "optional" | "required"``."""

    def __init__(self, names: Dict[str, Tuple[str, str]]) -> None:
        self.names = names
        self._by_first: Dict[str, List[str]] = {}
        for n in sorted(names, key=len, reverse=True):
            self._by_first.setdefault(n[:1], []).append(n)

    # -- lexing ---------------------------------------------------------------------------------------------

    def parse(self, code: str) -> List[Node]:
        self.src = code.replace("\r\n", "\n")
        self.lines = self.src.split("\n")
        self.i = 0
        nodes = self._sequence(top=True)
        return self._structure(nodes)

    def _pos(self, i: int) -> Tuple[int, int]:
        line = self.src.count("\n", 0, i) + 1
        col = i - (self.src.rfind("\n", 0, i) + 1) + 1
        return line, col

    def _match_name(self, i: int) -> Optional[str]:
        rest = self.src[i: i + 64].lower()
        for n in self._by_first.get(rest[:1], ()):
            if rest.startswith(n):
                return n
        return None

    def _sequence(self, top: bool) -> List[Node]:
        """Parse until end (top) or an unescaped ``;``/``]`` (inside arguments; not consumed)."""
        out: List[Node] = []
        buf: List[str] = []
        s = self.src

        def flush() -> None:
            if buf:
                out.append(Text("".join(buf)))
                buf.clear()

        while self.i < len(s):
            ch = s[self.i]
            if ch == "\\" and self.i + 1 < len(s) and s[self.i + 1] in "$;[]\\":
                buf.append(ESC[s[self.i + 1]])
                self.i += 2
                continue
            if not top and ch in ";]":
                break
            if ch == "$":
                name = self._match_name(self.i + 1)
                if name is not None:
                    flush()
                    out.append(self._call(name))
                    continue
            buf.append(ch)
            self.i += 1
        flush()
        return out

    def _call(self, name: str) -> Call:
        start = self.i
        canonical, brackets = self.names[name]
        raw = self.src[start + 1: start + 1 + len(name)]
        self.i = start + 1 + len(name)
        line, col = self._pos(start)
        args: Optional[List[List[Node]]] = None
        if brackets != "none" and self.i < len(self.src) and self.src[self.i] == "[":
            self.i += 1
            args = []
            while True:
                arg = self._sequence(top=False)
                args.append(arg)
                if self.i >= len(self.src):
                    raise ParseError(f"${raw}[ is missing its closing ]", line, col)
                ch = self.src[self.i]
                self.i += 1
                if ch == "]":
                    break
        elif brackets == "required":
            # BDFD reports this at run time; keep the call so the error has a position
            pass
        source = self.lines[line - 1] if line - 1 < len(self.lines) else ""
        return Call(canonical, raw, args, line, col, source.strip(), self.src[start:self.i])

    # -- block structure ------------------------------------------------------------------------------------

    def _structure(self, nodes: List[Node]) -> List[Node]:
        # comments out, args structured recursively
        flat: List[Node] = []
        for n in nodes:
            if isinstance(n, Call):
                if n.name == "c":
                    continue
                if n.args is not None:
                    n.args = [self._structure(a) for a in n.args]
            flat.append(n)
        out, _ = self._blocks(flat, 0, ())
        return out

    def _blocks(self, nodes: List[Node], i: int, until: Sequence[str]) -> Tuple[List[Node], int]:
        out: List[Node] = []
        while i < len(nodes):
            n = nodes[i]
            if isinstance(n, Call) and n.name in until:
                return out, i
            if isinstance(n, Call) and n.name == "if" and (n.args is None or len(n.args) <= 1):
                block, i = self._if(nodes, i)
                out.append(block)
                continue
            if isinstance(n, Call) and n.name == "try":
                body, i = self._blocks(nodes, i + 1, ("catch", "endtry"))
                catch: List[Node] = []
                if i < len(nodes) and nodes[i].name == "catch":  # type: ignore[union-attr]
                    catch, i = self._blocks(nodes, i + 1, ("endtry",))
                out.append(Try(body, catch))
                i += 1  # past $endtry (or end of code)
                continue
            if isinstance(n, Call) and n.name in _LOOPS and (n.name != "loop" or (n.args is not None and len(n.args) == 1)):
                body, i = self._blocks(nodes, i + 1, (_LOOPS[n.name],))
                out.append(Loop(n.name, n, body))
                i += 1
                continue
            if isinstance(n, Call) and n.name == "async":
                body, i = self._blocks(nodes, i + 1, ("endasync",))
                out.append(Async(n, body))
                i += 1
                continue
            out.append(n)
            i += 1
        return out, i

    def _if(self, nodes: List[Node], i: int) -> Tuple[If, int]:
        block = If([])
        cond = nodes[i]
        i += 1
        while True:
            body, i = self._blocks(nodes, i, ("elseif", "else", "endif"))
            block.branches.append((cond, body))  # type: ignore[arg-type]
            if i >= len(nodes):
                return block, i
            tag = nodes[i]
            i += 1
            if tag.name == "elseif":  # type: ignore[union-attr]
                cond = tag
                continue
            if tag.name == "else":  # type: ignore[union-attr]
                block.else_body, i = self._blocks(nodes, i, ("endif",))
                return block, i + 1
            return block, i  # $endif
