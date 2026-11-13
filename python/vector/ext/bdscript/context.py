"""Execution state for one run of a BDScript command."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ButtonSpec:
    custom_id: str
    label: str
    style: str = "secondary"
    disabled: bool = False
    emoji: Optional[str] = None
    url: Optional[str] = None
    new_row: bool = False


@dataclass
class SelectSpec:
    custom_id: str
    placeholder: str = ""
    min_values: int = 1
    max_values: int = 1
    options: List[Dict[str, Any]] = field(default_factory=list)
    disabled: bool = False


@dataclass
class ModalSpec:
    custom_id: str
    title: str
    inputs: List[Dict[str, Any]] = field(default_factory=list)


class Response:
    """Everything the script asked to send (built up by functions, sent at the end)."""

    def __init__(self) -> None:
        self.embeds: Dict[int, Any] = {}           # BDFD embed index (1-based) -> vector.Embed
        self.rows: List[List[Any]] = [[]]          # ButtonSpec / SelectSpec rows
        self.modal: Optional[ModalSpec] = None
        self.reactions: List[str] = []             # $addReactions: on the response
        self.cmd_reactions: List[str] = []         # $addCmdReactions: on the triggering message
        self.files: List[Any] = []
        self.mention_author = True                 # BDFD mentions the author unless $nomention
        self.reply_to: Optional[str] = None
        self.reply_mention = False
        self.ephemeral = False
        self.tts = False
        self.delete_after: Optional[float] = None
        self.expires_in: Optional[float] = None
        self.delete_command_after: Optional[float] = None
        self.channel_id: Optional[str] = None      # $useChannel
        self.allowed_users: Optional[List[str]] = None
        self.allowed_roles: Optional[List[str]] = None
        self.remove_links = False
        self.remove_components = False             # $removeButtons/$removeAllComponents on the interaction msg
        self.edit_target: Optional[str] = None     # fork $reply/interactions: edit instead of send
        self.defer = False
        self.suppress = False                      # nothing auto-sent (e.g. $sendMessage already sent)

    def embed(self, index: Any = None) -> Any:
        from ...embeds import Embed

        try:
            i = int(index) if index not in (None, "") else 1
        except ValueError:
            i = 1
        if i not in self.embeds:
            self.embeds[i] = Embed()
        return self.embeds[i]

    def has_components(self) -> bool:
        return any(self.rows)


class Context:
    def __init__(self, bot: Any, *, message: Any = None, channel: Any = None, author: Any = None, guild: Any = None,
                 args: Optional[List[str]] = None, command: Any = None, interaction: Any = None,
                 extras: Optional[Dict[str, Any]] = None, mention_default: bool = True) -> None:
        self.bot = bot                     # BDBot
        self.client = getattr(bot, "client", bot)
        self.message = message
        self.channel = channel or getattr(message, "channel", None)
        self.author = author or getattr(message, "author", None)
        self.guild = guild if guild is not None else getattr(self.channel, "guild", None)
        self.args: List[str] = list(args or [])
        self.command = command
        self.interaction = interaction
        self.extras: Dict[str, Any] = dict(extras or {})
        self.response = Response()
        self.response.mention_author = mention_default
        self.vars: Dict[str, str] = {}               # $var
        self.keywords: Dict[str, str] = {}           # fork $let/$get
        self.split: List[str] = []                   # $textSplit
        self.json: Any = None                        # $jsonParse
        self.http: Dict[str, Any] = {"headers": {}, "result": "", "status": 0}
        self.error: Dict[str, str] = {}              # $error[] inside $catch
        self.suppress_errors: Optional[str] = None   # $suppressErrors message ("" = silent)
        self.embed_suppress_errors: Optional[Dict[str, Any]] = None
        self.inner_space_removal = True
        self.special_escaping = True
        self.started = time.perf_counter()
        self.async_tasks: Dict[str, Any] = {}
        self.random_cache: Dict[str, str] = {}
        self.sent_ids: List[str] = []
        self.depth = 0
        self.awaited: Optional[Dict[str, Any]] = None
        self.loop: Dict[str, Any] = {}

    # -- convenience --------------------------------------------------------------------------------------
    @property
    def author_id(self) -> str:
        return str(getattr(self.author, "id", "") or "")

    @property
    def channel_id(self) -> str:
        return str(getattr(self.channel, "id", "") or "")

    @property
    def guild_id(self) -> str:
        return str(getattr(self.guild, "id", "") or "")

    def member(self, user_id: Optional[str] = None) -> Any:
        if self.guild is None:
            return None
        uid = user_id or self.author_id
        return self.guild.get_member(uid)

    def child(self) -> "Context":
        """A context for ``$eval``/async scopes sharing this one's state."""
        return self
