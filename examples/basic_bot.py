"""The smallest useful bot: events, a few commands, an embed.

    export VECTOR_NSEC=nsec1...        # or leave unset: a key is created and stored on first run
    python examples/basic_bot.py
"""

import os
import random
from typing import Literal, Optional

import vector
from vector.ext import commands

bot = commands.Bot(
    command_prefix="!",                    # "!ping" works, and so does Vector's native "/ping"
    description="A friendly example bot",
    owner_id=os.environ.get("VECTOR_OWNER"),  # your npub, for @commands.is_owner()
    invite_policy="public",                # auto-accept Community invites
)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.npub})")
    print(f"In {len(bot.guilds)} communities")
    await bot.change_presence(activity=vector.Game("with Nostr"))


@bot.event
async def on_member_join(member: vector.Member):
    channel = member.guild.system_channel
    if channel:
        await channel.send(f"Welcome {member.mention}! 👋")


@bot.command()
async def ping(ctx: commands.Context):
    """Check the bot is alive."""
    await ctx.reply("pong 🏓")


@bot.command()
@commands.describe(sides="how many sides", times="how many dice")
async def roll(ctx, sides: int = 6, times: int = 1):
    """Roll some dice."""
    rolls = [random.randint(1, sides) for _ in range(min(times, 20))]
    await ctx.send(f"🎲 {', '.join(map(str, rolls))} (total **{sum(rolls)}**)")


@bot.command()
async def convert(ctx, temp: float, unit: Literal["c", "f"]):
    """Convert a temperature."""
    if unit == "c":
        await ctx.send(f"{temp}°C = {temp * 9 / 5 + 32:.1f}°F")
    else:
        await ctx.send(f"{temp}°F = {(temp - 32) * 5 / 9:.1f}°C")


@bot.command()
@commands.guild_only()
async def whois(ctx, member: Optional[vector.Member] = None):
    """Show someone's profile."""
    member = member or ctx.author
    embed = vector.Embed(title=member.display_name, description=member.about or "*no bio*", colour=member.colour)
    embed.add_field(name="npub", value=f"`{member.npub[:20]}…`", inline=False)
    embed.add_field(name="Roles", value=", ".join(r.name for r in member.roles[1:]) or "none")
    embed.add_field(name="Top role", value=member.top_role.name)
    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)
    embed.timestamp = vector.utils.utcnow()
    await ctx.send(embed=embed)


@bot.command()
async def echo(ctx, *, text: str):
    """Repeat after me."""
    await ctx.send(text)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply(f"Missing `{error.param.name}`. Usage: `{ctx.prefix}{ctx.command} {ctx.command.signature}`")
    elif isinstance(error, commands.CheckFailure):
        await ctx.reply(f"🚫 {error}")
    else:
        raise error


bot.run(os.environ.get("VECTOR_NSEC"))
