"""``vector-bdscript run <folder>``: run a folder of BDScript commands as a Vector bot.

The folder holds command files (``.bds``, ``.json``, ``.py``; see ``CommandManager``) and optionally ``bot.json``::

    {"prefix": "!", "owners": ["npub1..."], "variables": {"money": 0},
     "slash": [{"name": "ping", "description": "Pong", "options": []}]}

Files are watched and reloaded when they change. The key comes from ``--nsec`` or ``$VECTOR_NSEC``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="vector-bdscript", description="Run BDScript commands on Vector")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a folder of commands")
    r.add_argument("folder")
    r.add_argument("--nsec", default=os.environ.get("VECTOR_NSEC"))
    r.add_argument("--prefix", default=None)
    r.add_argument("--data-dir", default=os.environ.get("VECTOR_DATA_DIR"))
    r.add_argument("--no-watch", action="store_true")
    c = sub.add_parser("check", help="parse every command and report syntax errors")
    c.add_argument("folder")
    e = sub.add_parser("functions", help="list supported functions")
    args = ap.parse_args(argv)

    from . import FUNCTIONS, BDBot

    if args.cmd == "functions":
        for name in sorted({f.name for f in FUNCTIONS.values()}, key=str.lower):
            f = FUNCTIONS[name.lower()]
            tag = "" if f.status == "full" else f"  ({f.status}{': ' + f.note if f.note else ''})"
            print(f"${name}{tag}")
        return

    cfg = {}
    cfg_path = os.path.join(args.folder, "bot.json")
    if os.path.exists(cfg_path):
        cfg = json.load(open(cfg_path))

    if args.cmd == "check":
        from .interpreter import compile_code
        from .bot import CommandManager

        bad = 0
        mgr = CommandManager.__new__(CommandManager)
        for root, _, files in os.walk(args.folder):
            for f in files:
                full = os.path.join(root, f)
                for d in CommandManager._read(mgr, full):
                    try:
                        compile_code(str(d.get("code", "")))
                    except Exception as ex:
                        bad += 1
                        print(f"{full}: {ex}")
        print("ok" if not bad else f"{bad} error(s)")
        sys.exit(1 if bad else 0)

    bot = BDBot(prefix=args.prefix or cfg.get("prefix", "!"), owners=cfg.get("owners", ()),
                data_dir=args.data_dir, auto_variables=cfg.get("auto_variables", False))
    bot.variables(cfg.get("variables", {}))
    for s in cfg.get("slash", []):
        bot.slash_command(s["name"], s.get("description", ""), s.get("options", []))
    n = bot.manager.load(args.folder)
    print(f"loaded {n} command(s)")

    async def go():
        if not args.no_watch:
            bot.later(bot.manager.watch())
        await bot.start(args.nsec)

    asyncio.run(go())


if __name__ == "__main__":
    main()
