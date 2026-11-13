"""Use BDScript inside a normal discord.py-style bot, and call it from Python.

    VECTOR_NSEC=nsec1... python examples/bdscript_in_bot.py
"""
from vector.ext import commands
from vector.ext.bdscript import BDScript, BDScriptError

bot = commands.Bot(command_prefix="!")
bd = BDScript(bot)
bd.variables({"coins": 0})

# 1. BDScript as ordinary commands
bd.add_command("coins", "$nomention You have $getUserVar[coins] coins.")
bd.add_command("shout", "$toUpperCase[$message]!", aliases=["yell"])


# 2. A Python function BDScript can call:  $roll[6]
@bd.function("roll")
def roll(ctx, sides="6"):
    import random
    try:
        return random.randint(1, int(sides))
    except ValueError:
        raise BDScriptError("sides must be a number")


# 3. Calling BDScript from your own command
@bot.command()
async def card(ctx, *, who: str = ""):
    r = await bd.run("$title[Hello $username]$description[You rolled a $roll[20]!]"
                     "$footer[$communityName]$addField[Asked about;" + (who or "nobody") + ";no]", ctx)
    if not r.ok:
        await ctx.send(f"script failed: {r.failure}")


# 4. Evaluate without sending anything
@bot.command()
async def calc(ctx, *, expr: str):
    out = await bd.evaluate_async("$calculate[" + expr.replace("]", "") + "]", ctx)
    await ctx.reply(out)


bot.run()
