"""``Permissions`` and ``PermissionOverwrite``, shaped like discord.py's.

Vector's Community permissions are a 64-bit field like Discord's. Every bit Vector defines is
available under its Discord name (``kick_members``, ``ban_members``…) and, where it differs,
its Vector name too (``kick``, ``ban``, ``manage_metadata``…).

Discord permissions Vector has no equivalent for (``embed_links``, ``use_application_commands``,
``manage_webhooks``…) are accepted everywhere and always read as granted, so checks such as
``@commands.has_permissions(embed_links=True)`` keep working after a port.
"""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Iterator, Optional, Set, Tuple

__all__ = ("Permissions", "PermissionOverwrite", "VALID_FLAGS")

#: Vector's bits, by every name they go by.
VALID_FLAGS: Dict[str, int] = {
    "manage_roles": 1 << 0,
    "manage_permissions": 1 << 0,
    "manage_channels": 1 << 1,
    "manage_guild": 1 << 2,
    "manage_community": 1 << 2,
    "manage_metadata": 1 << 2,
    "kick_members": 1 << 3,
    "kick": 1 << 3,
    "ban_members": 1 << 4,
    "ban": 1 << 4,
    "manage_messages": 1 << 5,
    "create_instant_invite": 1 << 6,
    "create_invite": 1 << 6,
    "view_audit_log": 1 << 8,
    "mention_everyone": 1 << 9,
    "pin_messages": 1 << 11,
    "view_channel": 1 << 13,
    "read_messages": 1 << 13,
    "send_messages": 1 << 14,
    "send_messages_in_threads": 1 << 15,
    "send_in_threads": 1 << 15,
    "attach_files": 1 << 16,
    "add_reactions": 1 << 17,
    "read_message_history": 1 << 18,
    "connect": 1 << 19,
    "speak": 1 << 20,
    "stream": 1 << 21,
    "video": 1 << 21,
    "priority_speaker": 1 << 22,
    "mute_members": 1 << 23,
    "deafen_members": 1 << 24,
    "move_members": 1 << 25,
    "moderate_members": 1 << 26,
    "manage_nicknames": 1 << 28,
    "change_nickname": 1 << 29,
}

#: Discord-only permissions: accepted, ignored, and always read as granted.
DISCORD_ONLY: Set[str] = {
    "administrator", "embed_links", "use_external_emojis", "external_emojis", "use_external_stickers",
    "external_stickers", "manage_emojis", "manage_emojis_and_stickers", "manage_expressions",
    "create_expressions", "manage_webhooks", "manage_events", "create_events", "manage_threads",
    "create_public_threads", "create_private_threads", "use_application_commands", "use_slash_commands",
    "request_to_speak", "use_voice_activation", "use_embedded_activities", "view_guild_insights",
    "send_tts_messages", "use_soundboard", "use_external_sounds", "send_voice_messages",
    "send_polls", "create_polls", "use_external_apps", "view_creator_monetization_analytics",
}

MANAGEMENT_MASK = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5) | (1 << 6) | (1 << 8) | (1 << 11)
ADMIN_ALL = MANAGEMENT_MASK | (1 << 9)
ALL_BITS = 0
for _bit in set(VALID_FLAGS.values()):
    ALL_BITS |= _bit


def _canonical_names() -> Dict[int, str]:
    seen: Dict[int, str] = {}
    for name, bit in VALID_FLAGS.items():
        seen.setdefault(bit, name)
    return seen


_CANONICAL = _canonical_names()


class Permissions:
    """A set of Community permissions. Behaves like ``discord.Permissions``."""

    __slots__ = ("value",)
    VALID_FLAGS: ClassVar[Dict[str, int]] = VALID_FLAGS

    def __init__(self, permissions: int = 0, **kwargs: bool):
        if not isinstance(permissions, int):
            raise TypeError(f"Expected int parameter, received {permissions.__class__.__name__} instead.")
        self.value = permissions
        for key, value in kwargs.items():
            if key in DISCORD_ONLY:
                continue
            if key not in VALID_FLAGS:
                raise TypeError(f"{key!r} is not a valid permission name.")
            setattr(self, key, value)

    # -- flag access ----------------------------------------------------------------------

    def __getattr__(self, name: str) -> bool:
        if name in VALID_FLAGS:
            bit = VALID_FLAGS[name]
            return (self.value & bit) == bit
        if name in DISCORD_ONLY:
            return True
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "value":
            object.__setattr__(self, name, value)
        elif name in VALID_FLAGS:
            bit = VALID_FLAGS[name]
            object.__setattr__(self, "value", (self.value | bit) if value else (self.value & ~bit))
        elif name in DISCORD_ONLY:
            pass
        else:
            raise AttributeError(name)

    def __iter__(self) -> Iterator[Tuple[str, bool]]:
        for bit, name in _CANONICAL.items():
            yield name, (self.value & bit) == bit

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Permissions) and self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)

    def __int__(self) -> int:
        return self.value

    def __repr__(self) -> str:
        return f"<Permissions value={self.value}>"

    def __or__(self, other: "Permissions") -> "Permissions":
        return Permissions(self.value | int(other))

    def __and__(self, other: "Permissions") -> "Permissions":
        return Permissions(self.value & int(other))

    def __xor__(self, other: "Permissions") -> "Permissions":
        return Permissions(self.value ^ int(other))

    def __invert__(self) -> "Permissions":
        return Permissions(~self.value & ALL_BITS)

    def __le__(self, other: "Permissions") -> bool:
        return (self.value & int(other)) == self.value

    def __ge__(self, other: "Permissions") -> bool:
        return (self.value | int(other)) == self.value

    def __lt__(self, other: "Permissions") -> bool:
        return self <= other and self != other

    def __gt__(self, other: "Permissions") -> bool:
        return self >= other and self != other

    is_subset = __le__
    is_superset = __ge__
    is_strict_subset = __lt__
    is_strict_superset = __gt__

    def update(self, **kwargs: bool) -> None:
        for key, value in kwargs.items():
            if key in VALID_FLAGS or key in DISCORD_ONLY:
                setattr(self, key, value)

    def handle_overwrite(self, allow: int, deny: int) -> None:
        self.value = (self.value & ~deny) | allow

    @property
    def administrator(self) -> bool:  # type: ignore[override]
        """True when every management bit is held (Vector has no single admin bit)."""
        return (self.value & MANAGEMENT_MASK) == MANAGEMENT_MASK

    # -- presets --------------------------------------------------------------------------

    @classmethod
    def none(cls) -> "Permissions":
        return cls(0)

    @classmethod
    def all(cls) -> "Permissions":
        return cls(ALL_BITS)

    @classmethod
    def all_channel(cls) -> "Permissions":
        return cls(sum({VALID_FLAGS[n] for n in (
            "view_channel", "send_messages", "send_messages_in_threads", "attach_files", "add_reactions",
            "read_message_history", "connect", "speak", "stream", "priority_speaker", "mute_members",
            "deafen_members", "move_members", "manage_messages", "manage_channels", "manage_roles",
            "create_instant_invite")}))

    @classmethod
    def general(cls) -> "Permissions":
        return cls(sum({VALID_FLAGS[n] for n in (
            "view_channel", "manage_channels", "manage_roles", "view_audit_log", "manage_guild")}))

    @classmethod
    def membership(cls) -> "Permissions":
        return cls(sum({VALID_FLAGS[n] for n in (
            "create_instant_invite", "change_nickname", "manage_nicknames", "kick_members", "ban_members",
            "moderate_members")}))

    @classmethod
    def text(cls) -> "Permissions":
        return cls(sum({VALID_FLAGS[n] for n in (
            "send_messages", "send_messages_in_threads", "manage_messages", "attach_files",
            "read_message_history", "mention_everyone", "add_reactions", "pin_messages")}))

    @classmethod
    def voice(cls) -> "Permissions":
        return cls(sum({VALID_FLAGS[n] for n in (
            "connect", "speak", "stream", "mute_members", "deafen_members", "move_members", "priority_speaker")}))

    @classmethod
    def stage(cls) -> "Permissions":
        return cls(0)

    @classmethod
    def advanced(cls) -> "Permissions":
        return cls(ADMIN_ALL)

    @classmethod
    def elevated(cls) -> "Permissions":
        return cls(MANAGEMENT_MASK | VALID_FLAGS["moderate_members"])

    @classmethod
    def admin(cls) -> "Permissions":
        """Everything a Vector "Admin" role holds."""
        return cls(ADMIN_ALL)


class PermissionOverwrite:
    """Per-channel allow/deny for one target. Unset (``None``) means "inherit"."""

    __slots__ = ("_values",)

    def __init__(self, **kwargs: Optional[bool]):
        self._values: Dict[str, Optional[bool]] = {}
        for key, value in kwargs.items():
            if key in DISCORD_ONLY:
                continue
            if key not in VALID_FLAGS:
                raise ValueError(f"no permission called {key!r}")
            self._values[_CANONICAL[VALID_FLAGS[key]]] = value

    def __getattr__(self, name: str) -> Optional[bool]:
        if name in VALID_FLAGS:
            return self._values.get(_CANONICAL[VALID_FLAGS[name]])
        if name in DISCORD_ONLY:
            return None
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_values":
            object.__setattr__(self, name, value)
        elif name in VALID_FLAGS:
            self._values[_CANONICAL[VALID_FLAGS[name]]] = value
        elif name in DISCORD_ONLY:
            pass
        else:
            raise AttributeError(name)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, PermissionOverwrite) and self.pair() == other.pair()

    def __iter__(self) -> Iterator[Tuple[str, Optional[bool]]]:
        for name in _CANONICAL.values():
            yield name, self._values.get(name)

    def __repr__(self) -> str:
        allow, deny = self.pair()
        return f"<PermissionOverwrite allow={allow.value} deny={deny.value}>"

    def pair(self) -> Tuple[Permissions, Permissions]:
        allow = deny = 0
        for name, value in self._values.items():
            if value is True:
                allow |= VALID_FLAGS[name]
            elif value is False:
                deny |= VALID_FLAGS[name]
        return Permissions(allow), Permissions(deny)

    @classmethod
    def from_pair(cls, allow: Permissions | int, deny: Permissions | int) -> "PermissionOverwrite":
        ret = cls()
        a, d = int(allow), int(deny)
        for bit, name in _CANONICAL.items():
            if a & bit:
                ret._values[name] = True
            elif d & bit:
                ret._values[name] = False
        return ret

    def is_empty(self) -> bool:
        return all(v is None for v in self._values.values())

    def update(self, **kwargs: Optional[bool]) -> None:
        for key, value in kwargs.items():
            if key in VALID_FLAGS:
                setattr(self, key, value)
