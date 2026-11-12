"""``vector.ext.commands``: a port of ``discord.ext.commands`` for Vector.

    from vector.ext import commands

    bot = commands.Bot(command_prefix="!")

    @bot.command()
    async def ping(ctx):
        await ctx.send("pong")
"""

from .bot import AutoShardedBot, Bot, BotBase, when_mentioned, when_mentioned_or
from .cog import Cog, CogMeta, GroupCog
from .context import Context
from .converter import *  # noqa: F401,F403
from .converter import Greedy, Range
from .cooldowns import BucketType, Cooldown, CooldownMapping, DynamicCooldownMapping, MaxConcurrency
from .core import *  # noqa: F401,F403
from .core import Command, Group, GroupMixin, Parameter
from .errors import *  # noqa: F401,F403
from .help import DefaultHelpCommand, EmbedHelpCommand, HelpCommand, MinimalHelpCommand, Paginator

HybridCommand = Command
HybridGroup = Group
