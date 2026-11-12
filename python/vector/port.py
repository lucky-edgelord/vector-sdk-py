"""``vector-port``: check a discord.py bot for things that need attention before it runs on Vector.

    vector-port check path/to/bot            # report only
    vector-port check path/to/bot --fix      # also rewrite INTEGER id columns to TEXT in SQL

What it looks for:

* ``discord`` names Vector doesn't have (errors) or only stubs (warnings)
* ID-shaped database columns declared ``INTEGER`` (Vector IDs are 64-hex strings and npubs)
* hard-coded Discord snowflakes (17-20 digit integers) that won't match anything on Vector
* ``int(...)`` applied to something ID-like
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

_ID_WORDS = r"(?:guild|server|channel|user|member|author|owner|role|message|msg|mod|admin|target|moderator|staff|bot)"
# a column called guild_id / GuildID / userid / channelid ... declared INTEGER (optionally PRIMARY KEY)
_COLUMN = re.compile(rf"(?P<name>\b\w*{_ID_WORDS}_?id\b|\bid_?{_ID_WORDS}\b)(?P<sp>\s+)(?P<type>INTEGER|INT|BIGINT)\b",
                     re.IGNORECASE)
_SNOWFLAKE = re.compile(r"^\d{17,20}$")


@dataclass
class Finding:
    level: str  # "error" | "warn" | "info"
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.level}: {self.message}"


def _py_files(root: str) -> Iterator[str]:
    if os.path.isfile(root):
        yield root
        return
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in {".git", "__pycache__", "venv", ".venv", "node_modules", "env"}]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(d, f)


def _sql_files(root: str) -> Iterator[str]:
    if os.path.isfile(root):
        return
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in {".git", "__pycache__", "venv", ".venv", "node_modules", "env"}]
        for f in files:
            if f.endswith(".sql"):
                yield os.path.join(d, f)


def _resolve(dotted: str):
    """Resolve ``discord.ext.commands.Foo`` against vector; returns (found, is_stub)."""
    import importlib

    import vector  # noqa: F401
    from vector import compat

    parts = dotted.split(".")
    head = ".".join(parts[:1])
    if head != "discord":
        return True, False
    mod_name = compat._ALIASES.get(".".join(parts[:-1]))
    if mod_name is None:
        mod_name = compat._ALIASES.get(".".join(parts))
        if mod_name is not None:
            return True, False  # a whole module
        return False, False
    mod = importlib.import_module(mod_name)
    if not hasattr(mod, parts[-1]):
        return False, False
    return True, bool(getattr(getattr(mod, parts[-1]), "__vector_stub__", False))


def check_python(path: str) -> List[Finding]:
    out: List[Finding] = []
    try:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
    except (SyntaxError, UnicodeDecodeError) as e:
        return [Finding("warn", path, getattr(e, "lineno", 1) or 1, f"could not parse: {e}")]

    aliases = {}  # local name -> dotted discord module
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "discord" or a.name.startswith("discord."):
                    aliases[a.asname or a.name.split(".")[0]] = a.name if a.asname else "discord"
        elif isinstance(node, ast.ImportFrom) and node.module and (node.module == "discord" or node.module.startswith("discord.")):
            for a in node.names:
                full = f"{node.module}.{a.name}"
                found, stub = _resolve(full)
                if not found:
                    out.append(Finding("error", path, node.lineno, f"{full} has no Vector equivalent"))
                elif stub:
                    out.append(Finding("warn", path, node.lineno, f"{full} is a Discord-only feature (stub: raises if used)"))
                aliases[a.asname or a.name] = full

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            chain, cur = [], node
            while isinstance(cur, ast.Attribute):
                chain.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name) and cur.id in aliases and aliases[cur.id].split(".")[0] == "discord":
                full = ".".join([aliases[cur.id]] + list(reversed(chain)))
                found, stub = _resolve(full)
                if not found and full.count(".") == 1:
                    out.append(Finding("error", path, node.lineno, f"{full} has no Vector equivalent"))
                elif stub and full.count(".") == 1:
                    out.append(Finding("warn", path, node.lineno, f"{full} is a Discord-only feature (stub: raises if used)"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            if _SNOWFLAKE.match(str(node.value)):
                out.append(Finding("warn", path, node.lineno,
                                   f"hard-coded Discord ID {node.value}: Vector IDs are 64-hex strings/npubs, "
                                   "load this from config"))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "int" and node.args:
            a0 = node.args[0]
            name = a0.attr if isinstance(a0, ast.Attribute) else a0.id if isinstance(a0, ast.Name) else ""
            if re.search(rf"{_ID_WORDS}_?id$|^id$", name, re.IGNORECASE) and name:
                out.append(Finding("warn", path, node.lineno, f"int({name}): Vector IDs are strings, keep as str"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "\n" in node.value or \
                (isinstance(node, ast.Constant) and isinstance(node.value, str) and "CREATE" in node.value.upper()):
            for off, line in enumerate(str(node.value).splitlines()):
                if _COLUMN.search(line):
                    out.append(Finding("warn", path, getattr(node, "lineno", 1) + off,
                                       "ID column declared INTEGER; use TEXT (" + line.strip()[:60] + ")"))
    return out


def check_sql(path: str) -> List[Finding]:
    out = []
    for i, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
        if _COLUMN.search(line):
            out.append(Finding("warn", path, i, "ID column declared INTEGER; use TEXT (" + line.strip()[:60] + ")"))
    return out


def _fix_text(text: str) -> Tuple[str, int]:
    n = 0

    def sub(m: "re.Match[str]") -> str:
        nonlocal n
        n += 1
        return f"{m.group('name')}{m.group('sp')}TEXT"

    return _COLUMN.sub(sub, text), n


def fix_file(path: str) -> int:
    text = open(path, encoding="utf-8").read()
    new, n = _fix_text(text)
    if n:
        open(path, "w", encoding="utf-8").write(new)
    return n


def check(root: str, fix: bool = False) -> List[Finding]:
    findings: List[Finding] = []
    for p in _py_files(root):
        findings += check_python(p)
    for p in _sql_files(root):
        findings += check_sql(p)
    if fix:
        for p in list(_sql_files(root)) + list(_py_files(root)):
            n = fix_file(p)
            if n:
                findings.append(Finding("info", p, 1, f"rewrote {n} ID column(s) INTEGER -> TEXT"))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="vector-port", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="scan a discord.py bot (file or folder)")
    c.add_argument("path")
    c.add_argument("--fix", action="store_true", help="rewrite ID-shaped INTEGER columns to TEXT in .sql and .py files")
    args = ap.parse_args(argv)
    findings = check(args.path, fix=args.fix)
    order = {"error": 0, "warn": 1, "info": 2}
    for f in sorted(findings, key=lambda f: (order[f.level], f.path, f.line)):
        print(f)
    errors = sum(f.level == "error" for f in findings)
    warns = sum(f.level == "warn" for f in findings)
    print(f"\n{errors} error(s), {warns} warning(s). Run it with: vector-run <your bot>.py")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
