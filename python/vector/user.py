"""Users (anyone, identified by npub), the bot's own account, and Community members."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from .abc import Messageable
from .asset import Asset
from .permissions import Permissions
from .utils import MISSING, _shorten, from_ms, utcnow

if TYPE_CHECKING:
    from .channel import DMChannel, TextChannel
    from .community import Community
    from .role import Role
    from .state import ConnectionState

__all__ = ("BaseUser", "User", "ClientUser", "Member", "Profile")


class Profile:
    """A Vector profile (Nostr kind 0 plus Vector extras). Every field may be empty."""

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        data = data or {}
        self.raw = data
        self.name: str = data.get("name") or ""
        self.display_name: str = data.get("display_name") or ""
        self.nickname: str = data.get("nickname") or ""
        self.avatar_url: str = data.get("avatar") or ""
        self.banner_url: str = data.get("banner") or ""
        self.about: str = data.get("about") or ""
        self.website: str = data.get("website") or ""
        self.nip05: str = data.get("nip05") or ""
        self.lud16: str = data.get("lud16") or ""
        self.bot: bool = bool(data.get("bot"))
        self.blocked: bool = bool(data.get("is_blocked"))
        status = data.get("status") or {}
        self.status: str = status.get("title") or ""
        self.status_url: str = status.get("url") or ""
        self.last_updated = from_ms((data.get("last_updated") or 0) * 1000) if data.get("last_updated") else None
        self.avatar_cached: str = data.get("avatar_cached") or ""
        self.banner_cached: str = data.get("banner_cached") or ""

    def __repr__(self) -> str:
        return f"<Profile name={self.name!r} display_name={self.display_name!r}>"


class BaseUser:
    __slots__ = ("_state", "npub", "_profile")

    def __init__(self, state: "ConnectionState", npub: str, profile: Optional[Profile] = None):
        self._state = state
        self.npub = npub
        self._profile = profile or Profile()

    # -- identity -------------------------------------------------------------------------

    @property
    def id(self) -> str:
        """The user's npub (Vector's equivalent of a user id)."""
        return self.npub

    @property
    def name(self) -> str:
        return self._profile.name or self._profile.display_name or _shorten(self.npub)

    username = name

    @property
    def global_name(self) -> Optional[str]:
        return self._profile.display_name or None

    @property
    def display_name(self) -> str:
        return self._profile.nickname or self._profile.display_name or self.name

    @property
    def discriminator(self) -> str:
        return "0"

    @property
    def mention(self) -> str:
        """A NIP-27 mention Vector renders as the user's name."""
        return f"nostr:{self.npub}"

    @property
    def avatar(self) -> Optional[Asset]:
        p = self._profile
        return Asset(p.avatar_url, cached_path=p.avatar_cached) if p.avatar_url else None

    @property
    def display_avatar(self) -> Optional[Asset]:
        return self.avatar

    @property
    def banner(self) -> Optional[Asset]:
        p = self._profile
        return Asset(p.banner_url, cached_path=p.banner_cached) if p.banner_url else None

    @property
    def bot(self) -> bool:
        return self._profile.bot

    @property
    def system(self) -> bool:
        return False

    @property
    def about(self) -> str:
        return self._profile.about

    bio = about

    @property
    def status_text(self) -> str:
        return self._profile.status

    @property
    def profile(self) -> Profile:
        return self._profile

    @property
    def created_at(self) -> Optional[datetime.datetime]:
        return None

    def mentioned_in(self, message: Any) -> bool:
        return self.npub in (message.content or "")

    def _update_profile(self, profile: Optional[Profile]) -> None:
        if profile is not None:
            self._profile = profile

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} npub={self.npub!r} name={self.name!r}>"

    def __eq__(self, other: Any) -> bool:
        return getattr(other, "npub", None) == self.npub

    def __hash__(self) -> int:
        return hash(self.npub)


class User(BaseUser, Messageable):
    """Anyone on Vector. Sending to a ``User`` sends a DM."""

    __slots__ = ()

    async def _get_channel_target(self):
        return self.npub, "dm"

    @property
    def dm_channel(self) -> "DMChannel":
        return self._state.dm_channel(self.npub)

    async def create_dm(self) -> "DMChannel":
        return self.dm_channel

    async def fetch(self) -> "User":
        """Refresh this user's profile from relays."""
        data = await self._state.native.fetch_profile(self.npub)
        if data:
            self._profile = Profile(data)
        return self

    async def block(self) -> None:
        await self._state.native.block(self.npub)

    async def unblock(self) -> None:
        await self._state.native.unblock(self.npub)

    @property
    def mutual_guilds(self) -> List["Community"]:
        return [c for c in self._state.communities if c._members is not None and self.npub in c._members]

    mutual_communities = mutual_guilds


class ClientUser(BaseUser):
    """The bot's own account (``client.user``)."""

    __slots__ = ()

    async def edit(
        self,
        *,
        username: Optional[str] = MISSING,
        avatar: Optional[Union[bytes, str]] = MISSING,
        banner: Optional[Union[bytes, str]] = MISSING,
        about: Optional[str] = MISSING,
        bio: Optional[str] = MISSING,
    ) -> "ClientUser":
        """Update the profile. ``avatar``/``banner`` take a URL, a file path, or raw image bytes."""
        p = self._profile

        async def image(value: Any, current: str) -> str:
            if value is MISSING:
                return current
            if value is None:
                return ""
            if isinstance(value, (bytes, bytearray)):
                import os
                import tempfile

                fd, path = tempfile.mkstemp(suffix=".png")
                with os.fdopen(fd, "wb") as f:
                    f.write(value)
                try:
                    return await self._state.native.upload_image(path)
                finally:
                    os.unlink(path)
            value = str(value)
            if value.startswith(("http://", "https://")):
                return value
            return await self._state.native.upload_image(value)

        name = p.name if username is MISSING else (username or "")
        about_text = bio if bio is not MISSING else about
        about_text = p.about if about_text is MISSING else (about_text or "")
        avatar_url = await image(avatar, p.avatar_url)
        banner_url = await image(banner, p.banner_url)
        await self._state.native.update_profile(name, avatar_url, banner_url, about_text)
        raw = dict(p.raw)
        raw.update(name=name, avatar=avatar_url, banner=banner_url, about=about_text)
        self._profile = Profile(raw)
        return self

    @property
    def bot(self) -> bool:
        return True


class Member(User):
    """A user inside a Community. Mirrors ``discord.Member``."""

    __slots__ = ("community", "_overrides", "_user")

    def __init__(self, state: "ConnectionState", community: "Community", user: BaseUser, *, overrides: Optional[Dict[str, Any]] = None):
        self._state = state
        self.npub = user.npub
        self._user = user._user if isinstance(user, Member) else user
        self.community = community
        #: Snapshot values (used for ``before`` in ``on_member_update``).
        self._overrides: Dict[str, Any] = overrides or {}

    @property
    def _profile(self) -> Profile:  # type: ignore[override]
        """Shared with the underlying :class:`User`, so profile refreshes show up everywhere."""
        return self._user._profile

    @_profile.setter
    def _profile(self, value: Profile) -> None:
        self._user._profile = value

    @property
    def user(self) -> BaseUser:
        return self._user

    @property
    def guild(self) -> "Community":
        return self.community

    @property
    def _cid(self) -> str:
        return self.community.id

    @property
    def nick(self) -> Optional[str]:
        if "nick" in self._overrides:
            return self._overrides["nick"]
        return self._state.native.member_nickname(self._cid, self.npub)

    @property
    def display_name(self) -> str:
        return self.nick or super().display_name

    @property
    def roles(self) -> List["Role"]:
        """Roles held, lowest first like discord.py (``@everyone`` first)."""
        if "role_ids" in self._overrides:
            ids = self._overrides["role_ids"]
            roles = [r for r in self.community.roles if r.id in ids]
        else:
            try:
                data = self._state.native.member_roles(self._cid, self.npub)
            except Exception:
                data = []
            from .role import Role

            roles = [Role(self._state, self.community, d) for d in data]
        roles.sort(key=lambda r: r.position)
        return [self.community.default_role] + roles

    @property
    def top_role(self) -> "Role":
        roles = self.roles
        return roles[-1]

    @property
    def guild_permissions(self) -> Permissions:
        try:
            return Permissions(self._state.native.member_permissions(self._cid, self.npub))
        except Exception:
            return Permissions.none()

    resolved_permissions = guild_permissions

    def permissions_in(self, channel: "TextChannel") -> Permissions:
        return channel.permissions_for(self)

    @property
    def timed_out_until(self) -> Optional[datetime.datetime]:
        if "timed_out_until" in self._overrides:
            return self._overrides["timed_out_until"]
        try:
            until = self._state.native.member_timed_out_until(self._cid, self.npub)
        except Exception:
            return None
        return datetime.datetime.fromtimestamp(until, tz=datetime.timezone.utc) if until else None

    def is_timed_out(self) -> bool:
        t = self.timed_out_until
        return t is not None and t > utcnow()

    @property
    def joined_at(self) -> Optional[datetime.datetime]:
        return None

    @property
    def pending(self) -> bool:
        return False

    @property
    def colour(self):
        from .colour import Colour

        for role in reversed(self.roles):
            if role.colour.value:
                return role.colour
        return Colour.default()

    color = colour

    def is_owner(self) -> bool:
        return self._state.native.member_is_owner(self._cid, self.npub)

    def is_admin(self) -> bool:
        try:
            return self._state.native.member_is_admin(self._cid, self.npub)
        except Exception:
            return False

    def is_banned(self) -> bool:
        return self._state.native.member_is_banned(self._cid, self.npub)

    def can(self, permission: Union[int, Permissions, str]) -> bool:
        """Whether the member holds a permission: ``member.can("kick_members")``."""
        if isinstance(permission, str):
            from .permissions import DISCORD_ONLY, VALID_FLAGS

            if permission in DISCORD_ONLY:
                return True
            permission = VALID_FLAGS[permission]
        return self._state.native.member_can(self._cid, self.npub, int(permission))

    def can_read(self, channel: Any) -> bool:
        return self._state.native.member_can_read(self._cid, self.npub, getattr(channel, "id", channel))

    def get_role(self, role_id: str) -> Optional["Role"]:
        return next((r for r in self.roles if r.id == role_id), None)

    # -- moderation -----------------------------------------------------------------------

    async def kick(self, *, reason: Optional[str] = None) -> None:
        await self._state.native.member_kick(self._cid, self.npub)

    async def ban(self, *, reason: Optional[str] = None, delete_message_days: int = 0, delete_message_seconds: int = 0) -> None:
        await self._state.native.member_ban(self._cid, self.npub)

    async def unban(self, *, reason: Optional[str] = None) -> None:
        await self._state.native.member_unban(self._cid, self.npub)

    async def timeout(self, until: Optional[Union[datetime.timedelta, datetime.datetime]], /, *, reason: Optional[str] = None) -> None:
        """Time the member out for a ``timedelta`` or until a ``datetime``; ``None`` lifts it."""
        if until is None:
            await self._state.native.member_remove_timeout(self._cid, self.npub)
            return
        if isinstance(until, datetime.datetime):
            if until.tzinfo is None:
                until = until.replace(tzinfo=datetime.timezone.utc)
            seconds = (until - utcnow()).total_seconds()
        else:
            seconds = until.total_seconds()
        await self._state.native.member_timeout(self._cid, self.npub, max(seconds, 0.0))

    async def remove_timeout(self, *, reason: Optional[str] = None) -> None:
        await self._state.native.member_remove_timeout(self._cid, self.npub)

    async def add_roles(self, *roles: Any, reason: Optional[str] = None, atomic: bool = True) -> None:
        for role in roles:
            await self._state.native.member_add_role(self._cid, self.npub, getattr(role, "id", role))

    async def remove_roles(self, *roles: Any, reason: Optional[str] = None, atomic: bool = True) -> None:
        for role in roles:
            await self._state.native.member_remove_role(self._cid, self.npub, getattr(role, "id", role))

    async def grant_admin(self) -> None:
        await self._state.native.member_grant_admin(self._cid, self.npub)

    async def revoke_admin(self) -> None:
        await self._state.native.member_revoke_admin(self._cid, self.npub)

    async def edit(
        self,
        *,
        nick: Optional[str] = MISSING,
        roles: List[Any] = MISSING,
        timed_out_until: Optional[datetime.datetime] = MISSING,
        reason: Optional[str] = None,
        **ignored: Any,
    ) -> "Member":
        if nick is not MISSING:
            await self._state.native.member_set_nickname(self._cid, self.npub, nick or "")
        if roles is not MISSING:
            ids = [getattr(r, "id", r) for r in roles if getattr(r, "id", r) != "everyone"]
            await self._state.native.member_set_roles(self._cid, self.npub, ids)
        if timed_out_until is not MISSING:
            await self.timeout(timed_out_until)
        return self

    async def move_to(self, channel: Any, *, reason: Optional[str] = None) -> None:
        raise NotImplementedError("Vector has no server-side voice moves")

    def _snapshot(self, **overrides: Any) -> "Member":
        return Member(self._state, self.community, self, overrides=overrides)

    def __repr__(self) -> str:
        return f"<Member npub={self.npub!r} name={self.name!r} community={self.community.id!r}>"
