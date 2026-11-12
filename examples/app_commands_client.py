"""discord.py's ``app_commands`` style on a plain Client (no prefix commands at all)."""

import os

import vector
from vector import app_commands

client = vector.Client()
tree = app_commands.CommandTree(client)


@tree.command(name="hello", description="Say hello to someone")
@app_commands.describe(user="who to greet")
async def hello(interaction: vector.Interaction, user: vector.Member):
    await interaction.response.send_message(f"Hello {user.mention}! 👋")


@tree.command(description="Pick a size")
@app_commands.choices(size=[
    app_commands.Choice(name="Small", value="s"),
    app_commands.Choice(name="Medium", value="m"),
    app_commands.Choice(name="Large", value="l"),
])
async def order(interaction: vector.Interaction, size: app_commands.Choice[str]):
    await interaction.response.send_message(f"One {size.name.lower()} coming up ☕")


@tree.command(description="Secret message")
async def whisper(interaction: vector.Interaction, text: str):
    await interaction.response.send_message(f"🤫 {text}", ephemeral=True)  # DMs the user


@client.event
async def on_ready():
    await tree.sync()  # a no-op on Vector, kept so ported code runs
    print("ready:", client.user)


client.run(os.environ.get("VECTOR_NSEC"))
