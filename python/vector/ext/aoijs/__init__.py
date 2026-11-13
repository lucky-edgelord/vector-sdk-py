"""aoi.js-style interface for vector-sdk-py.

Write a Vector bot the way you would write an aoi.js bot: ``AoiClient``, ``client.command({...})``,
``client.readyCommand(...)``, ``client.variables(...)``, ``client.loadCommands(...)`` and so on. The ``code``
strings are BDScript (the engine in :mod:`vector.ext.bdscript`), so every BDScript function works inside them.

    from vector.ext.aoijs import AoiClient

    client = AoiClient(token="nsec1...", prefix="!", intents=["MessageContent"], events=["onMessage"])
    client.command({"name": "ping", "code": "Pong! $ping ms"})
    client.run()
"""

from .client import AoiClient, Bot  # noqa: F401

__all__ = ("AoiClient", "Bot")
