"""``Colour`` / ``Color``: a 24-bit RGB value with discord.py's presets."""

from __future__ import annotations

import colorsys
import random
from typing import Any, Optional, Tuple, Union

__all__ = ("Colour", "Color")


class Colour:
    __slots__ = ("value",)

    def __init__(self, value: int):
        if not isinstance(value, int):
            raise TypeError(f"Expected int parameter, received {value.__class__.__name__} instead.")
        self.value: int = value & 0xFFFFFF

    def _get_byte(self, byte: int) -> int:
        return (self.value >> (8 * byte)) & 0xFF

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Colour) and self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)

    def __int__(self) -> int:
        return self.value

    def __str__(self) -> str:
        return f"#{self.value:0>6x}"

    def __repr__(self) -> str:
        return f"<Colour value={self.value}>"

    @property
    def r(self) -> int:
        return self._get_byte(2)

    @property
    def g(self) -> int:
        return self._get_byte(1)

    @property
    def b(self) -> int:
        return self._get_byte(0)

    def to_rgb(self) -> Tuple[int, int, int]:
        return (self.r, self.g, self.b)

    @classmethod
    def from_rgb(cls, r: int, g: int, b: int) -> "Colour":
        return cls((r << 16) + (g << 8) + b)

    @classmethod
    def from_hsv(cls, h: float, s: float, v: float) -> "Colour":
        rgb = colorsys.hsv_to_rgb(h, s, v)
        return cls.from_rgb(*(int(x * 255) for x in rgb))

    @classmethod
    def from_str(cls, value: str) -> "Colour":
        value = value.strip()
        if value.startswith("#"):
            return cls(int(value[1:], 16))
        if value.startswith("0x"):
            return cls(int(value[2:], 16))
        if value.startswith("rgb(") and value.endswith(")"):
            r, g, b = (int(x) for x in value[4:-1].split(","))
            return cls.from_rgb(r, g, b)
        return cls(int(value, 16))

    @classmethod
    def random(cls, *, seed: Optional[Union[int, str, float, bytes, bytearray]] = None) -> "Colour":
        rand = random if seed is None else random.Random(seed)
        return cls.from_hsv(rand.random(), 1, 1)

    @classmethod
    def default(cls) -> "Colour":
        return cls(0)

    # discord.py's palette
    @classmethod
    def teal(cls): return cls(0x1ABC9C)
    @classmethod
    def dark_teal(cls): return cls(0x11806A)
    @classmethod
    def brand_green(cls): return cls(0x57F287)
    @classmethod
    def green(cls): return cls(0x2ECC71)
    @classmethod
    def dark_green(cls): return cls(0x1F8B4C)
    @classmethod
    def blue(cls): return cls(0x3498DB)
    @classmethod
    def dark_blue(cls): return cls(0x206694)
    @classmethod
    def purple(cls): return cls(0x9B59B6)
    @classmethod
    def dark_purple(cls): return cls(0x71368A)
    @classmethod
    def magenta(cls): return cls(0xE91E63)
    @classmethod
    def dark_magenta(cls): return cls(0xAD1457)
    @classmethod
    def gold(cls): return cls(0xF1C40F)
    @classmethod
    def dark_gold(cls): return cls(0xC27C0E)
    @classmethod
    def orange(cls): return cls(0xE67E22)
    @classmethod
    def dark_orange(cls): return cls(0xA84300)
    @classmethod
    def brand_red(cls): return cls(0xED4245)
    @classmethod
    def red(cls): return cls(0xE74C3C)
    @classmethod
    def dark_red(cls): return cls(0x992D22)
    @classmethod
    def lighter_grey(cls): return cls(0x95A5A6)
    lighter_gray = lighter_grey
    @classmethod
    def dark_grey(cls): return cls(0x607D8B)
    dark_gray = dark_grey
    @classmethod
    def light_grey(cls): return cls(0x979C9F)
    light_gray = light_grey
    @classmethod
    def darker_grey(cls): return cls(0x546E7A)
    darker_gray = darker_grey
    @classmethod
    def og_blurple(cls): return cls(0x7289DA)
    @classmethod
    def blurple(cls): return cls(0x5865F2)
    @classmethod
    def greyple(cls): return cls(0x99AAB5)
    @classmethod
    def dark_theme(cls): return cls(0x313338)
    @classmethod
    def fuchsia(cls): return cls(0xEB459E)
    @classmethod
    def yellow(cls): return cls(0xFEE75C)
    @classmethod
    def pink(cls): return cls(0xEB459F)
    @classmethod
    def dark_embed(cls): return cls(0x2B2D31)
    @classmethod
    def light_embed(cls): return cls(0xEEEFF1)
    # Vector's own accent
    @classmethod
    def vector(cls): return cls(0x59FCB3)


Color = Colour
