"""Exceptions, named after their discord.py counterparts where one exists."""

from __future__ import annotations

from typing import Optional

try:  # the native hierarchy, so errors raised in Rust are catchable by these names
    from ._native import (
        NetworkError as _NativeNetworkError,
        NotFound as _NativeNotFound,
        NotInitialized as _NativeNotInitialized,
        NotPermitted as _NativeNotPermitted,
        VectorException as _NativeVectorException,
    )
except ImportError:  # pragma: no cover - lets the pure-Python layer import without the extension
    class _NativeVectorException(Exception):
        pass

    class _NativeNotPermitted(_NativeVectorException):
        pass

    class _NativeNotFound(_NativeVectorException):
        pass

    class _NativeNotInitialized(_NativeVectorException):
        pass

    class _NativeNetworkError(_NativeVectorException):
        pass


__all__ = (
    "VectorException",
    "DiscordException",
    "ClientException",
    "HTTPException",
    "Forbidden",
    "NotFound",
    "NotInitialized",
    "LoginFailure",
    "InvalidData",
    "InvalidArgument",
    "ConnectionClosed",
    "PrivilegedIntentsRequired",
)

#: Base class of every error this library raises (the native one, so Rust errors match too).
VectorException = _NativeVectorException
#: discord.py name for the base class.
DiscordException = VectorException

#: The bot lacks a Community permission. ``err.args`` is ``(message, needed_bits, action)``.
Forbidden = _NativeNotPermitted
#: No such Community, Channel, Role, Category, message or member.
NotFound = _NativeNotFound
#: The bot is not logged in.
NotInitialized = _NativeNotInitialized
#: A relay or network request failed (discord.py's ``HTTPException`` covers the same ground).
HTTPException = _NativeNetworkError


class ClientException(VectorException):
    """Raised when an operation in the Client fails (misuse rather than a network problem)."""


class LoginFailure(ClientException):
    """The key or seed phrase given to :meth:`Client.login` was rejected."""


class InvalidData(ClientException):
    """Data from Vector was not in the expected shape."""


class InvalidArgument(ClientException):
    """An argument was invalid (kept for discord.py 1.x code)."""


class ConnectionClosed(ClientException):
    """The connection to Vector's relays ended."""

    def __init__(self, reason: Optional[str] = None):
        super().__init__(reason or "the connection closed")
        self.reason = reason


class PrivilegedIntentsRequired(ClientException):
    """Never raised: Vector has no privileged intents. Present so ``except`` clauses still work."""
