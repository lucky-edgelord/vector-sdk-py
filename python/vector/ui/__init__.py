"""Discord-style UI components for Vector, built on reactions.

See :mod:`vector.ui.view` for how buttons and selects map onto reactions, and
:mod:`vector.ui.modal` for how modals become a short chat conversation.
"""

from .interaction import Followup, Interaction, InteractionResponse, InteractionType
from .modal import Modal, TextInput, TextStyle
from .view import (
    LETTER_EMOJI, NUMBER_EMOJI, Button, ButtonStyle, ChannelSelect, Item, MentionableSelect, Paginator, RoleSelect,
    Select, SelectOption, UserSelect, View, button, select,
)

__all__ = (
    "View", "Item", "Button", "ButtonStyle", "Select", "SelectOption", "UserSelect", "RoleSelect", "ChannelSelect",
    "MentionableSelect", "button", "select", "Modal", "TextInput", "TextStyle", "Interaction", "InteractionResponse",
    "InteractionType", "Followup", "Paginator", "LETTER_EMOJI", "NUMBER_EMOJI",
)
