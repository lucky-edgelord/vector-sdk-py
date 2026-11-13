"""BDBot: runs BDScript commands on Vector.

Two ways to write a bot, both supported fully:

* **BDFD style**: commands with a trigger (``!ping``) or a callback trigger (``$onJoined[channelID]``,
  ``$onInteraction[id]``, ``$awaitedCommand[name]``, ``$onLeave``, ``$onBanAdd``, ``$onBanRemove``,
  ``$onMessageDelete``, ``$onAutoComplete[name]``, ``$alwaysReply``), slash commands, variables with defaults.
* **D.js-BDscript style**: ``bot.command({"name": ..., "type": "basicCommand", "code": ...})``,
  ``bot.variable([...])``, ``bot.event("onMessage")``, ``bot.createSlashCommandData(...)``,
  ``bot.manager.load("./commands")``, ``bot.login(token)``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Union

from ... import Client, Intents
from .context import Context, ModalSpec
from .interpreter import compile_code, run
from .output import build_view
from .storage import Storage

log = logging.getLogger("vector.bdscript")

FORK_TYPES = {"basicCommand": "message", "readyCommand": "ready", "slashCommand": "slash", "buttonCommand": "interaction",
              "musicStartCommand": "musicStart", "musicEndCommand": "musicEnd", "joinCommand": "join",
              "leaveCommand": "leave", "interactionCommand": "interaction", "awaitedCommand": "awaited",
              "deleteCommand": "delete", "banAddCommand": "banAdd", "banRemoveCommand": "banRemove"}
_CALLBACK = re.compile(r"^\$(onJoined|onLeave|onInteraction|onInteractionComplex|awaitedCommand|awaitedCommandError|"
                       r"onBanAdd|onBanRemove|onMessageDelete|onAutoComplete|alwaysReply|reaction)(?:\[(.*)\])?$",
                       re.IGNORECASE)
_KIND = {"onjoined": "join", "onleave": "leave", "oninteraction": "interaction", "oninteractioncomplex": "interaction",
         "awaitedcommand": "awaited", "awaitedcommanderror": "awaitedError", "onbanadd": "banAdd",
         "onbanremove": "banRemove", "onmessagedelete": "delete", "onautocomplete": "autocomplete",
         "alwaysreply": "always", "reaction": "reaction"}


_CHANNEL_CALLBACKS = {"join", "leave", "banAdd", "banRemove"}


@dataclass
class Command:
    code: str
    name: str = ""
    trigger: str = ""
    kind: str = "message"            # message, slash, ready, join, leave, interaction, awaited, awaitedError, ...
    arg: str = ""                    # callback argument: channel ID, custom ID, awaited name, ...
    aliases: List[str] = field(default_factory=list)
    description: str = ""
    folder: str = ""
    type: str = ""                   # the D.js-BDscript type as given
    options: List[Dict[str, Any]] = field(default_factory=list)
    ignore_case: bool = False
    contains: List[str] = field(default_factory=list)
    always: bool = False
    source: str = ""                 # file it came from

    @property
    def is_event(self) -> bool:
        return self.kind not in ("message", "always", "awaited")


class CommandManager:
    """Loads commands from a folder (D.js-BDscript's ``bot.manager``). Files:

    * ``*.bds`` / ``*.bdscript``: code, with an optional header block of ``key: value`` lines between ``---``::

        ---
        trigger: !ping
        aliases: p, pong
        ---
        Pong! $ping ms

      (``name:`` instead of ``trigger:`` uses the bot prefix; ``type:`` takes D.js-BDscript types or callback
      triggers such as ``$onJoined[123]``)
    * ``*.json``: one command object or a list of them
    * ``*.py``: a module-level ``command`` dict or ``commands`` list (D.js-BDscript's ``module.exports``)
    """

    def __init__(self, bot: "BDBot") -> None:
        self.bot = bot
        self.paths: List[str] = []
        self._mtimes: Dict[str, float] = {}

    @property
    def mainPath(self) -> Optional[str]:  # noqa: N802 (D.js-BDscript name)
        return self.paths[0] if self.paths else None

    def load(self, path: str) -> int:
        path = os.path.abspath(path)
        if path not in self.paths:
            self.paths.append(path)
        n = 0
        for root, _, files in os.walk(path):
            for f in sorted(files):
                full = os.path.join(root, f)
                for data in self._read(full):
                    data.setdefault("folder", os.path.relpath(root, path) if root != path else "")
                    self.bot.command(data, _source=full)
                    n += 1
                self._mtimes[full] = os.path.getmtime(full)
        return n

    def _read(self, full: str) -> List[Dict[str, Any]]:
        try:
            if full.endswith((".bds", ".bdscript")):
                text = open(full, encoding="utf-8").read()
                meta: Dict[str, Any] = {}
                if text.startswith("---"):
                    head, _, text = text[3:].partition("\n---")
                    text = text.lstrip("\n")
                    for line in head.strip().splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1)
                            meta[k.strip()] = v.strip()
                if "aliases" in meta and isinstance(meta["aliases"], str):
                    meta["aliases"] = [a.strip() for a in meta["aliases"].strip("[]").split(",") if a.strip()]
                if not meta.get("name") and not meta.get("trigger") and not meta.get("type"):
                    meta["name"] = os.path.splitext(os.path.basename(full))[0]
                meta["code"] = text
                return [meta]
            if full.endswith(".json"):
                data = json.load(open(full, encoding="utf-8"))
                return data if isinstance(data, list) else [data]
            if full.endswith(".py"):
                spec = importlib.util.spec_from_file_location(f"_bds_{abs(hash(full))}", full)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
                if hasattr(mod, "commands"):
                    return list(mod.commands)
                if hasattr(mod, "command"):
                    return [mod.command]
        except Exception as e:
            log.error("could not load command file %s: %s", full, e)
        return []

    def refresh(self) -> int:
        """Reload every loaded folder (``$updateCommands``)."""
        self.bot.commands = [c for c in self.bot.commands if not c.source]
        n = 0
        for p in list(self.paths):
            n += self.load(p)
        return n

    def changed(self) -> bool:
        for full, mt in list(self._mtimes.items()):
            if not os.path.exists(full) or os.path.getmtime(full) != mt:
                return True
        for p in self.paths:
            for root, _, files in os.walk(p):
                for f in files:
                    if os.path.join(root, f) not in self._mtimes:
                        return True
        return False

    async def watch(self, interval: float = 1.0) -> None:
        """Hot reload: re-read commands whenever a file changes."""
        while True:
            await asyncio.sleep(interval)
            if self.changed():
                log.info("commands changed, reloading (%d)", self.refresh())


class AudioManager:
    """Voice and music queues per community (``$joinVoice``, ``$playSong`` ...)."""

    @dataclass
    class Track:
        title: str
        url: str
        requester: str = ""
        duration: int = 0

    def __init__(self, bot: "BDBot") -> None:
        self.bot = bot
        self._clients: Dict[str, Any] = {}
        self._queues: Dict[str, List["AudioManager.Track"]] = {}
        self._current: Dict[str, Optional["AudioManager.Track"]] = {}
        self._ctx: Dict[str, Context] = {}

    def client_for(self, gid: str) -> Any:
        return self._clients.get(gid)

    async def join(self, ctx: Context, channel: Any) -> Any:
        vc = self._clients.get(ctx.guild_id)
        if vc is None or not vc.is_connected():
            vc = await channel.connect()
            self._clients[ctx.guild_id] = vc
        self._ctx[ctx.guild_id] = ctx
        return vc

    async def leave(self, gid: str) -> None:
        vc = self._clients.pop(gid, None)
        self._queues.pop(gid, None)
        if vc is not None:
            await vc.disconnect()

    async def _resolve(self, query: str) -> "AudioManager.Track":
        q = query.strip()
        if q.startswith(("http://", "https://")) and not re.search(r"youtu\.?be|soundcloud", q):
            return AudioManager.Track(title=q.rsplit("/", 1)[-1] or q, url=q)
        try:
            import yt_dlp  # optional: search and stream from YouTube & co.
        except ImportError:
            if os.path.isfile(q) and self.bot.allow_files:
                return AudioManager.Track(title=os.path.basename(q), url=q)
            raise ValueError("searching needs `pip install yt-dlp`; give a direct audio URL instead")

        def info() -> Dict[str, Any]:
            with yt_dlp.YoutubeDL({"format": "bestaudio/best", "quiet": True, "noplaylist": True,
                                   "default_search": "ytsearch1"}) as y:
                d = y.extract_info(q, download=False)
                return d["entries"][0] if "entries" in d else d
        d = await asyncio.get_running_loop().run_in_executor(None, info)
        return AudioManager.Track(title=d.get("title", q), url=d["url"], duration=int(d.get("duration") or 0))

    async def add(self, ctx: Context, query: str) -> "AudioManager.Track":
        gid = ctx.guild_id
        if self._clients.get(gid) is None:
            m = ctx.member()
            ch = getattr(getattr(m, "voice", None), "channel", None)
            if ch is None:
                raise ValueError("not in a voice channel ($joinVoice first)")
            await self.join(ctx, ch)
        track = await self._resolve(query)
        track.requester = ctx.author_id
        self._queues.setdefault(gid, []).append(track)
        self._ctx[gid] = ctx
        vc = self._clients[gid]
        if not vc.is_playing() and self._current.get(gid) is None:
            await self._next(gid)
        return track

    async def _next(self, gid: str) -> None:
        from ... import FFmpegPCMAudio

        q = self._queues.get(gid) or []
        vc = self._clients.get(gid)
        if not q or vc is None:
            self._current[gid] = None
            return
        track = q.pop(0)
        self._current[gid] = track
        src = FFmpegPCMAudio(track.url)
        await src.load()
        loop = asyncio.get_running_loop()

        def after(err: Optional[Exception]) -> None:
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._ended(gid, track)))
        vc.play(src, after=after)
        await self.bot._fire("musicStart", self._ctx.get(gid), extras={"track": track})

    async def _ended(self, gid: str, track: "AudioManager.Track") -> None:
        await self.bot._fire("musicEnd", self._ctx.get(gid), extras={"track": track})
        if self._current.get(gid) is track:
            self._current[gid] = None
            await self._next(gid)

    def skip(self, gid: str) -> None:
        vc = self._clients.get(gid)
        if vc is not None:
            vc.stop()

    def stop(self, gid: str) -> None:
        self._queues[gid] = []
        self.skip(gid)

    def pause(self, gid: str) -> None:
        vc = self._clients.get(gid)
        if vc is not None:
            vc.pause()

    def resume(self, gid: str) -> None:
        vc = self._clients.get(gid)
        if vc is not None:
            vc.resume()

    def queue(self, gid: str) -> List["AudioManager.Track"]:
        return list(self._queues.get(gid) or [])

    def current(self, gid: str) -> Optional["AudioManager.Track"]:
        return self._current.get(gid)


class BDBot:
    """A BDScript bot on Vector.

    >>> bot = BDBot(prefix="!")
    >>> bot.variables({"money": 0})
    >>> bot.command(trigger="!ping", code="Pong! $ping ms")
    >>> bot.run()   # VECTOR_NSEC from the environment, or bot.run("nsec1...")
    """

    def __init__(self, prefix: Union[str, Sequence[str]] = "!", *, token: Optional[str] = None,
                 owners: Iterable[str] = (), database: Optional[str] = None, data_dir: Optional[str] = None,
                 auto_variables: bool = False, mention_author: bool = True, prefix_variable: Optional[str] = None,
                 allow_http: bool = True, http_limit: int = 5, allow_exec: bool = False, allow_files: bool = False,
                 ai: Optional[Callable[..., Any]] = None, custom_images: Optional[Dict[str, str]] = None,
                 client: Optional[Client] = None, **client_options: Any) -> None:
        self.prefixes: List[str] = [prefix] if isinstance(prefix, str) else list(prefix)
        self.token = token
        self.owners: List[str] = [str(o) for o in owners]
        if data_dir:
            client_options["data_dir"] = data_dir
        self.client: Client = client or Client(intents=Intents.all(), **client_options)
        self.client.bdbot = self  # type: ignore[attr-defined]
        db = database or os.path.join(data_dir or ".", "bdscript.db")
        self.storage = Storage(db)
        self.commands: List[Command] = []
        self.variables_def: Dict[str, Any] = {}
        self.variable_types: Dict[str, str] = {}
        self.auto_variables = auto_variables
        self.mention_author = mention_author
        self.prefix_variable = prefix_variable
        self.allow_http, self.http_limit = allow_http, http_limit
        self.allow_exec, self.allow_files = allow_exec, allow_files
        self.ai = ai or _default_ai()
        self.custom_images: Dict[str, str] = dict(custom_images or {})
        self.mini_apps: Dict[str, str] = {}
        self.slash_data: Dict[str, Dict[str, Any]] = {}
        self.slash_commands: Dict[str, Dict[str, Any]] = {}
        self.views: Dict[str, Any] = {}
        self.slowmodes: Dict[str, int] = {}
        self.tickets: set = set(json.loads(self.storage.kv_get("tickets", "[]") or "[]"))
        self.threads: Dict[str, Any] = {}
        self.message_counts: Dict[str, int] = {}
        self.log_lines: List[str] = []
        self.started_at = time.time()
        self.manager = CommandManager(self)
        self.audio = AudioManager(self)
        self._awaits: Dict[tuple, Dict[str, Any]] = {}
        self._reaction_waits: Dict[str, Dict[str, Any]] = {}
        self._tasks: set = set()
        self._wire()

    # -- registration ---------------------------------------------------------------------------------------
    def command(self, data: Optional[Dict[str, Any]] = None, *, _source: str = "", **kwargs: Any) -> Command:
        """Add a command. BDFD style ``command(trigger="!ping", code=...)`` / ``command(trigger="$onJoined[id]")``,
        prefix style ``command(name="ping", aliases=[...], code=...)``, or a D.js-BDscript dict
        ``command({"name": "ping", "type": "basicCommand", "code": ...})``."""
        d = dict(data or {}, **kwargs)
        code = str(d.get("code", ""))
        cmd = Command(code=code, name=str(d.get("name") or ""), trigger=str(d.get("trigger") or ""),
                      aliases=list(d.get("aliases") or []), description=str(d.get("description") or ""),
                      folder=str(d.get("folder") or ""), type=str(d.get("type") or ""), source=_source)
        cb = _CALLBACK.match(cmd.trigger.strip()) or _CALLBACK.match(cmd.type.strip())
        if cb:
            cmd.kind, cmd.arg = _KIND[cb.group(1).lower()], (cb.group(2) or "").strip()
        elif cmd.type in FORK_TYPES:
            cmd.kind = FORK_TYPES[cmd.type]
            cmd.arg = cmd.name if cmd.kind == "interaction" else ""
        elif cmd.type in ("slash", "slashCommand"):
            cmd.kind = "slash"
        low = code.lower()
        cmd.ignore_case = "$ignoretriggercase" in low
        if "$alwaysreply" in low and cmd.kind == "message" and not cmd.trigger and not cmd.name:
            cmd.kind = "always"
        m = re.search(r"\$messagecontains\[([^\]]*)\]", code, re.IGNORECASE)
        if m:
            cmd.contains = [w for w in m.group(1).split(";") if w]
        if cmd.kind == "slash" and cmd.name and "options" in d:
            cmd.options = list(d["options"])
        compile_code(code)  # syntax errors surface at load time
        self.commands.append(cmd)
        return cmd

    def variables(self, defaults: Union[Dict[str, Any], Sequence[Dict[str, Any]]]) -> None:
        """Declare variables and defaults: ``{"money": 0}`` or D.js-BDscript's
        ``[{"name": "coins", "default": 0, "type": "INTEGER"}]``."""
        if isinstance(defaults, dict):
            for k, v in defaults.items():
                self.variables_def[k] = "" if v is None else v
        else:
            for v in defaults:
                self.variables_def[v["name"]] = v.get("default", "") if v.get("default") is not None else ""
                if v.get("type"):
                    self.variable_types[v["name"]] = str(v["type"]).upper()

    variable = variables  # D.js-BDscript name

    def event(self, *names: str) -> None:
        """D.js-BDscript compatibility: every event is always on, so this is a no-op."""

    def slash_command(self, name: str, description: str = "", options: Sequence[Dict[str, Any]] = (),
                      code: Optional[str] = None) -> None:
        """Define a slash command (shown in Vector's ``/`` picker). Options:
        ``{"name": "target", "type": "USER", "description": "...", "required": False, "choices": [...]}``."""
        self.slash_data[name] = {"name": name, "description": description or name, "options": list(options)}
        if code is not None:
            self.command(name=name, type="slashCommand", code=code)
        if self.client.is_ready():
            self.publish_slash([name])

    def createSlashCommandData(self, data: Dict[str, Any]) -> None:  # noqa: N802 (D.js-BDscript name)
        self.slash_data[data["name"]] = dict(data)

    def publish_slash(self, names: Optional[Sequence[str]] = None) -> None:
        for n in names or list(self.slash_data):
            d = self.slash_data.get(n) or {"name": n, "description": n, "options": []}
            args = []
            for o in d.get("options") or []:
                t = str(o.get("type", "STRING")).lower()
                t = {"user": "user", "integer": "integer", "number": "number", "boolean": "boolean",
                     "channel": "channel", "role": "role"}.get(t, "string")
                choices = [str(c.get("value", c.get("name")) if isinstance(c, dict) else c) for c in o.get("choices") or []]
                args.append((o["name"], t, o.get("description", o["name"]), bool(o.get("required")), choices))
            try:
                self.client.register_slash_command(n, d.get("description") or n, args)
                self.slash_commands[n] = d
            except Exception as e:
                log.warning("could not publish /%s: %s", n, e)

    def unpublish_slash(self, names: Optional[Sequence[str]] = None) -> None:
        for n in names or list(self.slash_commands):
            self.slash_commands.pop(n, None)
            unreg = getattr(self.client.native, "unregister_command", None) if self.client.native else None
            if unreg:
                try:
                    unreg(n)
                except Exception:
                    pass

    def get_command(self, name: str) -> Optional[Command]:
        for c in self.commands:
            if name in (c.name, c.trigger) or name in c.aliases:
                return c
        return None

    def reload(self) -> int:
        return self.manager.refresh()

    def later(self, coro: Any) -> None:
        t = asyncio.ensure_future(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    # -- running --------------------------------------------------------------------------------------------
    def run(self, token: Optional[str] = None, **kwargs: Any) -> None:
        self.client.run(token or self.token or os.environ.get("VECTOR_NSEC"), **kwargs)

    def login(self, token: Optional[str] = None) -> None:  # D.js-BDscript name
        self.run(token)

    async def start(self, token: Optional[str] = None) -> None:
        await self.client.start(token or self.token or os.environ.get("VECTOR_NSEC"))

    async def run_code(self, code: str, *, message: Any = None, channel: Any = None, author: Any = None,
                       args: Optional[List[str]] = None, send: bool = True, **extras: Any) -> str:
        """Run BDScript directly (handy for tests and REPLs)."""
        ctx = Context(self, message=message, channel=channel, author=author, args=args,
                      command=Command(code=code, name="eval"), extras=extras, mention_default=False)
        return await run(ctx, code, send=send)

    async def _fire(self, kind: str, base: Optional[Context] = None, *, arg: Optional[str] = None,
                    match: Optional[Callable[[Command], bool]] = None, **kw: Any) -> int:
        n = 0
        for cmd in list(self.commands):
            if cmd.kind != kind:
                continue
            if match is not None and not match(cmd):
                continue
            if arg is not None and cmd.arg and cmd.arg != arg:
                continue
            ckw = dict(kw)
            if cmd.kind in _CHANNEL_CALLBACKS:
                # $onJoined[channelID] etc. post into the given channel (or the community's system channel)
                g = ckw.get("guild")
                ch = self.client.get_channel(cmd.arg) if cmd.arg else getattr(g, "system_channel", None)
                if ch is None or (g is not None and getattr(ch, "guild", None) is not None and str(ch.guild.id) != str(g.id)):
                    continue
                ckw["channel"] = ch
            ctx = self._ctx_for(cmd, base, **ckw)
            self.later(run(ctx, cmd.code))
            n += 1
        return n

    def _ctx_for(self, cmd: Command, base: Optional[Context] = None, **kw: Any) -> Context:
        extras = dict(kw.pop("extras", {}) or {})
        if base is not None:
            kw.setdefault("message", base.message)
            kw.setdefault("channel", base.channel)
            kw.setdefault("author", base.author)
            kw.setdefault("guild", base.guild)
        mention = self.mention_author and cmd.kind in ("message", "always", "awaited") and not cmd.type
        return Context(self, command=cmd, extras=extras, mention_default=mention, **kw)

    # -- events ---------------------------------------------------------------------------------------------
    def _wire(self) -> None:
        c = self.client

        @c.event
        async def on_ready() -> None:
            self.started_at = time.time()
            self.publish_slash()
            await self._fire("ready", None, channel=None, author=c.user)

        @c.event
        async def on_message(message: Any) -> None:
            await self._on_message(message)

        @c.event
        async def on_member_join(member: Any) -> None:
            await self._fire("join", None, author=member, guild=member.guild)

        @c.event
        async def on_member_remove(member: Any) -> None:
            await self._fire("leave", None, author=member, guild=member.guild)

        @c.event
        async def on_member_ban(guild: Any, user: Any) -> None:
            await self._fire("banAdd", None, author=user, guild=guild)

        @c.event
        async def on_member_unban(guild: Any, user: Any) -> None:
            await self._fire("banRemove", None, author=user, guild=guild)

        @c.event
        async def on_message_delete(message: Any) -> None:
            await self._fire("delete", None, message=message, channel=message.channel, author=message.author,
                             extras={"deleted": True})

        @c.event
        async def on_reaction_add(reaction: Any, user: Any) -> None:
            await self._on_reaction(reaction, user)

        @c.event
        async def on_slash_command(name: str, args: Dict[str, Any], message: Any) -> None:
            opts = {k: str(v) for k, v in (args or {}).items()}
            base = Context(self, message=message)
            n = await self._fire("slash", base, args=list(opts.values()),
                                 match=lambda cmd: cmd.name == name or cmd.trigger.lstrip("/") == name,
                                 extras={"options": opts, "slash": True, "slash_name": name})
            if not n:  # BDFD: a slash command with the same name as a prefix command runs it
                for cmd in self.commands:
                    if cmd.kind == "message" and name in (cmd.name, cmd.trigger.lstrip("".join(self.prefixes))):
                        ctx = self._ctx_for(cmd, base, args=list(opts.values()),
                                            extras={"options": opts, "slash": True, "slash_name": name})
                        self.later(run(ctx, cmd.code))

        # a failing handler must never take the bot down
        @c.event
        async def on_error(event: str, *a: Any, **k: Any) -> None:
            log.exception("error in %s", event)

    def _prefixes_for(self, message: Any) -> List[str]:
        out = list(self.prefixes)
        if self.prefix_variable:
            g = getattr(message, "guild", None) or getattr(getattr(message, "channel", None), "guild", None)
            if g is not None:
                v = self.storage.get("server", self.prefix_variable, str(g.id))
                if v:
                    out.insert(0, v)
        return out

    async def _on_message(self, message: Any) -> None:
        author = message.author
        if getattr(author, "bot", False) or str(getattr(author, "id", "")) == str(getattr(self.client.user, "id", "")):
            return
        ch = message.channel
        self.message_counts[str(ch.id)] = self.message_counts.get(str(ch.id), 0) + 1
        content = message.content or ""
        base = Context(self, message=message)

        # awaited commands ($awaitFunc)
        key = (str(author.id), str(ch.id))
        waiting = self._awaits.pop(key, None)
        if waiting is not None:
            n = await self._fire("awaited", base, arg=waiting["name"], args=content.split(),
                                 extras={"awaited": waiting["name"]})
            if not n:
                await self._fire("awaitedError", base, arg=waiting["name"], args=content.split())
            return

        for cmd in list(self.commands):
            if cmd.kind == "always" or (cmd.kind == "message" and cmd.always):
                self.later(run(self._ctx_for(cmd, base, args=content.split()), cmd.code))
            elif cmd.contains and cmd.kind == "message" and not cmd.trigger and not cmd.name:
                low = content.lower()
                if any(w.lower() in low for w in cmd.contains):
                    self.later(run(self._ctx_for(cmd, base, args=content.split()), cmd.code))

        # triggers, longest first
        candidates = []
        prefixes = self._prefixes_for(message)
        for cmd in self.commands:
            if cmd.kind != "message":
                continue
            triggers = []
            if cmd.trigger:
                triggers.append(cmd.trigger)
            for p in prefixes:
                for n in [cmd.name] + cmd.aliases:
                    if n and not cmd.trigger:
                        triggers.append(p + n)
            for t in triggers:
                hay, needle = (content.lower(), t.lower()) if (cmd.ignore_case or not cmd.trigger) else (content, t)
                if hay == needle or hay.startswith(needle + " ") or hay.startswith(needle + "\n"):
                    candidates.append((len(t), cmd, content[len(t):].strip()))
        if not candidates:
            return
        best = max(c[0] for c in candidates)
        for length, cmd, rest in candidates:
            if length == best:
                ctx = self._ctx_for(cmd, base, args=rest.split() if rest else [])
                self.later(run(ctx, cmd.code))

    def await_command(self, name: str, user_id: str, channel_id: str, ctx: Context) -> None:
        self._awaits[(user_id, channel_id)] = {"name": name, "since": time.time()}

    async def _on_reaction(self, reaction: Any, user: Any) -> None:
        if str(getattr(user, "id", "")) == str(getattr(self.client.user, "id", "")):
            return
        mid = str(reaction.message.id)
        wait = self._reaction_waits.get(mid)
        if wait and str(user.id) == wait["user"]:
            name = wait["map"].get(str(reaction.emoji))
            if name:
                base = Context(self, message=reaction.message, author=user)
                await self._fire("awaited", base, arg=name, author=user, extras={"emoji": str(reaction.emoji)})
        await self._fire("reaction", Context(self, message=reaction.message, author=user), author=user,
                         arg=str(reaction.emoji), extras={"emoji": str(reaction.emoji)})

    # -- interactions ---------------------------------------------------------------------------------------
    async def dispatch_interaction(self, custom_id: str, interaction: Any, *, values: Optional[List[str]] = None,
                                   inputs: Optional[Dict[str, str]] = None) -> None:
        extras = {"custom_id": custom_id, "values": values or [], "inputs": inputs or {}}
        base = Context(self, message=interaction.message, channel=interaction.channel, author=interaction.user)
        tasks = []
        for cmd in self.commands:
            if cmd.kind != "interaction":
                continue
            if cmd.arg and cmd.arg != custom_id:
                continue
            ctx = self._ctx_for(cmd, base, author=interaction.user, interaction=interaction,
                                args=list(values or []), extras=extras)
            ctx.response.mention_author = False
            tasks.append(run(ctx, cmd.code))
        for t in tasks:
            await t

    def _build_modal(self, ctx: Context, spec: ModalSpec) -> Any:
        from ... import ui

        bot = self

        class _Modal(ui.Modal):
            async def on_submit(self, interaction: Any) -> None:
                values = {c.custom_id: c.value for c in self.children}
                await bot.dispatch_interaction(spec.custom_id, interaction, inputs=values)

        m = _Modal(title=spec.title, custom_id=spec.custom_id)
        for i in spec.inputs:
            m.add_item(ui.TextInput(label=i["label"], custom_id=i["id"],
                                    style=ui.TextStyle.paragraph if i["style"] != "short" else ui.TextStyle.short,
                                    placeholder=i.get("placeholder") or None, default=i.get("value") or None,
                                    required=i.get("required", True), min_length=i.get("min"), max_length=i.get("max")))
        return m

    def remember_view(self, message_id: str, view: Any) -> None:
        self.views[str(message_id)] = view

    async def edit_components(self, ctx: Context, message_id: str, change: Callable[[List[List[Any]]], Any]) -> None:
        view = self.views.get(str(message_id))
        rows = [list(r) for r in getattr(view, "bdscript_rows", [[]])] if view is not None else [[]]
        change(rows)
        new = build_view(ctx, rows)
        msg = await ctx.channel.fetch_message(message_id)
        if view is not None:
            try:
                view.stop()
            except Exception:
                pass
        await msg.edit(view=new)
        if new is not None:
            self.views[str(message_id)] = new
        else:
            self.views.pop(str(message_id), None)


def _default_ai() -> Optional[Callable[..., Any]]:
    """``$ai`` via Anthropic's API when ``ANTHROPIC_API_KEY`` is set (model: ``$BDSCRIPT_AI_MODEL``)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    model = os.environ.get("BDSCRIPT_AI_MODEL", "claude-haiku-5-5")

    async def ask(*, prompt: str, system: Optional[str], max_tokens: int, history: List[Dict[str, str]]) -> str:
        import urllib.request

        body = {"model": model, "max_tokens": max_tokens,
                "messages": [*history, {"role": "user", "content": prompt}]}
        if system:
            body["system"] = system

        def go() -> str:
            req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                         headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                                  "content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.loads(r.read())
            return "".join(b.get("text", "") for b in d.get("content", []))
        return await asyncio.get_running_loop().run_in_executor(None, go)
    return ask
