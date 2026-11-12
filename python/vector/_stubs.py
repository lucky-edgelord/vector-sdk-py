"""Placeholders for discord.py names that have no Vector equivalent.

A ported bot often does ``from discord import Thread, Webhook, MessageType`` just for type hints, or only touches
these in code paths Vector never reaches. Importing, subclassing and ``isinstance`` checks all work; *using* a stub
(instantiating it, calling it, reading an enum member that doesn't exist on Vector) raises
:class:`NotSupportedOnVector`, a clear error instead of an ``ImportError`` at startup.

Every stub has ``__vector_stub__ = True`` so code can tell.
"""

from __future__ import annotations

import enum
import re
import sys
import time
from typing import Any, Dict, Iterable

from .errors import VectorException


class NotSupportedOnVector(VectorException, NotImplementedError):
    """Raised when a discord.py feature that Vector doesn't have is used."""


def _unsupported(name: str) -> NotSupportedOnVector:
    return NotSupportedOnVector(f"{name} is a discord.py feature that Vector doesn't have")


class _StubBase:
    __vector_stub__ = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise _unsupported(type(self).__name__)


class _StubEnumMeta(type):
    """Enum look-alike: any member name resolves (so ``MessageType.default`` is a valid expression), and comparing
    members is by identity, so branches on them simply never match."""

    def __getattr__(cls, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        member = cls.__new__(cls)
        member.name, member.value = name, name
        type.__setattr__(cls, name, member)
        return member

    def __iter__(cls):
        return iter(())

    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        if args:
            return getattr(cls, str(args[0]))
        raise _unsupported(cls.__name__)


class _StubEnum(metaclass=_StubEnumMeta):
    __vector_stub__ = True
    name: str = ""
    value: Any = None

    def __repr__(self) -> str:
        return f"<{type(self).__name__}.{self.name}>"


class _StubFlags:
    """Flags look-alike: constructible, every flag reads as ``False``."""

    __vector_stub__ = True

    def __init__(self, value: int = 0, **kwargs: Any) -> None:
        self.value = value

    def __getattr__(self, name: str) -> bool:
        if name.startswith("__"):
            raise AttributeError(name)
        return False

    def __int__(self) -> int:
        return self.value

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, _StubFlags) and other.value == self.value

    def __hash__(self) -> int:
        return hash(self.value)

    def __iter__(self):
        return iter(())


def _cls(name: str, base: type, doc: str = "") -> type:
    return type(name, (base,), {"__doc__": doc or f"discord.py's ``{name}``; not available on Vector."})


_ENUMS = """AppCommandOptionType AppCommandPermissionType AppCommandType AppInstallationType AuditLogActionCategory
AutoModRuleActionType AutoModRuleEventType AutoModRuleTriggerType CollectibleType ComponentType ContentFilter
DefaultAvatar EntitlementOwnerType EntitlementType EntityType EventStatus ExpireBehavior ExpireBehaviour
ForumLayoutType ForumOrderType InteractionResponseType InviteTarget InviteType Locale MFALevel MediaItemLoadingState
MessageReferenceType MessageType NSFWLevel NameplatePalette NotificationLevel OnboardingMode OnboardingPromptType
PollLayoutType PrivacyLevel ReactionType SKUType SelectDefaultValueType SeparatorSpacing SpeakingState
StatusDisplayType StickerFormatType StickerType SubscriptionStatus TeamMembershipState TeamMemberRole
VerificationLevel VideoQualityMode VoiceChannelEffectAnimationType WebhookType""".split()

_FLAGS = """ApplicationFlags AttachmentFlags AutoModPresets ChannelFlags EmbedFlags InviteFlags MemberFlags MessageFlags
PublicUserFlags RoleFlags SKUFlags SystemChannelFlags UserFlags""".split()

_EXCEPTIONS = """DiscordServerError GatewayNotFound InteractionResponded MissingApplicationID RateLimited
FFmpegProcessError""".split()

_CLASSES = """ActionRow AppCommandContext AppInfo AppInstallParams AuditLogChanges AuditLogDiff AutoModAction
AutoModRule AutoModRuleAction AutoModTrigger BaseActivity BaseSoundboardSound BotIntegration Button CallMessage
CheckboxComponent CheckboxGroupComponent CheckboxGroupOption ClientStatus Collectible Component Container
DeletedReferencedMessage Entitlement FFmpegAudio FileComponent FileUploadComponent ForumTag GroupChannel
GuildPreview GuildProductPurchase GuildSticker Integration IntegrationAccount IntegrationApplication
IntegrationTypeConfig InteractionCallbackActivityInstance InteractionCallbackResponse InteractionMessage
LabelComponent MediaGalleryComponent MediaGalleryItem MessageApplication MessageInteraction
MessageInteractionMetadata MessageSnapshot Onboarding OnboardingPrompt OnboardingPromptOption PartialAppInfo
PartialIntegration PartialInviteChannel PartialInviteGuild PartialWebhookChannel PartialWebhookGuild Poll
PollAnswer PollMedia PrimaryGuild PurchaseNotification RadioGroupComponent RadioGroupOption
RawAppCommandPermissionsUpdateEvent RawBulkMessageDeleteEvent RawIntegrationDeleteEvent RawMessageDeleteEvent
RawPollVoteActionEvent RawPresenceUpdateEvent RawReactionClearEmojiEvent RawReactionClearEvent
RawThreadDeleteEvent RawThreadMembersUpdate RawThreadUpdateEvent RoleSubscriptionInfo RoleTags SKU
ScheduledEvent SectionComponent SelectDefaultValue SelectMenu SeparatorComponent SessionStartLimits ShardInfo
SoundboardDefaultSound SoundboardSound Spotify StageChannel StageInstance StandardSticker Sticker StickerItem
StickerPack StreamIntegration Subscription SyncWebhook SyncWebhookMessage Team TeamMember Template TextDisplay
TextInput Thread ThreadMember ThumbnailComponent UnfurledMediaItem VoiceChannelEffect VoiceChannelSoundEffect
Webhook WebhookMessage WelcomeChannel WelcomeScreen Widget WidgetChannel WidgetMember""".split()

_UI_CLASSES = """ActionRow Checkbox CheckboxGroup Container DynamicItem File FileUpload Label LayoutView MediaGallery
RadioGroup Section Separator TextDisplay Thumbnail""".split()

_COMMANDS_ERRORS = {
    "BadFlagArgument": "FlagError", "BadInviteArgument": "BadArgument", "BadTimestampArgument": "BadArgument",
    "GuildStickerNotFound": "BadArgument", "MissingFlagArgument": "FlagError", "MissingRequiredFlag": "FlagError",
    "ObjectNotFound": "BadArgument", "PartialEmojiConversionFailure": "BadArgument",
    "ScheduledEventNotFound": "BadArgument", "SoundboardSoundNotFound": "BadArgument",
    "ThreadNotFound": "BadArgument", "TooManyFlags": "FlagError",
}

_COMMANDS_CONVERTERS = """EmojiConverter GameConverter GuildStickerConverter IDConverter InviteConverter
PartialEmojiConverter ScheduledEventConverter SoundboardSoundConverter StageChannelConverter
ThreadConverter""".split()


def _build_main() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for n in _ENUMS:
        out[n] = _cls(n, _StubEnum)
    for n in _FLAGS:
        out[n] = _cls(n, _StubFlags)
    for n in _EXCEPTIONS:
        out[n] = _cls(n, VectorException)
    for n in _CLASSES:
        out[n] = _cls(n, _StubBase)
    out["ExpireBehaviour"] = out["ExpireBehavior"]
    out["version_info"] = type("VersionInfo", (tuple,), {"__slots__": ()})((2, 6, 0, "final", 0))
    return out


def _build_ui() -> Dict[str, Any]:
    out = {n: _cls(n, _StubBase, f"discord.ui.{n}; Components V2 isn't available on Vector.") for n in _UI_CLASSES}

    def _deco(name: str):
        def decorator(*args: Any, **kwargs: Any):
            raise _unsupported(f"ui.{name}")
        decorator.__name__ = name
        return decorator

    for n in ("action_row", "checkbox", "container", "section", "separator", "text_display", "thumbnail", "radio",
              "file_upload", "media_gallery", "label", "file", "dynamic"):
        out.setdefault(n, _deco(n))
    return out


def _build_commands() -> Dict[str, Any]:
    from .ext.commands import converter, errors

    out: Dict[str, Any] = {}
    for n, base in _COMMANDS_ERRORS.items():
        out[n] = _cls(n, getattr(errors, base))
    for n in _COMMANDS_CONVERTERS:
        def convert(self, ctx, argument, _n=n):
            raise _unsupported(_n)
        out[n] = type(n, (converter.Converter,), {"convert": convert, "__vector_stub__": True})

    class Flag:
        __vector_stub__ = True

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise _unsupported("commands.Flag")

    class FlagConverter:
        """``--flag value`` style arguments aren't supported yet."""

        __vector_stub__ = True

        def __init_subclass__(cls, **kwargs: Any) -> None:
            super().__init_subclass__()

        @classmethod
        async def convert(cls, ctx, argument):
            raise _unsupported("commands.FlagConverter")

    def flag(*args: Any, **kwargs: Any):
        return None  # lets class bodies that declare flags still load

    out.update(Flag=Flag, FlagConverter=FlagConverter, flag=flag, Timestamp=_cls("Timestamp", _StubBase))
    return out


def _build_utils() -> Dict[str, Any]:
    import datetime
    import functools
    import logging
    import warnings

    EPOCH = 1420070400000

    def time_snowflake(dt: datetime.datetime, /, *, high: bool = False) -> int:
        return (int(dt.timestamp() * 1000 - EPOCH) << 22) + (2 ** 22 - 1 if high else 0)

    def parse_time(timestamp: Any):
        return datetime.datetime.fromisoformat(timestamp) if timestamp else None

    def compute_timedelta(dt: datetime.datetime) -> float:
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return max((dt - datetime.datetime.now(datetime.timezone.utc)).total_seconds(), 0)

    def copy_doc(original):
        def decorator(overridden):
            overridden.__doc__ = original.__doc__
            return overridden
        return decorator

    def deprecated(instead: Any = None):
        def actual(func):
            @functools.wraps(func)
            def decorated(*args, **kwargs):
                warnings.warn(f"{func.__name__} is deprecated" + (f", use {instead}" if instead else ""),
                              DeprecationWarning, stacklevel=2)
                return func(*args, **kwargs)
            return decorated
        return actual

    class classproperty:
        def __init__(self, fget):
            self.fget = fget

        def __get__(self, obj, owner):
            return self.fget(owner)

    def setup_logging(*, handler=None, formatter=None, level=None, root: bool = True) -> None:
        logging.basicConfig(level=level or logging.INFO)

    def is_docker() -> bool:
        import os
        return os.path.exists("/.dockerenv")

    return dict(DISCORD_EPOCH=EPOCH, time_snowflake=time_snowflake, parse_time=parse_time,
                compute_timedelta=compute_timedelta, copy_doc=copy_doc, deprecated=deprecated,
                classproperty=classproperty, setup_logging=setup_logging, is_docker=is_docker,
                cached_property=functools.cached_property)


def _build_tasks() -> Dict[str, Any]:
    class ExponentialBackoff:
        def __init__(self, base: int = 1, *, integral: bool = False) -> None:
            self._base, self._integral = base, integral
            self._exp, self._last = 0, 0.0

        def delay(self) -> float:
            import random
            now = time.monotonic()
            if now - self._last > 2 ** (self._exp + 1) * self._base + 1:
                self._exp = 0
            self._last = now
            high = (2 ** (self._exp + 1)) * self._base
            self._exp = min(self._exp + 1, 10)
            d = random.uniform(0, high)
            return float(int(d)) if self._integral else d

    return dict(ExponentialBackoff=ExponentialBackoff)


_BUILDERS = {"main": _build_main, "ui": _build_ui, "commands": _build_commands, "utils": _build_utils,
             "tasks": _build_tasks}


def fill(namespace: Dict[str, Any], which: str) -> None:
    """Add every stub for ``which`` that ``namespace`` doesn't already define."""
    for name, value in _BUILDERS[which]().items():
        namespace.setdefault(name, value)
        if which == "main" and name in ("__version__",):
            namespace[name] = value if name not in namespace else namespace[name]
