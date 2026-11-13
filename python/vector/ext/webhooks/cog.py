"""Chat commands for managing webhooks from inside Vector: ``!webhook create|list|delete``."""

from __future__ import annotations

from typing import Any

from ... import ui  # noqa: F401
from ...ext import commands
from .store import WebhookStore


class WebhookCog(commands.Cog, name="Webhooks"):
    """Create Discord-compatible webhook URLs for the current channel. The URL contains the secret token, so it is
    sent to you in a DM and shown only once."""

    def __init__(self, bot: Any, store: WebhookStore, base_url: str) -> None:
        self.bot, self.store, self.base_url = bot, store, base_url.rstrip("/")

    @commands.group(name="webhook", invoke_without_command=True)
    @commands.guild_only()
    async def webhook(self, ctx: commands.Context) -> None:
        await ctx.send("`webhook create <name>` · `webhook list` · `webhook delete <id>`")

    @webhook.command(name="create")
    @commands.has_permissions(manage_channels=True)
    async def create(self, ctx: commands.Context, *, name: str = "webhook") -> None:
        wh, token = self.store.create(name, ctx.channel.id, ctx.guild.id, ctx.author.id)
        await ctx.author.send(f"**Webhook “{wh.name}”** for #{ctx.channel.name}\n"
                              f"`{self.base_url}/api/webhooks/{wh.id}/{token}`\n"
                              f"Use it anywhere a Discord webhook URL works. Keep it secret.")
        await ctx.send(f"Created webhook `{wh.id}`; the URL is in your DMs.")

    @webhook.command(name="list")
    @commands.has_permissions(manage_channels=True)
    async def list_(self, ctx: commands.Context) -> None:
        rows = self.store.list(channel_id=ctx.channel.id)
        await ctx.send("\n".join(f"`{w.id}` {w.name}" for w in rows) or "No webhooks in this channel.")

    @webhook.command(name="delete")
    @commands.has_permissions(manage_channels=True)
    async def delete(self, ctx: commands.Context, webhook_id: str) -> None:
        wh = self.store.get(webhook_id)
        if wh is None or wh.channel_id != ctx.channel.id:
            await ctx.send("No such webhook in this channel.")
            return
        self.store.delete(webhook_id)
        await ctx.send(f"Deleted webhook `{webhook_id}`.")
