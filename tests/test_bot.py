import asyncio
from typing import Literal, Optional

import pytest

import vector
from vector import app_commands, ui
from vector.ext import commands, tasks

from conftest import ALICE, BOT, COMMUNITY, GENERAL, MOD, VOICE, incoming, raw_message


async def test_client_events_and_wait_for(harness_factory):
    client = vector.Client(intents=vector.Intents.default())
    seen = []

    @client.event
    async def on_ready():
        seen.append("ready")

    @client.event
    async def on_message(message: vector.Message):
        seen.append((message.content, message.author.name, message.guild.name, message.channel.name))
        if message.content == "hi":
            await message.channel.send("hello!")

    @client.listen("on_message")
    async def extra(message):
        seen.append("listener")

    h = await harness_factory(client)
    assert client.is_ready() and "ready" in seen
    assert client.get_guild(COMMUNITY).name == "Test Community"
    assert [c.name for c in client.guilds[0].text_channels] == ["general"]
    assert isinstance(client.guilds[0].get_channel(VOICE), vector.VoiceChannel)

    waiter = asyncio.ensure_future(client.wait_for("message", check=lambda m: m.content == "ping", timeout=2))
    await h.say("hi")
    await h.say("ping")
    msg = await waiter
    assert msg.content == "ping"
    assert ("hi", "alice", "Test Community", "general") in seen
    assert "listener" in seen
    assert h.texts == ["hello!"]
    await h.stop()


async def test_message_delete_uses_cache(harness_factory):
    client = vector.Client()
    deleted = []

    @client.event
    async def on_message_delete(message):
        deleted.append(message.content)

    @client.event
    async def on_raw_message_delete(payload):
        deleted.append(("raw", payload.moderated))

    h = await harness_factory(client)
    data = incoming("secret")
    await h.emit({"type": "message", "message": data})
    await h.emit({"type": "message_delete", "chat_id": GENERAL, "message_id": data["message"]["id"], "by": ALICE,
                  "moderated": False, "at": 1})
    assert "secret" in deleted and ("raw", False) in deleted
    await h.stop()


async def test_prefix_and_native_commands(harness_factory):
    bot = commands.Bot(command_prefix="!")
    calls = []

    @bot.command(aliases=["r"])
    async def roll(ctx, sides: int = 6, label: Optional[str] = None):
        """Roll a die."""
        calls.append(("roll", sides, label, ctx.prefix))
        await ctx.reply(f"rolled d{sides}")

    @bot.command()
    @commands.describe(target="who to greet")
    async def greet(ctx, target: vector.Member, *, message: str = "hi"):
        calls.append(("greet", target.name, message))

    @bot.command()
    async def unit(ctx, temp: float, scale: Literal["c", "f"]):
        calls.append(("unit", temp, scale))

    h = await harness_factory(bot)

    # published as native slash commands with typed args
    assert bot.native.commands["roll"][1] == [("sides", "int", "sides", False, []), ("label", "string", "label", False, [])]
    assert bot.native.commands["greet"][1][0] == ("target", "user", "who to greet", True, [])
    assert bot.native.commands["greet"][1][1][1] == "string"
    assert bot.native.commands["unit"][1][1] == ("scale", "choice", "scale", True, ["c", "f"])
    assert "help" in bot.native.commands

    await h.say("!roll 20 big one")
    await h.say("!r")
    await h.say(f"!greet nostr:{MOD} good morning all")
    await h.slash("roll", {"sides": 12, "label": None})
    await h.slash("greet", {"target": MOD, "message": "yo"})
    await h.slash("unit", {"temp": 21.5, "scale": "c"})
    await asyncio.sleep(0.1)
    assert ("roll", 20, "big", "!") in calls
    assert ("roll", 6, None, "!") in calls
    assert ("greet", "mod", "good morning all") in calls
    assert ("roll", 12, None, "/") in calls
    assert ("greet", "mod", "yo") in calls
    assert ("unit", 21.5, "c") in calls
    assert "rolled d20" in h.texts
    replies = [s for s in h.native.sent if s["text"] == "rolled d20"]
    assert replies[0]["reply_to"] is not None
    await h.stop()


async def test_errors_checks_cooldowns(harness_factory):
    bot = commands.Bot(command_prefix="!")
    errors = []

    @bot.command()
    @commands.has_permissions(kick_members=True)
    async def kick(ctx, member: vector.Member):
        await member.kick()

    @bot.command()
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def daily(ctx):
        await ctx.send("claimed")

    @bot.command()
    async def boom(ctx):
        raise RuntimeError("kaboom")

    @boom.error
    async def boom_error(ctx, error):
        errors.append(("local", type(error).__name__, type(error.original).__name__))

    @bot.event
    async def on_command_error(ctx, error):
        errors.append(type(error).__name__)

    h = await harness_factory(bot)
    await h.say(f"!kick {MOD}", author=ALICE)
    await h.say(f"!kick {ALICE}", author=MOD)
    await h.say("!daily")
    await h.say("!daily")
    await h.say("!boom")
    await h.say("!nope")
    await h.say("!kick", author=MOD)
    await asyncio.sleep(0.1)
    assert "MissingPermissions" in errors
    assert ("kick", ALICE) in h.native.calls
    assert h.texts.count("claimed") == 1 and "CommandOnCooldown" in errors
    assert ("local", "CommandInvokeError", "RuntimeError") in errors
    assert "CommandNotFound" in errors
    assert "MissingRequiredArgument" in errors
    await h.stop()


async def test_cogs_groups_and_help(harness_factory):
    class Music(commands.Cog):
        """Play some tunes."""

        def __init__(self, bot):
            self.bot = bot
            self.events = []

        @commands.group(invoke_without_command=True)
        async def queue(self, ctx):
            self.events.append("queue")

        @queue.command()
        async def add(self, ctx, *, song: str):
            self.events.append(("add", song))

        @queue.command()
        async def clear(self, ctx):
            self.events.append("clear")

        @commands.Cog.listener()
        async def on_member_join(self, member):
            self.events.append(("join", member.name))

        async def cog_check(self, ctx):
            return ctx.author.npub != MOD

    class MyBot(commands.Bot):
        async def setup_hook(self):
            await self.add_cog(Music(self))

    bot = MyBot(command_prefix="!", description="Test bot")
    h = await harness_factory(bot)
    cog = bot.get_cog("Music")
    assert bot.native.commands["queue"][1][0] == ("subcommand", "choice", "what to do", False, ["add", "clear"])

    await h.say("!queue")
    await h.say("!queue add Never Gonna Give You Up")
    await h.slash("queue", {"subcommand": "clear", "args": None})
    await h.slash("queue", {"subcommand": "add", "args": "Darude Sandstorm"})
    await h.say("!queue clear", author=MOD)  # cog_check blocks MOD
    await h.emit({"type": "member_join", "community_id": COMMUNITY, "channel_id": GENERAL, "npub": ALICE,
                  "invited_by": None, "invite_label": None})
    await asyncio.sleep(0.1)
    assert cog.events.count("queue") == 1
    assert ("add", "Never Gonna Give You Up") in cog.events
    assert ("add", "Darude Sandstorm") in cog.events
    assert cog.events.count("clear") == 1
    assert ("join", "alice") in cog.events

    await h.say("!help")
    await asyncio.sleep(0.05)
    help_text = h.texts[-1]
    assert "**Music**" in help_text and "`!queue`" in help_text and "Test bot" in help_text

    await bot.remove_cog("Music")
    assert bot.get_command("queue") is None
    await h.stop()


async def test_views_buttons_and_selects(harness_factory):
    bot = commands.Bot(command_prefix="!")
    clicks = []

    class Confirm(ui.View):
        @ui.button(label="Yes", emoji="✅", style=ui.ButtonStyle.success)
        async def yes(self, interaction: vector.Interaction, button: ui.Button):
            clicks.append(("yes", interaction.user.name))
            await interaction.response.send_message("Confirmed")
            self.stop()

        @ui.button(label="No")
        async def no(self, interaction, button):
            clicks.append("no")

        @ui.select(placeholder="Pick a colour", options=[ui.SelectOption(label="Red"), ui.SelectOption(label="Blue", value="b")])
        async def colour(self, interaction, select):
            clicks.append(("select", select.values))

    view_holder = {}

    @bot.command()
    async def ask(ctx):
        view = Confirm(timeout=30)
        view_holder["v"] = view
        view_holder["m"] = await ctx.send("Sure?", view=view)

    h = await harness_factory(bot)
    await h.say("!ask")
    await asyncio.sleep(0.1)
    msg = view_holder["m"]
    sent = h.native.sent[-1]["text"]
    assert "Sure?" in sent and "Yes" not in sent and "🇦 No" in sent
    assert "1️⃣ Red" in sent and "2️⃣ Blue" in sent
    assert [e for (m, e) in h.native.reactions if m == msg.id] == ["✅", "🇦", "1️⃣", "2️⃣"]

    def react(emoji, who=ALICE):
        return {"type": "reaction_add", "chat_id": GENERAL,
                "message": raw_message("Sure?", BOT, mid=msg.id, mine=True),
                "reaction": {"id": "x" + emoji, "reference_id": msg.id, "author_id": who, "emoji": emoji}, "at": 1}

    await h.emit(react("2️⃣"))
    await h.emit(react("🇦"))
    await h.emit(react("✅"))
    await asyncio.sleep(0.1)
    assert ("select", ["b"]) in clicks and "no" in clicks and ("yes", "alice") in clicks
    assert "Confirmed" in h.texts
    assert await asyncio.wait_for(view_holder["v"].wait(), 1) is False
    await h.stop()


async def test_tasks_loop_and_app_commands(harness_factory):
    ticks = []

    @tasks.loop(seconds=0.01, count=3)
    async def ticker():
        ticks.append(ticker.current_loop)

    ticker.start()
    await asyncio.sleep(0.2)
    assert ticks == [0, 1, 2] and not ticker.is_running()

    client = vector.Client()
    tree = app_commands.CommandTree(client)
    got = []

    @tree.command(name="weather", description="Get the weather")
    @app_commands.describe(city="which city")
    @app_commands.choices(units=[app_commands.Choice(name="Celsius", value="c"), app_commands.Choice(name="Fahrenheit", value="f")])
    async def weather(interaction: vector.Interaction, city: str, units: str = "c"):
        got.append((city, units, interaction.user.name))
        await interaction.response.send_message(f"{city}: sunny")

    h = await harness_factory(client)
    assert h.native.commands["weather"][1] == [("city", "string", "which city", True, []),
                                               ("units", "choice", "units", False, ["c", "f"])]
    await h.slash("weather", {"city": "Lisbon", "units": "f"})
    await asyncio.sleep(0.05)
    assert got == [("Lisbon", "f", "alice")]
    assert "Lisbon: sunny" in h.texts
    await h.stop()


async def test_send_with_embed_file_and_delete_after(harness_factory):
    client = vector.Client()
    h = await harness_factory(client)
    channel = client.get_channel(GENERAL)
    e = vector.Embed(title="Chart", colour=0x00FF00).set_image(url="attachment://chart.png")
    await channel.send("Here:", embed=e, file=vector.File(b"\x89PNG....", filename="chart.png"))
    last = h.native.sent[-1]
    assert last["file"] == "chart.png" and "Here:" in last["text"] and "**Chart**" in last["text"]

    msg = await channel.send("temp", delete_after=0.05)
    assert h.native.sent[-1]["expires_in"] == 1
    await asyncio.sleep(0.15)
    assert ("delete", msg.id) in h.native.calls

    user = client.get_user(ALICE) or await client.fetch_user(ALICE)
    await user.send("psst")
    assert h.native.sent[-1]["channel"] == ALICE and h.native.sent[-1]["kind"] == "dm"
    await h.stop()


async def test_community_change_events(harness_factory):
    client = vector.Client()
    got = []

    @client.event
    async def on_guild_role_create(role):
        got.append(("role", role.name))

    @client.event
    async def on_member_ban(guild, user):
        got.append(("ban", guild.name, user.npub))

    @client.event
    async def on_community_change(change):
        got.append(("change", change.kind))

    h = await harness_factory(client)
    await h.emit({"type": "community_change", "community_id": COMMUNITY,
                  "change": {"change": "role_created", "role": {"role_id": "r9", "name": "VIP", "position": 2,
                                                                 "permissions": 0, "scope": {"kind": "server"}}}})
    await h.emit({"type": "community_change", "community_id": COMMUNITY,
                  "change": {"change": "member_banned", "member": ALICE}})
    assert ("role", "VIP") in got and ("ban", "Test Community", ALICE) in got
    assert ("change", "role_created") in got and ("change", "member_banned") in got
    assert client.get_guild(COMMUNITY).get_role("r9").name == "VIP"
    await h.stop()


async def test_cog_error_handlers_greedy_and_varargs(harness_factory):
    got = []

    class Mod(commands.Cog):
        @commands.command()
        @commands.has_permissions(ban_members=True)
        async def ban(self, ctx, members: commands.Greedy[vector.Member], *, reason: str = "none"):
            got.append(("ban", [m.name for m in members], reason))

        @commands.command()
        async def poll(self, ctx, question: str, *options: str):
            got.append(("poll", question, options))

        @ban.error
        async def on_ban_error(self, ctx, error):
            got.append(("error", type(error).__name__))

    bot = commands.Bot(command_prefix="!")
    h = await harness_factory(bot)
    await bot.add_cog(Mod())
    assert "poll" in bot.native.commands  # registered natively after login too
    await h.say(f"!ban {ALICE} nostr:{BOT} being rude", author=MOD)
    await h.say(f"!ban {ALICE}", author=ALICE)
    await h.say('!poll "Lunch today?" pizza tacos')
    await h.slash("poll", {"question": "Dinner?", "options": 'soup "fish pie"'})
    await asyncio.sleep(0.1)
    assert ("ban", ["alice", "testbot"], "being rude") in got
    assert ("error", "MissingPermissions") in got
    assert ("poll", "Lunch today?", ("pizza", "tacos")) in got
    assert ("poll", "Dinner?", ("soup", "fish pie")) in got
    await h.stop()


async def test_compat_runs_unmodified_discord_code(tmp_path):
    import subprocess, sys, textwrap
    bot = tmp_path / "bot.py"
    bot.write_text(textwrap.dedent('''
        import discord
        from discord.ext import commands, tasks
        from discord import ui
        intents = discord.Intents.default(); intents.message_content = True
        bot = commands.Bot(command_prefix="!", intents=intents)
        class Cog(commands.Cog):
            @commands.command()
            async def hi(self, ctx): await ctx.send(embed=discord.Embed(title="x"))
        bot.add_cog(Cog(bot))
        class V(discord.ui.View):
            @discord.ui.button(label="a", style=discord.ButtonStyle.primary)
            async def a(self, i, b): pass
        print("OK", discord.__name__, isinstance(bot, discord.Client), "hi" in bot.all_commands)
    '''))
    r = subprocess.run([sys.executable, "-m", "vector.compat", str(bot)], capture_output=True, text=True, timeout=60)
    assert "OK vector True True" in r.stdout, r.stderr


async def test_embed_image_sits_above_footer_and_buttons_on_last(harness_factory):
    import datetime as _dt

    class V(ui.View):
        @ui.button(label="A")
        async def a(self, i, b): pass

    client = vector.Client()
    h = await harness_factory(client)
    ch = client.get_channel(GENERAL)
    e = vector.Embed(title="T", description="body", timestamp=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc))
    e.set_image(url="attachment://pic.png"); e.set_footer(text="foot")
    msg = await ch.send(embed=e, file=vector.File(__import__("io").BytesIO(b"x"), filename="pic.png"), view=V())
    first, second = h.native.sent[-2], h.native.sent[-1]
    assert first["file"] == "pic.png" and "foot" not in first["text"] and "> body" in first["text"]
    assert second["text"].startswith("> -# foot") and msg.id == second["id"]
