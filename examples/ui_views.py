"""Buttons, selects, modals and pagination, rebuilt from reactions.

Each button/option is a reaction under the message; reacting "clicks" it (removing your
reaction clicks it again). Callbacks receive a ``vector.Interaction`` like discord.py's.
"""

import os

import vector
from vector import ui
from vector.ext import commands

bot = commands.Bot(command_prefix="!")


class Confirm(ui.View):
    def __init__(self, author: vector.User):
        super().__init__(timeout=60)
        self.author = author
        self.value = None

    async def interaction_check(self, interaction: vector.Interaction) -> bool:
        return interaction.user == self.author  # only the person who asked can answer

    @ui.button(label="Confirm", emoji="✅", style=ui.ButtonStyle.success)
    async def confirm(self, interaction: vector.Interaction, button: ui.Button):
        self.value = True
        await interaction.response.send_message("Confirmed ✅")
        self.stop()

    @ui.button(label="Cancel", emoji="❌", style=ui.ButtonStyle.danger)
    async def cancel(self, interaction: vector.Interaction, button: ui.Button):
        self.value = False
        await interaction.response.send_message("Cancelled", ephemeral=True)  # ephemeral → sent as a DM
        self.stop()

    async def on_timeout(self):
        if self.message:
            await self.message.reply("⏰ Timed out")


class Feedback(ui.Modal, title="Feedback"):
    name = ui.TextInput(label="Your name", max_length=50)
    rating = ui.TextInput(label="Rating 1-5", max_length=1)
    comments = ui.TextInput(label="Anything else?", style=ui.TextStyle.paragraph, required=False)

    async def on_submit(self, interaction: vector.Interaction):
        await interaction.response.send_message(f"Thanks {self.name.value}! You rated us {self.rating.value}/5.")


class FeedbackButton(ui.View):
    @ui.button(label="Leave feedback", emoji="📝")
    async def open(self, interaction: vector.Interaction, button: ui.Button):
        await interaction.response.send_modal(Feedback())  # asked as a short chat conversation


class RolePicker(ui.View):
    @ui.select(placeholder="Pick your team", options=[
        ui.SelectOption(label="Red team", value="red", emoji="🔴"),
        ui.SelectOption(label="Blue team", value="blue", emoji="🔵"),
        ui.SelectOption(label="Green team", value="green", emoji="🟢"),
    ])
    async def pick(self, interaction: vector.Interaction, select: ui.Select):
        role = vector.utils.get(interaction.guild.roles, name=f"{select.values[0].title()} team")
        if role:
            await interaction.user.add_roles(role)
        await interaction.response.send_message(f"{interaction.user.display_name} joined {select.values[0]}!")


@bot.command()
async def delete_everything(ctx):
    view = Confirm(ctx.author)
    await ctx.send("Are you sure?", view=view)
    await view.wait()
    print("answer:", view.value)


@bot.command()
async def feedback(ctx):
    await ctx.send("We'd love your thoughts:", view=FeedbackButton())


@bot.command()
@commands.guild_only()
async def teams(ctx):
    await ctx.send("Choose a team:", view=RolePicker(timeout=None))


@bot.command()
async def pages(ctx):
    embeds = [vector.Embed(title=f"Chapter {i}", description="Lorem ipsum " * i, colour=vector.Colour.random())
              for i in range(1, 6)]
    await ui.Paginator(embeds, author=ctx.author).start(ctx)


bot.run(os.environ.get("VECTOR_NSEC"))
