"""``Embed``: discord.py's API, rendered into Vector's markdown.

Vector has no embed objects, but it renders nearly all of markdown, coloured text
(``<color #hex>…</color>``) and Discord-style ``<t:UNIX:R>`` timestamps, so an embed becomes a
well-formatted message:

    ---                                (rule opening the embed)
    -# Author name                     (small line, linked if author.url)
    ### Title                          (heading in the embed colour, linked without a preview card)
    Description …

    | FIELD | INLINE FIELD |           (inline fields become one Vector table card)
    |---|---|
    | value | value |

    **Wide field**
    text

    ---
    -# footer • <t:…:f>      (small, under a divider)

Images set to
``attachment://name.png`` are sent as real attachments alongside; URL images are placed on their
own line so Vector shows a link preview.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Mapping, Optional, Union

from .colour import Colour

__all__ = ("Embed", "EmbedField")



class _Proxy:
    """Attribute bag, like discord.py's EmbedProxy: missing attributes read as ``None``."""

    def __init__(self, layer: Optional[Dict[str, Any]] = None):
        self.__dict__.update(layer or {})

    def __len__(self) -> int:
        return len(self.__dict__)

    def __repr__(self) -> str:
        inner = ", ".join(f"{k}={v!r}" for k, v in self.__dict__.items() if not k.startswith("_"))
        return f"EmbedProxy({inner})"

    def __getattr__(self, attr: str) -> None:
        return None

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, _Proxy) and self.__dict__ == other.__dict__


VECTOR_ACCENT = "#59fcb3"


class EmbedField(_Proxy):
    name: str
    value: str
    inline: bool


class Embed:
    def __init__(
        self,
        *,
        colour: Optional[Union[int, Colour]] = None,
        color: Optional[Union[int, Colour]] = None,
        title: Optional[Any] = None,
        type: str = "rich",
        url: Optional[Any] = None,
        description: Optional[Any] = None,
        timestamp: Optional[datetime.datetime] = None,
    ):
        self.colour = colour if colour is not None else color
        self.title: Optional[str] = str(title) if title is not None else None
        self.type = type
        self.url: Optional[str] = str(url) if url is not None else None
        self.description: Optional[str] = str(description) if description is not None else None
        self.timestamp = timestamp
        self._author: Dict[str, Any] = {}
        self._footer: Dict[str, Any] = {}
        self._image: Dict[str, Any] = {}
        self._thumbnail: Dict[str, Any] = {}
        self._fields: List[Dict[str, Any]] = []

    # -- discord.py surface ---------------------------------------------------------------

    @property
    def colour(self) -> Optional[Colour]:
        return self._colour

    @colour.setter
    def colour(self, value: Optional[Union[int, Colour]]) -> None:
        if value is None or isinstance(value, Colour):
            self._colour = value
        elif isinstance(value, int):
            self._colour = Colour(value)
        else:
            raise TypeError(f"Expected vector.Colour, int, or None but received {value.__class__.__name__} instead.")

    color = colour

    @property
    def timestamp(self) -> Optional[datetime.datetime]:
        return self._timestamp

    @timestamp.setter
    def timestamp(self, value: Optional[datetime.datetime]) -> None:
        if isinstance(value, datetime.datetime) and value.tzinfo is None:
            value = value.astimezone()
        self._timestamp = value

    @property
    def footer(self) -> _Proxy:
        return _Proxy(self._footer)

    def set_footer(self, *, text: Optional[Any] = None, icon_url: Optional[Any] = None) -> "Embed":
        self._footer = {}
        if text is not None:
            self._footer["text"] = str(text)
        if icon_url is not None:
            self._footer["icon_url"] = str(icon_url)
        return self

    def remove_footer(self) -> "Embed":
        self._footer = {}
        return self

    @property
    def image(self) -> _Proxy:
        return _Proxy(self._image)

    def set_image(self, *, url: Optional[Any]) -> "Embed":
        self._image = {} if url is None else {"url": str(url)}
        return self

    @property
    def thumbnail(self) -> _Proxy:
        return _Proxy(self._thumbnail)

    def set_thumbnail(self, *, url: Optional[Any]) -> "Embed":
        self._thumbnail = {} if url is None else {"url": str(url)}
        return self

    @property
    def video(self) -> _Proxy:
        return _Proxy()

    @property
    def provider(self) -> _Proxy:
        return _Proxy()

    @property
    def author(self) -> _Proxy:
        return _Proxy(self._author)

    def set_author(self, *, name: Any, url: Optional[Any] = None, icon_url: Optional[Any] = None) -> "Embed":
        self._author = {"name": str(name)}
        if url is not None:
            self._author["url"] = str(url)
        if icon_url is not None:
            self._author["icon_url"] = str(icon_url)
        return self

    def remove_author(self) -> "Embed":
        self._author = {}
        return self

    @property
    def fields(self) -> List[EmbedField]:
        return [EmbedField(f) for f in self._fields]

    def add_field(self, *, name: Any, value: Any, inline: bool = True) -> "Embed":
        self._fields.append({"name": str(name), "value": str(value), "inline": inline})
        return self

    def insert_field_at(self, index: int, *, name: Any, value: Any, inline: bool = True) -> "Embed":
        self._fields.insert(index, {"name": str(name), "value": str(value), "inline": inline})
        return self

    def clear_fields(self) -> "Embed":
        self._fields.clear()
        return self

    def remove_field(self, index: int) -> "Embed":
        try:
            del self._fields[index]
        except IndexError:
            pass
        return self

    def set_field_at(self, index: int, *, name: Any, value: Any, inline: bool = True) -> "Embed":
        self._fields[index] = {"name": str(name), "value": str(value), "inline": inline}
        return self

    def copy(self) -> "Embed":
        return Embed.from_dict(self.to_dict())

    def __len__(self) -> int:
        total = len(self.title or "") + len(self.description or "")
        for f in self._fields:
            total += len(f["name"]) + len(f["value"])
        total += len(self._footer.get("text", "")) + len(self._author.get("name", ""))
        return total

    def __bool__(self) -> bool:
        return any((self.title, self.url, self.description, self.colour, self._fields, self.timestamp,
                    self._author, self._thumbnail, self._footer, self._image))

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Embed) and self.to_dict() == other.to_dict()

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"type": self.type}
        if self.title is not None:
            d["title"] = self.title
        if self.description is not None:
            d["description"] = self.description
        if self.url is not None:
            d["url"] = self.url
        if self.colour is not None:
            d["color"] = self.colour.value
        if self.timestamp is not None:
            d["timestamp"] = self.timestamp.astimezone(datetime.timezone.utc).isoformat()
        if self._footer:
            d["footer"] = dict(self._footer)
        if self._image:
            d["image"] = dict(self._image)
        if self._thumbnail:
            d["thumbnail"] = dict(self._thumbnail)
        if self._author:
            d["author"] = dict(self._author)
        if self._fields:
            d["fields"] = [dict(f) for f in self._fields]
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Embed":
        self = cls(
            title=data.get("title"),
            description=data.get("description"),
            url=data.get("url"),
            type=data.get("type", "rich"),
            colour=data.get("color", data.get("colour")),
        )
        ts = data.get("timestamp")
        if ts:
            self.timestamp = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if data.get("footer"):
            self.set_footer(**data["footer"])
        if data.get("image"):
            self.set_image(url=data["image"].get("url"))
        if data.get("thumbnail"):
            self.set_thumbnail(url=data["thumbnail"].get("url"))
        if data.get("author"):
            self.set_author(**data["author"])
        for f in data.get("fields", []):
            self.add_field(name=f["name"], value=f["value"], inline=f.get("inline", True))
        return self

    # -- Vector rendering -----------------------------------------------------------------

    def attachment_names(self) -> List[str]:
        """Filenames referenced as ``attachment://…`` (sent as real files)."""
        names = []
        for layer in (self._image, self._thumbnail):
            url = layer.get("url", "")
            if url.startswith("attachment://"):
                names.append(url[len("attachment://"):])
        return names

    def image_urls(self) -> List[str]:
        """Web URLs of this embed's image and thumbnail (``attachment://`` ones are not included)."""
        return [u for u in (self._image.get("url"), self._thumbnail.get("url")) if u and not u.startswith("attachment://")]

    def to_markdown(self, *, part: str = "all", images: bool = True) -> str:
        """The embed as Vector markdown (what :meth:`Messageable.send` actually posts).

        ``part``: ``"all"``, ``"body"`` (everything above the footer) or ``"footer"`` (the footer quote only), so a
        message can put an attached image between them. ``images=False`` leaves out image URLs."""
        # always Vector's own mint, whatever colour the bot set, so embeds match the app
        hexcol = VECTOR_ACCENT

        def paint(text: str) -> str:
            return f"<color {hexcol}>{text}</color>" if hexcol else text

        def link(text: str, url: Optional[str]) -> str:
            # [text](<url>) is a link Vector will not unfurl into a big preview card
            return f"[{text}](<{url}>)" if url else text

        def cell(text: str) -> str:
            return str(text).replace("|", "\\|").replace("\n", "<br>")

        lines: List[str] = []

        if self._author:
            lines.append("-# " + link(self._author["name"], self._author.get("url")))

        if self.title:
            lines.append("### " + paint(f"**{link(self.title, self.url)}**"))

        if self.description:
            lines.extend(self.description.split("\n"))

        # fields: consecutive inline fields share a row (max 3), like Discord's grid
        rows: List[List[Dict[str, Any]]] = []
        for f in self._fields:
            if f.get("inline") and rows and rows[-1] and rows[-1][-1].get("inline") and len(rows[-1]) < 3:
                rows[-1].append(f)
            else:
                rows.append([f])
        for row in rows:
            if lines:
                lines.append("")
            if len(row) == 1:
                lines.append(f"**{row[0]['name']}**")
                lines.extend(row[0]["value"].split("\n"))
            else:
                lines.append("| " + " | ".join(cell(f["name"]) for f in row) + " |")
                lines.append("|" + "---|" * len(row))
                lines.append("| " + " | ".join(cell(f["value"]) for f in row) + " |")

        # an image can't live inside the quote (Vector has no inline images): a plain URL is left outside it, where
        # Vector unfurls it into a picture card; ``attachment://`` files are sent as real attachments by ``send``
        outside: List[str] = []
        if images:
            outside.extend(self.image_urls())

        footer_bits = []
        if self._footer.get("text"):
            footer_bits.append(self._footer["text"])
        if self.timestamp is not None:
            footer_bits.append(f"<t:{int(self.timestamp.timestamp())}:f>")

        def quote(ls: List[str]) -> str:
            # a blockquote gives the solid accent bar down the left edge; blank lines stay inside it
            return "\n".join(("> " + l) if l else ">" for l in ls)

        # layout: the embed body in a quote, then the image, then the footer + timestamp in a quote of its own
        blocks: List[str] = []
        if part in ("all", "body"):
            if lines:
                blocks.append(quote(lines))
            blocks.extend(outside)
        if footer_bits and part in ("all", "footer"):
            blocks.append(quote(["-# " + " • ".join(footer_bits)]))
        return "\n\n".join(blocks)

    def __str__(self) -> str:
        return self.to_markdown()

    def __repr__(self) -> str:
        return f"<Embed title={self.title!r} fields={len(self._fields)}>"
