"""Themes for Mini App panels (``xdc=True``).

A theme is a set of CSS variables, optional extra CSS, and a layout (``"panel"``: a form-like panel with a coloured embed bar, Discord-style buttons, selects and modals, but no chat
frame; or ``"card"``: a plainer card look)::

    await ctx.send(embed=e, view=v, xdc="midnight")                 # a built-in theme, by name
    await ctx.send(embed=e, view=v, xdc=vector.ui.themes.MIDNIGHT)

    brand = vector.ui.Theme("brand", vars={"--accent": "#ff6b6b", "--radius": "4px"},
                            css=".embed h2 { letter-spacing: .02em }")
    vector.ui.register_theme(brand)                                 # now usable as xdc="brand"
    bot = commands.Bot(..., ui_mode="xdc", ui_theme=brand)          # every embed and view becomes a panel

Variables: ``--bg --card --line --text --muted --accent --accent-text --danger --success --link --radius``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

__all__ = ("Theme", "register_theme", "get_theme", "THEMES", "VECTOR", "VECTOR_LIGHT", "DISCORD", "DISCORD_LIGHT", "MIDNIGHT",
           "PAPER", "CONTRAST")


class Theme:
    """CSS variables + extra CSS + a layout. ``css`` is applied after the built-in styles, so it wins."""

    def __init__(self, name: str, *, vars: Optional[Dict[str, str]] = None, css: str = "", layout: str = "panel",
                 dark: Optional[bool] = None):
        layout = "panel" if layout == "discord" else layout  # old name
        if layout not in ("card", "panel"):
            raise ValueError("layout must be 'card' or 'panel'")
        self.name = name
        self.vars: Dict[str, str] = dict(vars or {})
        self.css = css
        self.layout = layout
        self.dark = dark  # None: follow the phone's light/dark setting

    def extend(self, name: Optional[str] = None, *, vars: Optional[Dict[str, str]] = None, css: str = "",
               layout: Optional[str] = None) -> "Theme":
        """A copy with changes: ``vector.ui.themes.VECTOR.extend("mine", vars={"--accent": "#e91e63"})``."""
        merged = dict(self.vars)
        merged.update(vars or {})
        return Theme(name or self.name, vars=merged, css=(self.css + "\n" + css).strip(), layout=layout or self.layout,
                     dark=self.dark)

    def to_spec(self) -> Dict[str, Any]:
        for k in self.vars:
            if not k.startswith("--"):
                raise ValueError(f"theme variable {k!r} must start with '--'")
        return {"name": self.name, "vars": self.vars, "css": self.css, "layout": self.layout, "dark": self.dark}

    def __repr__(self) -> str:
        return f"<Theme {self.name!r} layout={self.layout!r}>"


# Vector's own look: black, mint accent (matches the app).
VECTOR = Theme("vector", dark=True, vars={
    "--bg": "#000000", "--card": "#111111", "--line": "#262626", "--text": "#f2f2f2", "--muted": "#8c8c8c",
    "--accent": "#59fcb3", "--accent-text": "#03261a", "--success": "#1f9d6a", "--danger": "#e5484d",
    "--link": "#59fcb3", "--radius": "12px", "--btn": "#242424", "--btn-text": "#f2f2f2"})

VECTOR_LIGHT = Theme("vector-light", dark=False, vars={
    "--bg": "#ffffff", "--card": "#f4f6f5", "--line": "#dfe4e2", "--text": "#101312", "--muted": "#667085",
    "--accent": "#0fb37a", "--accent-text": "#ffffff", "--success": "#12865b", "--link": "#0b8a5f",
    "--radius": "12px", "--btn": "#e4e8e6", "--btn-text": "#101312"})

# Discord's colours, for bots ported from Discord that want that look (same panel layout, no chat frame).
_DISCORD_DARK = {"--bg": "#313338", "--card": "#2b2d31", "--line": "#1e1f22", "--text": "#dbdee1", "--muted": "#949ba4",
                 "--accent": "#5865f2", "--accent-text": "#ffffff", "--danger": "#da373c", "--success": "#248046",
                 "--link": "#00a8fc", "--radius": "4px", "--btn": "#4e5058", "--btn-text": "#fff"}
DISCORD = Theme("discord", dark=True, vars=_DISCORD_DARK)

DISCORD_LIGHT = Theme("discord-light", dark=False, vars={
    "--bg": "#ffffff", "--card": "#f2f3f5", "--line": "#e3e5e8", "--text": "#313338", "--muted": "#5c5e66",
    "--accent": "#5865f2", "--accent-text": "#ffffff", "--danger": "#da373c", "--success": "#248046",
    "--link": "#006ce7", "--radius": "4px"})

MIDNIGHT = Theme("midnight", dark=True, vars={
    "--bg": "#05070d", "--card": "#0d1220", "--line": "#1b2438", "--text": "#e6ebf5", "--muted": "#7d8aa6",
    "--accent": "#6ea8fe", "--accent-text": "#04101f", "--link": "#8bb9ff", "--radius": "14px"})

PAPER = Theme("paper", dark=False, vars={
    "--bg": "#fbf8f1", "--card": "#f1ecdf", "--line": "#ddd5c2", "--text": "#2a261d", "--muted": "#7a705a",
    "--accent": "#b3541e", "--accent-text": "#ffffff", "--success": "#3f7d3a", "--link": "#8a3b12", "--radius": "6px"})

CONTRAST = Theme("high-contrast", dark=True, vars={
    "--bg": "#000000", "--card": "#000000", "--line": "#ffffff", "--text": "#ffffff", "--muted": "#e0e0e0",
    "--accent": "#ffd60a", "--accent-text": "#000000", "--danger": "#ff453a", "--success": "#30d158",
    "--link": "#64d2ff", "--radius": "2px"}, css=".embed,.btn,select,.chip{border-width:2px}")

THEMES: Dict[str, Theme] = {t.name: t for t in (VECTOR, VECTOR_LIGHT, DISCORD, DISCORD_LIGHT, MIDNIGHT, PAPER, CONTRAST)}


def register_theme(theme: Theme) -> Theme:
    """Make a theme available by name (``xdc="brand"``)."""
    THEMES[theme.name] = theme
    return theme


def get_theme(value: Union[None, bool, str, Theme, Dict[str, Any]], default: Union[str, Theme] = "vector") -> Theme:
    """A :class:`Theme` from a name, a Theme, a dict of variables, or ``True``/``None`` (the default)."""
    if isinstance(value, Theme):
        return value
    if isinstance(value, dict):
        return Theme("custom", vars=value)
    if isinstance(value, str):
        try:
            return THEMES[value.lower()]
        except KeyError:
            raise ValueError(f"unknown theme {value!r}; known: {', '.join(sorted(THEMES))}") from None
    if value is None or value is True:
        return get_theme(default) if not isinstance(default, Theme) else default
    raise TypeError(f"cannot make a theme from {value!r}")
