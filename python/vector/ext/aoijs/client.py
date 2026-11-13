"""``AoiClient``: aoi.js's client API on top of the BDScript engine."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Union

from ..bdscript.bot import BDBot, Command
from ..bdscript.context import Context
from ..bdscript.interpreter import evaluate, compile_code, run
from ..bdscript.parser import escape
from ..bdscript.registry import BDScriptError, fn

log = logging.getLogger("vector.aoijs")

# aoi.js command `type` values (and the *Command method that makes them) -> the engine's command kind
_TYPES = {
    "basic": "basicCommand", "basiccommand": "basicCommand", "ready": "readyCommand", "join": "joinCommand",
    "leave": "leaveCommand", "banadd": "banAddCommand", "banremove": "banRemoveCommand",
    "messagedelete": "deleteCommand", "deleted": "deleteCommand", "delete": "deleteCommand",
    "awaited": "awaitedCommand", "interaction": "interactionCommand", "slash": "slashCommand",
    "reactionadd": "reactionCommand", "reaction": "reactionCommand",
}

# aoi.js commands/events that have no counterpart on Vector (accepted so ported bots still load)
_UNSUPPORTED = (
    "guildJoin", "guildLeave", "guildUpdate", "guildUnavailable", "roleCreate", "roleUpdate", "roleDelete",
    "channelCreate", "channelUpdate", "channelDelete", "channelPinsUpdate", "stageInstanceCreate",
    "stageInstanceUpdate", "stageInstanceDelete", "threadCreate", "threadUpdate", "threadDelete", "threadListSync",
    "threadMemberUpdate", "threadMembersUpdate", "memberUpdate", "memberAvailable", "membersChunk", "emojiCreate",
    "emojiDelete", "emojiUpdate", "reactionRemove", "reactionRemoveAll", "reactionRemoveEmoji", "presenceUpdate",
    "voiceStateUpdate", "pollVoteAdd", "pollVoteRemove", "entitlementCreate", "entitlementUpdate",
    "entitlementDelete", "applicationCmdCreate", "applicationCmdDelete", "applicationCmdUpdate",
    "applicationCmdPermissionsUpdate", "userUpdate", "variableCreate", "variableDelete", "variableUpdate",
    "rateLimit", "webhooksUpdate", "autoModActionExecution", "autoModCreate", "autoModDelete", "autoModUpdate",
    "inviteCreate", "inviteDelete", "messageUpdate", "messageDeleteBulk", "bulkDelete", "update", "typingStart",
    "musicStart", "musicEnd",
)

_EVERY = re.compile(r"(\d+(?:\.\d+)?)\s*(ms|s|m|h|d|w)?", re.IGNORECASE)
_UNIT = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def _seconds(value: Any) -> float:
    """aoi.js durations: milliseconds as a number, or ``"10s"`` / ``"1h30m"``."""
    if isinstance(value, (int, float)):
        return float(value) / 1000.0
    total, found = 0.0, False
    for num, unit in _EVERY.findall(str(value)):
        found = True
        total += float(num) * (_UNIT[unit.lower()] if unit else 0.001)
    if not found:
        raise ValueError(f"invalid duration {value!r}")
    return total


class AoiClient(BDBot):
    """aoi.js's ``AoiClient`` for Vector.

    >>> client = AoiClient({"token": "nsec1...", "prefix": "!", "intents": ["MessageContent"], "events": ["onMessage"]})
    >>> client.command({"name": "ping", "code": "Pong! $ping ms"})
    >>> client.run()

    Options (as a dict or keywords): ``token`` (your Vector ``nsec``, or ``$VECTOR_NSEC``), ``prefix`` (string or
    list), ``database`` (a SQLite file path or ``{"path": "..."}``; default ``./database/aoi.db``; aoi.js's ``type``
    and ``db`` options are ignored: storage is always SQLite), ``mentionAuthor``,
    ``intents``/``events``/``respondOnEdit``/``sharding`` (accepted and ignored: every Vector event is available),
    plus any :class:`vector.Client` option such as ``data_dir``.
    """

    def __init__(self, options: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        o = dict(options or {}, **kwargs)
        for ignored in ("intents", "events", "respondOnEdit", "sharding", "cache", "disableAoiDB", "suppressAllErrors",
                        "errorMessage", "debugs", "aoiLogs", "aoiWarning", "aoiAutoUpdate", "shards", "voice",
                        "disableLogs", "disableDefaultCommands", "partials", "presence"):
            o.pop(ignored, None)
        db = o.pop("database", None)
        if isinstance(db, dict):   # aoi.js: {"type": "aoi.db", ...}; storage here is always SQLite
            db = db.get("path") or db.get("file")
        data_dir = o.get("data_dir")
        if not db:
            db = os.path.join(data_dir or "database", "aoi.db")
        os.makedirs(os.path.dirname(os.path.abspath(db)), exist_ok=True) if db != ":memory:" else None
        o.setdefault("mention_author", bool(o.pop("mentionAuthor", False)))
        super().__init__(o.pop("prefix", "!"), token=o.pop("token", None), database=db, **o)
        self.function_error_code: Optional[str] = None
        self.loops: List[Dict[str, Any]] = []
        self.ignored_commands: Dict[str, List[Dict[str, Any]]] = {}
        self._loop_tasks: List[Any] = []
        self.client.listen("on_ready")(self._start_loops)

    # -- commands -------------------------------------------------------------------------------------------
    def _normalise(self, d: Dict[str, Any], kind: Optional[str] = None) -> Dict[str, Any]:
        d = dict(d)
        if kind is not None:
            d["type"] = kind
        else:
            t = str(d.get("type") or "").strip()
            d["type"] = _TYPES.get(t.lower(), t) if t else ""
        # a "channel" on callback commands: send there, like aoi.js
        channel = d.pop("channel", None)
        if channel and d.get("code") and "$usechannel[" not in d["code"].lower():
            d["code"] = f"$useChannel[{channel}]\n{d['code']}"
        if d.pop("nonPrefixed", False) and d.get("name") and not d.get("trigger"):
            d["trigger"] = d["name"]
        return d

    def command(self, *commands: Dict[str, Any], _source: str = "", **kwargs: Any) -> Any:  # type: ignore[override]
        """Add commands: ``client.command({"name": "ping", "aliases": ["p"], "code": "..."}, {...})``.

        ``nonPrefixed: True`` makes the name a bare trigger. ``type`` takes aoi.js types (``"basic"``,
        ``"interaction"``...) and the engine's own.
        """
        items = list(commands) + ([kwargs] if kwargs else [])
        made = []
        for i, d in enumerate(items):
            if not isinstance(d, dict):
                raise TypeError(f"Command {len(self.commands)} must be a dict")
            if not d.get("name") and not d.get("trigger") and not d.get("type"):
                raise TypeError(f"Command {len(self.commands)} needs a name!")
            if not d.get("code"):
                raise TypeError(f"Command {len(self.commands)} needs a code!")
            made.append(super().command(self._normalise(d), _source=_source))
        return made[0] if len(made) == 1 else made

    def _typed(self, kind: str, d: Dict[str, Any]) -> Any:
        if not d.get("code"):
            raise TypeError(f"Code is not provided in {d.get('name') or 'unknown name'}: {kind}")
        d = self._normalise(d, kind)
        d.setdefault("name", "")
        return super().command(d)

    def readyCommand(self, d: Dict[str, Any]) -> Any: return self._typed("readyCommand", d)             # noqa: N802
    def joinCommand(self, d: Dict[str, Any]) -> Any: return self._typed("joinCommand", d)               # noqa: N802
    def leaveCommand(self, d: Dict[str, Any]) -> Any: return self._typed("leaveCommand", d)             # noqa: N802
    def banAddCommand(self, d: Dict[str, Any]) -> Any: return self._typed("banAddCommand", d)           # noqa: N802
    def banRemoveCommand(self, d: Dict[str, Any]) -> Any: return self._typed("banRemoveCommand", d)     # noqa: N802
    def deletedCommand(self, d: Dict[str, Any]) -> Any: return self._typed("deleteCommand", d)          # noqa: N802
    def reactionAddCommand(self, d: Dict[str, Any]) -> Any: return self._typed("reactionCommand", d)    # noqa: N802

    def awaitedCommand(self, d: Dict[str, Any]) -> Any:  # noqa: N802
        """``awaitedCommand({"name": "ask", "code": "..."})``: run with BDScript's ``$awaitFunc[ask]``."""
        if not d.get("name"):
            raise TypeError("awaitedCommand needs a name!")
        return self._typed("awaitedCommand", d)

    def interactionCommand(self, d: Dict[str, Any]) -> Any:  # noqa: N802
        """``interactionCommand({"name": "yes", "prototype": "button", "code": "..."})``: the name is the custom id
        (``prototype`` ``"slash"`` defines a slash command; ``"selectMenu"``/``"modal"``/``"button"`` are all
        matched by custom id)."""
        if not d.get("prototype"):
            raise TypeError(f"Prototype is not provided in {d.get('name') or 'unknown name'}: interactionCommand.")
        if not d.get("code"):
            raise TypeError(f"Code is not provided in {d.get('name') or 'unknown name'}: interactionCommand.")
        d = dict(d)
        proto = str(d.pop("prototype")).lower()
        if proto in ("slash", "slashcommand"):
            return self._typed("slashCommand", d)
        return self._typed("interactionCommand", d)

    def functionErrorCommand(self, d: Dict[str, Any]) -> None:  # noqa: N802
        """Runs for any function error instead of the default message. Use ``$handleError[function]``,
        ``$handleError[command]`` and ``$handleError[error]`` inside."""
        self.function_error_code = str(d["code"])
        compile_code(self.function_error_code)

    def loopCommand(self, d: Dict[str, Any]) -> None:  # noqa: N802
        """``loopCommand({"every": 60000, "channel": "<id>", "executeOnStartup": True, "code": "..."})``
        runs the code repeatedly (``every`` in ms or like ``"1h"``)."""
        if not d.get("code"):
            raise TypeError("Code is not provided in loopCommand")
        d = dict(d)
        d["seconds"] = _seconds(d.get("every", 60000))
        compile_code(str(d["code"]))
        self.loops.append(d)
        if self.client.is_ready():
            self._spawn_loop(d)

    def timeoutCommand(self, d: Dict[str, Any]) -> None:  # noqa: N802
        self.ignored_commands.setdefault("timeout", []).append(d)

    def __getattr__(self, name: str) -> Any:
        # *Command registrars for Discord-only events, and the on<Event>() switches
        if name.endswith("Command") and name[:-7] in _UNSUPPORTED:
            def unsupported(d: Dict[str, Any]) -> None:
                self.ignored_commands.setdefault(name[:-7], []).append(d)
                log.warning("%s has no Vector equivalent; the command is kept but never runs", name)
            return unsupported
        if re.fullmatch(r"on[A-Z]\w*", name):
            return lambda *a, **k: self      # events are always on
        raise AttributeError(name)

    # -- loops ----------------------------------------------------------------------------------------------
    def _spawn_loop(self, d: Dict[str, Any]) -> None:
        async def go() -> None:
            first = True
            while True:
                if not first or d.get("executeOnStartup"):
                    ch = self.client.get_channel(str(d["channel"])) if d.get("channel") else None
                    ctx = Context(self, channel=ch, author=self.client.user, command=Command(code=d["code"], name="loop", kind="ready"),
                                  mention_default=False)
                    try:
                        await run(ctx, str(d["code"]))
                    except Exception:
                        log.exception("loopCommand failed")
                first = False
                await asyncio.sleep(d["seconds"])

        t = asyncio.ensure_future(go())
        self._loop_tasks.append(t)

    async def _start_loops(self) -> None:
        for d in self.loops:
            self._spawn_loop(d)

    # -- variables, status, handler ---------------------------------------------------------------------------
    def variables(self, defaults: Union[Dict[str, Any], Sequence[Dict[str, Any]]], table: str = "main") -> None:  # type: ignore[override]
        """``client.variables({"money": 0, "title": "Rookie"}, "main")`` (the table is accepted and ignored)."""
        super().variables(defaults)

    def status(self, *statuses: Dict[str, Any]) -> None:
        """Accepted for aoi.js bots; Vector bots have no presence, so nothing is shown."""
        self.ignored_commands.setdefault("status", []).extend(statuses)

    def loadCommands(self, directory: str, debug: bool = False) -> int:  # noqa: N802
        """Load command files from a folder (``.py``, ``.json``, ``.bds``). A ``.py`` file sets ``exports`` (or
        ``command``/``commands``) to a dict or list of dicts, like ``module.exports``."""
        before = {id(c) for c in self.commands}
        n = self.manager.load(directory)
        if debug:
            for c in self.commands:
                if id(c) not in before:
                    print(f"loaded {c.kind} command: {c.name or c.trigger or c.arg}")
        return n

    def addFunction(self, d: Dict[str, Any]) -> None:  # noqa: N802
        """Custom functions, aoi.js style.

        * ``{"name": "$greet", "params": ["who"], "type": "aoi.js", "code": "Hello {who}!"}``: BDScript with
          ``{param}`` placeholders. ``$greet[Ada]`` -> ``Hello Ada!``
        * ``{"name": "$shout", "type": "djs", "code": lambda ctx, text="": text.upper()}``: a Python callable
          taking the BDScript context and the string arguments (async works).
        """
        name = str(d["name"]).lstrip("$")
        code = d.get("code")
        if callable(code):
            impl = code

            def python_fn(ctx: Context, *args: str) -> Any:
                out = impl(ctx, *args)
                return out
            fn(name, brackets=d.get("brackets", "optional"), status="custom")(python_fn)
            return
        params = list(d.get("params") or [])
        template = str(code)

        async def script_fn(ctx: Context, *args: str) -> str:
            body = template
            for p, v in zip(params, list(args) + [""] * len(params)):
                body = body.replace("{" + p + "}", escape(v))
            return await evaluate(ctx, compile_code(body))

        if len(params) <= 1:
            async def script_fn1(ctx: Context, a: str = "") -> str:
                return await script_fn(ctx, a)
            fn(name, brackets="optional", status="custom")(script_fn1)
        else:
            fn(name, brackets="optional", status="custom")(script_fn)

    # -- running ----------------------------------------------------------------------------------------------
    def run(self, token: Optional[str] = None, **kwargs: Any) -> None:
        super().run(token, **kwargs)

    login = run


Bot = AoiClient
