"""Run unmodified discord.py bots on Vector.

    python -m vector.compat bot.py        # or: vector-run bot.py

or, at the top of your entry point::

    import vector.compat; vector.compat.install()
    import discord                         # now resolves to ``vector``

``install()`` makes ``discord``, ``discord.ext.commands``, ``discord.ext.tasks``, ``discord.ext.menus``,
``discord.ui``, ``discord.utils`` and ``discord.errors`` import from this library. It never replaces a real
``discord`` that is already imported.
"""

from __future__ import annotations

import importlib
import runpy
import sys

_ALIASES = {
    "discord": "vector",
    "discord.ext": "vector.ext",
    "discord.ext.commands": "vector.ext.commands",
    "discord.ext.tasks": "vector.ext.tasks",
    "discord.ext.menus": "vector.ext.menus",
    "discord.ui": "vector.ui",
    "discord.utils": "vector.utils",
    "discord.errors": "vector.errors",
    "discord.abc": "vector.abc",
}


def install() -> None:
    """Alias the ``discord`` package namespace to ``vector``."""
    real = sys.modules.get("discord")
    if real is not None and getattr(real, "__name__", "") != "vector":
        raise RuntimeError("the real discord.py is already imported")
    for alias, target in _ALIASES.items():
        try:
            sys.modules[alias] = importlib.import_module(target)
        except ImportError:
            pass


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: vector-run bot.py [args...]   (runs a discord.py bot on Vector)")
        raise SystemExit(0 if argv else 2)
    install()
    script = argv[0]
    sys.argv = argv
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(script)))
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
