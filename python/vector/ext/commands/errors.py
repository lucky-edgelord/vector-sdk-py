"""Command errors: the same names and hierarchy as ``discord.ext.commands``."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from ...errors import ClientException, VectorException

__all__ = (
    "CommandError", "ConversionError", "UserInputError", "MissingRequiredArgument", "MissingRequiredAttachment",
    "TooManyArguments", "BadArgument", "BadUnionArgument", "BadLiteralArgument", "BadBoolArgument",
    "ArgumentParsingError", "UnexpectedQuoteError", "InvalidEndOfQuotedStringError", "ExpectedClosingQuoteError",
    "CheckFailure", "CheckAnyFailure", "PrivateMessageOnly", "NoPrivateMessage", "NotOwner", "MissingRole",
    "BotMissingRole", "MissingAnyRole", "BotMissingAnyRole", "MissingPermissions", "BotMissingPermissions",
    "NSFWChannelRequired", "CommandNotFound", "DisabledCommand", "CommandInvokeError", "CommandOnCooldown",
    "MaxConcurrencyReached", "MemberNotFound", "UserNotFound", "GuildNotFound", "CommunityNotFound",
    "ChannelNotFound", "ChannelNotReadable", "RoleNotFound", "MessageNotFound", "EmojiNotFound",
    "BadColourArgument", "BadColorArgument", "RangeError", "ExtensionError", "ExtensionAlreadyLoaded",
    "ExtensionNotLoaded", "NoEntryPointError", "ExtensionFailed", "ExtensionNotFound", "CommandRegistrationError",
    "HybridCommandError", "FlagError",
)


class CommandError(VectorException):
    def __init__(self, message: Optional[str] = None, *args: Any):
        if message is not None:
            super().__init__(message, *args)
        else:
            super().__init__(*args)

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


class ConversionError(CommandError):
    def __init__(self, converter: Any, original: Exception):
        self.converter = converter
        self.original = original
        super().__init__(str(original))


class UserInputError(CommandError):
    pass


class CommandNotFound(CommandError):
    pass


class MissingRequiredArgument(UserInputError):
    def __init__(self, param: Any):
        self.param = param
        super().__init__(f"{param.name} is a required argument that is missing.")


class MissingRequiredAttachment(UserInputError):
    def __init__(self, param: Any):
        self.param = param
        super().__init__(f"{param.name} is a required argument that is missing an attachment.")


class TooManyArguments(UserInputError):
    pass


class BadArgument(UserInputError):
    pass


class FlagError(BadArgument):
    pass


class RangeError(BadArgument):
    def __init__(self, value: Any, minimum: Any, maximum: Any):
        self.value, self.minimum, self.maximum = value, minimum, maximum
        bits = []
        if minimum is not None:
            bits.append(f"at least {minimum}")
        if maximum is not None:
            bits.append(f"at most {maximum}")
        super().__init__(f"value must be {' and '.join(bits)} but received {value!r}")


class BadUnionArgument(UserInputError):
    def __init__(self, param: Any, converters: Tuple[Any, ...], errors: List[CommandError]):
        self.param, self.converters, self.errors = param, converters, errors
        names = ", ".join(getattr(c, "__name__", c.__class__.__name__) for c in converters)
        super().__init__(f'Could not convert "{param.name}" into {names}.')


class BadLiteralArgument(UserInputError):
    def __init__(self, param: Any, literals: Tuple[Any, ...], errors: List[CommandError], argument: str = ""):
        self.param, self.literals, self.errors, self.argument = param, literals, errors, argument
        super().__init__(f'Could not convert "{param.name}" into the literal {", ".join(repr(x) for x in literals)}.')


class BadBoolArgument(BadArgument):
    def __init__(self, argument: str):
        self.argument = argument
        super().__init__(f"{argument} is not a recognised boolean option")


class ArgumentParsingError(UserInputError):
    pass


class UnexpectedQuoteError(ArgumentParsingError):
    def __init__(self, quote: str):
        self.quote = quote
        super().__init__(f"Unexpected quote mark, {quote!r}, in non-quoted string")


class InvalidEndOfQuotedStringError(ArgumentParsingError):
    def __init__(self, char: str):
        self.char = char
        super().__init__(f"Expected space after closing quotation but received {char!r}")


class ExpectedClosingQuoteError(ArgumentParsingError):
    def __init__(self, close_quote: str):
        self.close_quote = close_quote
        super().__init__(f"Expected closing {close_quote}.")


class CheckFailure(CommandError):
    pass


class CheckAnyFailure(CheckFailure):
    def __init__(self, checks: List[Any], errors: List[CheckFailure]):
        self.checks, self.errors = checks, errors
        super().__init__("You do not have permission to run this command.")


class PrivateMessageOnly(CheckFailure):
    def __init__(self, message: Optional[str] = None):
        super().__init__(message or "This command can only be used in private messages.")


class NoPrivateMessage(CheckFailure):
    def __init__(self, message: Optional[str] = None):
        super().__init__(message or "This command cannot be used in private messages.")


class NotOwner(CheckFailure):
    pass


class MissingRole(CheckFailure):
    def __init__(self, missing_role: Any):
        self.missing_role = missing_role
        super().__init__(f"Role {missing_role!r} is required to run this command.")


class BotMissingRole(CheckFailure):
    def __init__(self, missing_role: Any):
        self.missing_role = missing_role
        super().__init__(f"Bot requires the role {missing_role!r} to run this command")


class MissingAnyRole(CheckFailure):
    def __init__(self, missing_roles: List[Any]):
        self.missing_roles = missing_roles
        super().__init__(f"You are missing at least one of the required roles: {', '.join(map(repr, missing_roles))}")


class BotMissingAnyRole(CheckFailure):
    def __init__(self, missing_roles: List[Any]):
        self.missing_roles = missing_roles
        super().__init__(f"Bot is missing at least one of the required roles: {', '.join(map(repr, missing_roles))}")


def _perm_text(perms: List[str]) -> str:
    missing = [p.replace("_", " ").replace("guild", "server").title() for p in perms]
    return ", ".join(missing[:-1]) + f" and {missing[-1]}" if len(missing) > 2 else " and ".join(missing)


class MissingPermissions(CheckFailure):
    def __init__(self, missing_permissions: List[str], *args: Any):
        self.missing_permissions = missing_permissions
        super().__init__(f"You are missing {_perm_text(missing_permissions)} permission(s) to run this command.", *args)


class BotMissingPermissions(CheckFailure):
    def __init__(self, missing_permissions: List[str], *args: Any):
        self.missing_permissions = missing_permissions
        super().__init__(f"Bot requires {_perm_text(missing_permissions)} permission(s) to run this command.", *args)


class NSFWChannelRequired(CheckFailure):
    def __init__(self, channel: Any):
        self.channel = channel
        super().__init__(f"Channel '{channel}' needs to be NSFW for this command to work.")


class DisabledCommand(CommandError):
    pass


class CommandInvokeError(CommandError):
    def __init__(self, e: Exception):
        self.original = e
        super().__init__(f"Command raised an exception: {e.__class__.__name__}: {e}")


class HybridCommandError(CommandError):
    def __init__(self, original: Exception):
        self.original = original
        super().__init__(f"Hybrid command raised an error: {original}")


class CommandOnCooldown(CommandError):
    def __init__(self, cooldown: Any, retry_after: float, type: Any):
        self.cooldown, self.retry_after, self.type = cooldown, retry_after, type
        super().__init__(f"You are on cooldown. Try again in {retry_after:.2f}s")


class MaxConcurrencyReached(CommandError):
    def __init__(self, number: int, per: Any):
        self.number, self.per = number, per
        super().__init__(f"Too many people are using this command. It can only be used {number} time(s) at once.")


class MemberNotFound(BadArgument):
    def __init__(self, argument: str):
        self.argument = argument
        super().__init__(f'Member "{argument}" not found.')


class UserNotFound(BadArgument):
    def __init__(self, argument: str):
        self.argument = argument
        super().__init__(f'User "{argument}" not found.')


class GuildNotFound(BadArgument):
    def __init__(self, argument: str):
        self.argument = argument
        super().__init__(f'Community "{argument}" not found.')


CommunityNotFound = GuildNotFound


class ChannelNotFound(BadArgument):
    def __init__(self, argument: Any):
        self.argument = argument
        super().__init__(f'Channel "{argument}" not found.')


class ChannelNotReadable(BadArgument):
    def __init__(self, argument: Any):
        self.argument = argument
        super().__init__(f"Can't read messages in {argument}.")


class RoleNotFound(BadArgument):
    def __init__(self, argument: str):
        self.argument = argument
        super().__init__(f'Role "{argument}" not found.')


class MessageNotFound(BadArgument):
    def __init__(self, argument: str):
        self.argument = argument
        super().__init__(f'Message "{argument}" not found.')


class EmojiNotFound(BadArgument):
    def __init__(self, argument: str):
        self.argument = argument
        super().__init__(f'Emoji "{argument}" not found.')


class BadColourArgument(BadArgument):
    def __init__(self, argument: str):
        self.argument = argument
        super().__init__(f'Colour "{argument}" is invalid.')


BadColorArgument = BadColourArgument


class ExtensionError(VectorException):
    def __init__(self, message: Optional[str] = None, *args: Any, name: str):
        self.name = name
        super().__init__(message or f"Extension {name!r} had an error.", *args)


class ExtensionAlreadyLoaded(ExtensionError):
    def __init__(self, name: str):
        super().__init__(f"Extension {name!r} is already loaded.", name=name)


class ExtensionNotLoaded(ExtensionError):
    def __init__(self, name: str):
        super().__init__(f"Extension {name!r} has not been loaded.", name=name)


class NoEntryPointError(ExtensionError):
    def __init__(self, name: str):
        super().__init__(f"Extension {name!r} has no 'setup' function.", name=name)


class ExtensionFailed(ExtensionError):
    def __init__(self, name: str, original: Exception):
        self.original = original
        super().__init__(f"Extension {name!r} raised an error: {original.__class__.__name__}: {original}", name=name)


class ExtensionNotFound(ExtensionError):
    def __init__(self, name: str):
        super().__init__(f"Extension {name!r} could not be loaded.", name=name)


class CommandRegistrationError(ClientException):
    def __init__(self, name: str, *, alias_conflict: bool = False):
        self.name = name
        self.alias_conflict = alias_conflict
        kind = "alias" if alias_conflict else "command"
        super().__init__(f"The {kind} {name} is already an existing command or alias.")
