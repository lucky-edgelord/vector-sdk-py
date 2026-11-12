"""Mini Apps (WebXDC): the bot joins live app sessions as a peer.

Share any ``.xdc`` app into a chat with the bot; when someone opens it, the handler runs with a
live session. This one keeps a shared counter: clients send {"t": "inc"}, the bot broadcasts
the new total.
"""

import os

import vector
from vector.ext import commands

bot = commands.Bot(command_prefix="!")
counts = {}


@bot.xdc_app("vector-counter", join_when="opened", idle_timeout=180)
async def counter(session: vector.XdcSession):
    key = session.app.message_id
    await session.send_json({"t": "count", "value": counts.get(key, 0)})
    async for event in session:
        if event.type == "peer_join":
            await session.send_json({"t": "count", "value": counts.get(key, 0)})
        elif event.type == "data":
            msg = event.json()
            if msg.get("t") == "inc":
                counts[key] = counts.get(key, 0) + 1
                await session.send_json({"t": "count", "value": counts[key], "by": event.verified_sender})


class Games(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.xdc_app("*")  # any other app: just log what happens
    async def any_app(self, session: vector.XdcSession):
        manifest = await session.app.manifest()
        print(f"session for {manifest.name} in {session.chat_id}")
        async for event in session:
            print(event)

    @commands.command()
    async def counter(self, ctx):
        """Share the counter app here."""
        app = await ctx.channel.send_xdc(os.path.join(os.path.dirname(__file__), "counter.xdc"))
        await ctx.send(f"Shared `{app.file_name}`: open it to play!")

    @commands.Cog.listener()
    async def on_xdc_presence(self, presence: vector.XdcPresence):
        print(f"{presence.user} {'opened' if presence.online else 'closed'} an app")


async def main_setup():
    await bot.add_cog(Games(bot))


bot.setup_hook = main_setup
bot.run(os.environ.get("VECTOR_NSEC"))
