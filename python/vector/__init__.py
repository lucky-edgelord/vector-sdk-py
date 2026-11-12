"""vector: a discord.py-style library for Vector messenger bots, powered by the Rust ``vector_sdk``.

    import vector
    from vector.ext import commands

    bot = commands.Bot(command_prefix="!")

    @bot.event
    async def on_ready():
        print(f"Logged in as {bot.user} ({bot.npub})")

    @bot.command()
    async def ping(ctx):
        await ctx.send("pong")

    bot.run(os.environ["VECTOR_NSEC"])
"""

from __future__ import annotations

__title__ = "vector"
__author__ = "lucky-edgelord"
__license__ = "MIT"

try:
    from importlib.metadata import version as _v

    __version__ = _v("vector-sdk-py")
except Exception:  # pragma: no cover
    __version__ = "0.1.0"

from . import abc, app_commands, ui, utils
from .abc import Messageable
from .asset import Asset
from .channel import (
    CategoryChannel, ChannelType, DMChannel, ForumChannel, PartialMessageable, TextChannel, VoiceChannel,
)
from .client import AutoShardedClient, Client, setup_logging
from .colour import Color, Colour
from .community import (
    AuditLogAction, AuditLogEntry, BanEntry, Community, CommunityPreview, Guild, Invite, PendingInvite,
    RaidContainment, RelayCheck, RelayMove,
)
from .embeds import Embed
from .errors import *  # noqa: F401,F403
from .file import File
from .flags import (
    Activity, ActivityType, AllowedMentions, CustomActivity, Game, Intents, MemberCacheFlags, Object, Status, Streaming,
)
from .message import (
    Attachment, EditEntry, LinkPreview, Message, MessageReference, PartialMessage, RawMemberRemoveEvent,
    RawMessageDeletePayload, RawMessageUpdateEvent, RawReactionActionEvent, RawTypingEvent, Reaction,
)
from .permissions import PermissionOverwrite, Permissions
from .role import Role
from .state import CommunityChange, XdcPresence
from .message import Emoji, PartialEmoji
from .ui import ButtonStyle, Interaction, InteractionResponse, InteractionType, SelectOption, TextStyle
from .user import BaseUser, ClientUser, Member, Profile, User
from .voice import (
    AudioSource, FFmpegOpusAudio, FFmpegPCMAudio, PCMAudio, PCMVolumeTransformer, Speech, Transcriber, Utterances,
    VoiceClient, VoiceProtocol, VoiceState,
)
from .xdc import XdcApp, XdcEvent, XdcManifest, XdcPeer, XdcSession

#: The Rust SDK version this build wraps.
try:
    from ._native import __sdk_version__ as sdk_version
except ImportError:  # pragma: no cover
    sdk_version = None


def generate_nsec() -> str:
    """Mint a fresh bot secret key (``nsec1…``)."""
    return Client.generate_nsec()
