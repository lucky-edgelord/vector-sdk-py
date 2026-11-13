"""``BDScript``: the engine attached to an *existing* bot, and callable from Python.

    from vector.ext import commands
    from vector.ext.bdscript import BDScript

    bot = commands.Bot(command_prefix="!")
    bd = BDScript(bot)                                   # extra listeners only; your handlers are untouched

    bd.add_command("balance", "$nomention You have $getUserVar[money] coins.")   # a real `!balance` command

    @bot.command()
    async def hello(ctx):
        result = await bd.run("Hi $username! $randomText[a;b;c]", ctx)             # call it from Python
        print(result.text, result.embeds)

    print(bd.evaluate("$sum[2;3] $toUpperCase[ok]"))                               # -> "5 OK" (no bot needed)
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from .bot import BDBot, Command
from .context import Context
from .interpreter import run as _run
from .registry import FUNCTIONS, fn

__all__ = ("BDScript", "Result")


@dataclass
class Result:
    """What one run produced. ``str(result)`` is the text."""

    text: str = ""
    failure: Optional[str] = None      # the BDFD-style error message, or the message of a failed $onlyIf/$argsCheck
    embeds: List[Any] = field(default_factory=list)   # vector.Embed objects, in $embed index order
    rows: List[List[Any]] = field(default_factory=list)
    reactions: List[str] = field(default_factory=list)
    files: List[Any] = field(default_factory=list)
    sent: List[str] = field(default_factory=list)      # ids of messages the script sent itself ($sendMessage...)
    context: Optional[Context] = None

    @property
    def ok(self) -> bool:
        return self.failure is None

    def __str__(self) -> str:
        return self.text

    def __bool__(self) -> bool:
        return self.ok


def _split_args(args: Union[None, str, Sequence[Any]]) -> List[str]:
    if args is None:
        return []
    if isinstance(args, str):
        return args.split()
    return [str(a) for a in args]


class BDScript(BDBot):
    """A BDScript engine that rides on a bot you already have (``vector.Client`` or ``commands.Bot``).

    Everything on :class:`BDBot` works too (``command()``, ``variables()``, file-based commands...).
    Pass ``listen=False`` for a pure library: no events are hooked and nothing runs unless you call it.
    """

    def __init__(self, client: Any = None, *, prefix: Union[str, Sequence[str]] = "!", listen: bool = True,
                 **kw: Any) -> None:
        if client is None:
            from ...client import Client

            client = Client()
        # as an add-on the engine's own prefix commands are opt-in: with a commands.Bot use add_command()
        super().__init__(prefix, client=client, listen=listen, **kw)

    # -- calling BDScript from Python ----------------------------------------------------------------------
    def _context(self, code: str, ctx: Any = None, *, message: Any = None, channel: Any = None, author: Any = None,
                 guild: Any = None, args: Union[None, str, Sequence[Any]] = None, vars: Optional[Dict[str, Any]] = None,
                 extras: Optional[Dict[str, Any]] = None, mention: bool = False) -> Context:
        if ctx is not None:                     # a commands.Context, a Message or a channel
            message = message or getattr(ctx, "message", None) or (ctx if hasattr(ctx, "content") else None)
            if channel is None:
                channel = getattr(ctx, "channel", None) or getattr(message, "channel", None)
            author = author or getattr(ctx, "author", None) or getattr(message, "author", None)
        c = Context(self, message=message, channel=channel, author=author, guild=guild, args=_split_args(args),
                    command=Command(code=code, name="eval"), extras=extras, mention_default=mention)
        for k, v in (vars or {}).items():       # pre-set $var[...] values
            c.vars[str(k)] = str(v)
        return c

    async def run(self, code: str, ctx: Any = None, *, send: Optional[bool] = None, **kw: Any) -> Result:
        """Run BDScript.

        ``ctx`` may be a ``commands.Context``, a ``Message`` or a channel; or pass ``channel=``/``author=``/
        ``guild=``/``message=`` yourself. By default the reply (text, embeds, buttons...) is sent when there is
        somewhere to send it; ``send=False`` just returns the :class:`Result`.
        """
        context = self._context(code, ctx, **kw)
        if send is None:
            send = context.channel is not None
        text = await _run(context, code, send=send)
        r = context.response
        return Result(text=text, failure=context.failure, embeds=[r.embeds[i] for i in sorted(r.embeds)],
                      rows=[row for row in r.rows if row], reactions=list(r.reactions), files=list(r.files),
                      sent=list(context.sent_ids), context=context)

    async def evaluate_async(self, code: str, ctx: Any = None, **kw: Any) -> str:
        """Like :meth:`run` with ``send=False``, returning just the text."""
        return (await self.run(code, ctx, send=False, **kw)).text

    def evaluate(self, code: str, ctx: Any = None, **kw: Any) -> str:
        """Synchronous convenience for scripts, tests and REPLs (not inside a running event loop)."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.evaluate_async(code, ctx, **kw))
        raise RuntimeError("evaluate() can't run inside an event loop; use `await bd.evaluate_async(...)`")

    # -- exposing it as discord.py-style commands --------------------------------------------------------------
    def as_command(self, name: str, code: str, *, aliases: Sequence[str] = (), **attrs: Any) -> Any:
        """A ``commands.Command`` whose body is BDScript: ``bot.add_command(bd.as_command('ping', '$ping ms'))``.

        The words after the command become ``$message[1]``, ``$message[2]``...
        """
        from ..commands import command as _command

        engine = self

        async def callback(ctx: Any, *args: str) -> None:
            await engine.run(code, ctx, args=list(args), mention=engine.mention_author)

        callback.__name__ = name.replace("-", "_")
        return _command(name=name, aliases=list(aliases), **attrs)(callback)

    def add_command(self, name: str, code: str, **attrs: Any) -> Any:
        """Register BDScript ``code`` as a real command on the attached ``commands.Bot``."""
        if not hasattr(self.client, "add_command"):
            raise TypeError("the attached client has no add_command(); pass a commands.Bot, or use "
                            "bd.command(trigger='!name', code=...) for BDScript's own prefix handling")
        cmd = self.as_command(name, code, **attrs)
        self.client.add_command(cmd)
        return cmd

    # -- calling Python from BDScript ---------------------------------------------------------------------------
    def function(self, *names: str, brackets: str = "optional", **opts: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Teach BDScript a new function written in Python.

            @bd.function("shout")
            def shout(ctx, text=""):          # strings in, string out; async functions work too
                return text.upper() + "!"
        ``$shout[hello]`` -> ``HELLO!``. Raise ``BDScriptError("...")`` to fail like a built-in. The registry is
        process-wide, so the function is available to every engine.
        """
        def deco(impl: Callable[..., Any]) -> Callable[..., Any]:
            def wrapper(ctx: Context, *args: str) -> Any:
                out = impl(ctx, *args)
                if inspect.isawaitable(out):
                    async def finish() -> str:
                        return _to_text(await out)
                    return finish()
                return _to_text(out)

            wrapper.__name__ = getattr(impl, "__name__", "custom")
            try:
                n = len(inspect.signature(impl).parameters) - 1
                wrapper.__signature__ = inspect.signature(impl)  # type: ignore[attr-defined]
            except (TypeError, ValueError):
                n = 0
            fn(*names, brackets=brackets, status="custom", **opts)(wrapper)
            return impl

        return deco

    def functions(self) -> List[str]:
        return sorted(FUNCTIONS)


def _to_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)
