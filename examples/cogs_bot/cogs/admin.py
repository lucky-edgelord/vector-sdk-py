from vector.ext import commands


class Admin(commands.Cog, command_attrs={"hidden": True}):
    """Owner-only tools."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        return await self.bot.is_owner(ctx.author)

    @commands.command()
    async def reload(self, ctx, extension: str):
        """Hot-reload a cog: !reload cogs.fun"""
        await self.bot.reload_extension(extension)
        await ctx.react("🔁")

    @commands.command()
    async def shutdown(self, ctx):
        await ctx.send("Bye 👋")
        await self.bot.close()

    @commands.command()
    async def invite(self, ctx):
        """Make a join link for this Community."""
        invite = await ctx.guild.create_invite(max_age=86400, label="from the bot")
        await ctx.author.send(f"Invite (24h): {invite.url}")


async def setup(bot):
    await bot.add_cog(Admin(bot))
