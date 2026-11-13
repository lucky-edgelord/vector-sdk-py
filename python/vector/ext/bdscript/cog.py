"""A ready-made cog: ``bot.load_extension("vector.ext.bdscript.cog")``.

Adds owner-only ``!bd`` commands to a ``commands.Bot``:  ``!bd eval <code>``, ``!bd check <code>``, ``!bd functions [filter]``.
The engine is available as ``bot.bd``.
"""

from __future__ import annotations

from typing import Any

from ..commands import Cog, Context, group, is_owner
from .engine import BDScript
from .interpreter import compile_code
from .parser import ParseError
from .registry import FUNCTIONS


class BDScriptCog(Cog, name="BDScript"):
    def __init__(self, bot: Any, engine: BDScript) -> None:
        self.bot = bot
        self.bd = engine

    @group(name="bd", invoke_without_command=True)
    @is_owner()
    async def bd_group(self, ctx: Context) -> None:
        await ctx.send("`bd eval <code>` · `bd check <code>` · `bd functions [filter]`")

    @bd_group.command(name="eval")
    async def bd_eval(self, ctx: Context, *, code: str) -> None:
        r = await self.bd.run(code.strip("`"), ctx, send=True)
        if not r.text and not r.embeds and not r.rows:
            await ctx.send("(no output)")

    @bd_group.command(name="check")
    async def bd_check(self, ctx: Context, *, code: str) -> None:
        try:
            compile_code(code.strip("`"))
        except ParseError as e:
            await ctx.send(f"❌ Syntax error at {e.line}:{e.col}: {e}")
        else:
            await ctx.send("✅ Syntax is valid")

    @bd_group.command(name="functions")
    async def bd_functions(self, ctx: Context, filter: str = "") -> None:
        names = sorted(f.name for f in FUNCTIONS.values() if filter.lower() in f.name.lower())
        shown = ", ".join(names[:60])
        await ctx.send(f"{len(names)} functions" + (f": {shown}" + (" …" if len(names) > 60 else "") if names else ""))


async def setup(bot: Any) -> None:
    engine = getattr(bot, "bd", None) or BDScript(bot)
    bot.bd = engine
    await bot.add_cog(BDScriptCog(bot, engine))
