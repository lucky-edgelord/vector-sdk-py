"""Voice: play audio into a voice Channel, and listen + transcribe what people say.

Needs ``ffmpeg`` on PATH. Transcription needs a build with the ``whisper`` feature and a
ggml model file (see the README).
"""

import os
from typing import Optional

import vector
from vector.ext import commands

bot = commands.Bot(command_prefix="!")


@bot.command()
async def join(ctx, *, channel: Optional[vector.VoiceChannel] = None):
    """Join a voice channel."""
    channel = channel or next(iter(ctx.guild.voice_channels), None)
    if channel is None:
        return await ctx.reply("No voice channel here")
    await channel.connect()
    await ctx.react("🔊")


@bot.command()
async def play(ctx, *, path: str):
    """Play an audio file (anything ffmpeg can read)."""
    vc: vector.VoiceClient = ctx.voice_client
    if vc is None:
        return await ctx.reply("Use !join first")
    if vc.is_playing():
        vc.stop()
    vc.play(vector.PCMVolumeTransformer(vector.FFmpegPCMAudio(path), volume=0.8),
            after=lambda e: print("finished", e or ""))
    await ctx.send(f"▶️ Playing `{os.path.basename(path)}`")


@bot.command()
async def stop(ctx):
    if ctx.voice_client:
        ctx.voice_client.stop()


@bot.command()
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()


@bot.command()
async def beep(ctx):
    """Play a test tone."""
    if ctx.voice_client:
        await ctx.voice_client.say_and_wait(vector.voice.tone(440, 500))


@bot.command()
async def transcribe(ctx, model: str = "ggml-base.en.bin"):
    """Write down what people say in the call (needs the whisper build)."""
    vc = ctx.voice_client
    stt = vector.Transcriber(model)
    await ctx.send("📝 Listening…")
    async for member, pcm in vc.utterances(pause=0.8):
        text = (await stt.transcribe(pcm)).strip()
        if text:
            await ctx.send(f"**{member.display_name if member else '?'}:** {text}")


@bot.event
async def on_voice_state_update(member, before: vector.VoiceState, after: vector.VoiceState):
    if after.self_video and not before.self_video:
        print(f"{member.display_name} turned their camera on in {after.channel}")
    if before.channel is None and after.channel is not None:
        print(f"{member.display_name} joined {after.channel}")


bot.run(os.environ.get("VECTOR_NSEC"))
