import asyncio
import random

import vector
from vector import ui
from vector.ext import commands, tasks


class Poll(ui.View):
    def __init__(self, question: str, options: list):
        super().__init__(timeout=300)
        self.question = question
        self.votes = {}
        select = ui.Select(placeholder=question, options=[ui.SelectOption(label=o) for o in options])
        select.callback = self.vote
        self.select = select
        self.add_item(select)

    async def vote(self, interaction: vector.Interaction):
        self.votes[interaction.user.npub] = self.select.values[0]
        tally = {}
        for v in self.votes.values():
            tally[v] = tally.get(v, 0) + 1
        lines = "\n".join(f"**{k}** {'▰' * n} {n}" for k, n in sorted(tally.items(), key=lambda x: -x[1]))
        await interaction.response.edit_message(content=f"📊 {self.question}\n\n{lines}")


class Fun(commands.Cog):
    """Games and toys."""

    def __init__(self, bot):
        self.bot = bot
        self.status_rotation.start()

    async def cog_unload(self):
        self.status_rotation.cancel()

    @tasks.loop(minutes=10)
    async def status_rotation(self):
        await self.bot.change_presence(activity=vector.Game(random.choice(["chess", "with npubs", "on relays"])))

    @status_rotation.before_loop
    async def before_status(self):
        await self.bot.wait_until_ready()

    @commands.command(name="8ball")
    async def eight_ball(self, ctx, *, question: str):
        """Ask the magic 8-ball."""
        await ctx.reply(random.choice(["Yes.", "No.", "Ask again later.", "Definitely.", "Doubtful."]))

    @commands.command()
    async def poll(self, ctx, question: str, *options: str):
        """Make a poll: !poll "Lunch?" pizza tacos sushi"""
        if not 2 <= len(options) <= 10:
            return await ctx.reply("Give 2–10 options")
        await ctx.send(f"📊 {question}", view=Poll(question, list(options)))

    @commands.command()
    async def guess(self, ctx):
        """Guess a number between 1 and 10."""
        answer = random.randint(1, 10)
        await ctx.send("I'm thinking of a number 1–10…")

        def check(m: vector.Message):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.isdigit()

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=15)
        except asyncio.TimeoutError:
            return await ctx.send(f"Too slow! It was {answer}.")
        await ctx.send("🎉 Correct!" if int(msg.content) == answer else f"Nope, it was {answer}.")


async def setup(bot):
    await bot.add_cog(Fun(bot))
