"""``Intents``, ``AllowedMentions`` and other discord.py flag types.

Vector delivers every event to every bot, so intents change nothing. They are accepted so that
ported code like ``vector.Client(intents=vector.Intents.default())`` runs unchanged.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Union

__all__ = ("Intents", "AllowedMentions", "MemberCacheFlags", "Status", "Game", "Activity", "CustomActivity",
           "Streaming", "ActivityType", "Object")


class Intents:
    _FLAGS = (
        "guilds", "members", "moderation", "bans", "emojis", "emojis_and_stickers", "expressions", "integrations",
        "webhooks", "invites", "voice_states", "presences", "messages", "guild_messages", "dm_messages",
        "reactions", "guild_reactions", "dm_reactions", "typing", "guild_typing", "dm_typing", "message_content",
        "guild_scheduled_events", "auto_moderation", "polls",
    )

    def __init__(self, value: int = 0, **kwargs: bool):
        self.value = value
        self._on = {name: True for name in self._FLAGS}
        self._on.update(kwargs)

    def __getattr__(self, name: str) -> bool:
        if name.startswith("_"):
            raise AttributeError(name)
        return self.__dict__.get("_on", {}).get(name, True)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("value", "_on"):
            object.__setattr__(self, name, value)
        else:
            self._on[name] = bool(value)

    @classmethod
    def default(cls) -> "Intents":
        return cls()

    @classmethod
    def all(cls) -> "Intents":
        return cls()

    @classmethod
    def none(cls) -> "Intents":
        return cls()

    def __repr__(self) -> str:
        return "<Intents (Vector delivers all events)>"


class MemberCacheFlags:
    def __init__(self, **kwargs: bool):
        pass

    @classmethod
    def all(cls) -> "MemberCacheFlags":
        return cls()

    @classmethod
    def none(cls) -> "MemberCacheFlags":
        return cls()


class AllowedMentions:
    """Accepted for compatibility. Vector clients decide how mentions notify."""

    def __init__(self, *, everyone: bool = True, users: Union[bool, Iterable[Any]] = True,
                 roles: Union[bool, Iterable[Any]] = True, replied_user: bool = True):
        self.everyone, self.users, self.roles, self.replied_user = everyone, users, roles, replied_user

    @classmethod
    def all(cls) -> "AllowedMentions":
        return cls()

    @classmethod
    def none(cls) -> "AllowedMentions":
        return cls(everyone=False, users=False, roles=False, replied_user=False)


class Status:
    online = "online"
    offline = "offline"
    idle = "idle"
    dnd = "dnd"
    do_not_disturb = "dnd"
    invisible = "invisible"


class ActivityType:
    unknown = -1
    playing = 0
    streaming = 1
    listening = 2
    watching = 3
    custom = 4
    competing = 5


_PREFIX = {ActivityType.playing: "Playing ", ActivityType.streaming: "Streaming ", ActivityType.listening: "Listening to ",
           ActivityType.watching: "Watching ", ActivityType.competing: "Competing in ", ActivityType.custom: ""}


class Activity:
    """Becomes the bot's Vector status text (``Playing chess``, ``Watching the logs``…)."""

    def __init__(self, *, name: Optional[str] = None, type: int = ActivityType.playing, url: Optional[str] = None,
                 state: Optional[str] = None, **kwargs: Any):
        self.name = name
        self.type = type
        self.url = url
        self.state = state

    def to_status(self) -> str:
        text = self.state if self.type == ActivityType.custom and self.state else (self.name or "")
        return _PREFIX.get(self.type, "") + text

    def __str__(self) -> str:
        return self.name or ""


class Game(Activity):
    def __init__(self, name: str, **kwargs: Any):
        super().__init__(name=name, type=ActivityType.playing)


class Streaming(Activity):
    def __init__(self, *, name: str, url: str, **kwargs: Any):
        super().__init__(name=name, type=ActivityType.streaming, url=url)


class CustomActivity(Activity):
    def __init__(self, name: Optional[str], *, emoji: Optional[str] = None, **kwargs: Any):
        super().__init__(name=name, type=ActivityType.custom, state=name)
        self.emoji = emoji

    def to_status(self) -> str:
        return f"{self.emoji} {self.name}" if self.emoji else (self.name or "")


class Object:
    """A bare id, for APIs that only need one: ``vector.Object(id=npub)``."""

    def __init__(self, id: Any, *, type: Any = None):
        self.id = str(id)
        self.type = type

    def __eq__(self, other: Any) -> bool:
        return getattr(other, "id", None) == self.id

    def __hash__(self) -> int:
        return hash(self.id)

    def __repr__(self) -> str:
        return f"<Object id={self.id!r}>"
