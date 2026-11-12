"""Community roles."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from .colour import Colour
from .permissions import Permissions
from .utils import MISSING

if TYPE_CHECKING:
    from .community import Community
    from .state import ConnectionState
    from .user import Member

__all__ = ("Role",)


class Role:
    """A Community role. ``Role.id == "everyone"`` is the ``@everyone`` pseudo-role."""

    __slots__ = ("_state", "community", "id", "name", "_colour", "_permissions", "position", "hoist",
                 "mentionable", "channel_id", "rank", "raw")

    def __init__(self, state: "ConnectionState", community: "Community", data: Dict[str, Any]):
        self._state = state
        self.community = community
        self.raw = data
        self.id: str = data.get("role_id") or data.get("id") or ""
        self.name: str = data.get("name", "")
        self._colour = int(data.get("color") or 0)
        self._permissions = int(data.get("permissions") or 0)
        self.position: int = int(data.get("position") or 0)
        self.hoist: bool = bool(data.get("display"))
        self.mentionable: bool = bool(data.get("mentionable"))
        scope = data.get("scope") or {}
        self.channel_id: Optional[str] = scope.get("channel_id") if scope.get("kind") == "channel" else None
        self.rank: Optional[str] = data.get("rank")

    @classmethod
    def _everyone(cls, state: "ConnectionState", community: "Community", permissions: int) -> "Role":
        return cls(state, community, {"role_id": "everyone", "name": "@everyone", "permissions": permissions, "position": 0})

    @property
    def guild(self) -> "Community":
        return self.community

    @property
    def colour(self) -> Colour:
        return Colour(self._colour)

    color = colour

    @property
    def permissions(self) -> Permissions:
        return Permissions(self._permissions)

    @property
    def mention(self) -> str:
        return "@everyone" if self.is_default() else f"@{self.name}"

    def is_default(self) -> bool:
        return self.id == "everyone"

    def is_bot_managed(self) -> bool:
        return False

    def is_assignable(self) -> bool:
        return not self.is_default()

    @property
    def members(self) -> List["Member"]:
        if self.is_default():
            return list(self.community.members)
        try:
            npubs = self._state.native.role_holders(self.community.id, self.id)
        except Exception:
            return []
        return [self.community._member(n) for n in npubs]

    async def edit(
        self,
        *,
        name: str = MISSING,
        permissions: Union[Permissions, int] = MISSING,
        colour: Union[Colour, int] = MISSING,
        color: Union[Colour, int] = MISSING,
        hoist: bool = MISSING,
        mentionable: bool = MISSING,
        position: int = MISSING,
        reason: Optional[str] = None,
        **ignored: Any,
    ) -> Optional["Role"]:
        native = self._state.native
        cid = self.community.id
        if self.is_default():
            if permissions is not MISSING:
                await native.community_set_everyone_permissions(cid, int(permissions))
                self._permissions = int(permissions)
            return self
        col = colour if colour is not MISSING else color
        await native.role_edit(
            cid, self.id,
            name=None if name is MISSING else name,
            color=None if col is MISSING else int(col),
            permissions=None if permissions is MISSING else int(permissions),
            shown=None if hoist is MISSING else hoist,
            mentionable=None if mentionable is MISSING else mentionable,
        )
        if position is not MISSING:
            order = [r for r in self.community.roles if not r.is_default() and r.id != self.id]
            order.sort(key=lambda r: r.position, reverse=True)
            idx = max(0, len(order) - position + 1)
            order.insert(min(idx, len(order)), self)
            await native.community_reorder_roles(cid, [r.id for r in order])
        try:
            data = native.role_info(cid, self.id)
            self.__init__(self._state, self.community, data)  # type: ignore[misc]
        except Exception:
            pass
        return self

    async def delete(self, *, reason: Optional[str] = None) -> None:
        await self._state.native.role_delete(self.community.id, self.id)

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"<Role id={self.id!r} name={self.name!r}>"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Role) and other.id == self.id and other.community.id == self.community.id

    def __hash__(self) -> int:
        return hash((self.community.id, self.id))

    def __lt__(self, other: "Role") -> bool:
        return self.position < other.position

    def __le__(self, other: "Role") -> bool:
        return self.position <= other.position

    def __gt__(self, other: "Role") -> bool:
        return self.position > other.position

    def __ge__(self, other: "Role") -> bool:
        return self.position >= other.position
