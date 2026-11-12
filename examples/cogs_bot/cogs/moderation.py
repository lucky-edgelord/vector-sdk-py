import datetime
from typing import Optional

import vector
from vector.ext import commands


class Moderation(commands.Cog):
    """Keep the Community tidy."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        return ctx.guild is not None  # every command here is Community-only

    @commands.command()
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: vector.Member, *, reason: Optional[str] = None):
        """Kick a member."""
        await member.kick(reason=reason)
        await ctx.send(f"👢 Kicked **{member.display_name}**")

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, members: commands.Greedy[vector.Member]):
        """Ban one or more members (a single rekey for all of them)."""
        await ctx.guild.bulk_ban(members)
        await ctx.send(f"🔨 Banned {len(members)} member(s)")

    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def timeout(self, ctx, member: vector.Member, minutes: int = 10):
        """Time someone out."""
        await member.timeout(datetime.timedelta(minutes=minutes))
        await ctx.send(f"⏳ {member.display_name} is timed out for {minutes} minutes")

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx, amount: int = 10):
        """Delete recent messages."""
        deleted = await ctx.channel.purge(limit=amount)
        await ctx.send(f"🧹 Removed {len(deleted)} messages", delete_after=5)

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx):
        """Stop @everyone sending in this channel."""
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
        await ctx.send("🔒 Channel locked")

    @commands.command()
    @commands.has_permissions(view_audit_log=True)
    async def audit(self, ctx, limit: int = 5):
        """Show recent moderation actions."""
        lines = []
        async for entry in ctx.guild.audit_logs(limit=limit):
            lines.append(f"{vector.utils.format_dt(entry.created_at, 'R')} **{entry.user.display_name}** {entry.action}")
        await ctx.send("\n".join(lines) or "Nothing yet")

    @commands.Cog.listener()
    async def on_member_ban(self, guild: vector.Guild, user: vector.User):
        if guild.system_channel:
            await guild.system_channel.send(f"🔨 {user.display_name} was banned")

    @kick.error
    @ban.error
    async def mod_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("You can't do that here.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply(f"Couldn't find {error.argument!r}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
