"""A bot split into cogs loaded as extensions, the discord.py way.

    cd examples/cogs_bot && python bot.py
"""

import os

import vector
from vector.ext import commands


class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or("!"),
            help_command=commands.EmbedHelpCommand(),
            owner_ids={os.environ["VECTOR_OWNER"]} if "VECTOR_OWNER" in os.environ else None,
        )

    async def setup_hook(self):
        # load cogs here so their commands are in the slash manifest Vector publishes on start
        for ext in ("cogs.moderation", "cogs.fun", "cogs.admin"):
            await self.load_extension(ext)

    async def on_ready(self):
        print(f"Ready as {self.user} with cogs: {', '.join(self.cogs)}")


MyBot().run(os.environ.get("VECTOR_NSEC"))
