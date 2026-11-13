"""Embeds (BDFD + D.js-BDscript), and Components V2 rendered as embeds."""

from __future__ import annotations

import datetime
import re

from ..registry import BDScriptError, fn
from ..util import get_channel, to_int, truthy

_NAMED = {"red": 0xED4245, "green": 0x57F287, "blue": 0x3498DB, "yellow": 0xFEE75C, "orange": 0xE67E22,
          "purple": 0x9B59B6, "black": 0x000000, "white": 0xFFFFFF, "grey": 0x95A5A6, "gray": 0x95A5A6,
          "blurple": 0x5865F2, "pink": 0xEB459E, "random": -1}


def colour_value(c: str) -> int:
    c = c.strip().lower()
    if c in _NAMED:
        if _NAMED[c] == -1:
            import random
            return random.randint(0, 0xFFFFFF)
        return _NAMED[c]
    if c.isdigit():
        return int(c)
    h = c.lstrip("#")
    if re.fullmatch(r"[0-9a-f]{3}", h):
        h = "".join(ch * 2 for ch in h)
    if not re.fullmatch(r"[0-9a-f]{6}", h):
        raise BDScriptError(f"invalid color '{c}'")
    return int(h, 16)


def _e(ctx, index):
    return ctx.response.embed(index)


@fn("title", min_args=1, brackets="required")
def _title(ctx, text, index="", *rest):
    e = _e(ctx, index if index.strip().isdigit() else "")
    e.title = text
    if index and not index.strip().isdigit() and index.startswith("http"):
        e.url = index  # D.js-BDscript: $title[text;url]
    return ""


@fn("description", min_args=1, brackets="required")
def _description(ctx, text, index=""):
    _e(ctx, index).description = text
    return ""


@fn("color", min_args=1, brackets="required")
def _color(ctx, c, index=""):
    _e(ctx, index).colour = colour_value(c)
    return ""


@fn("footer", min_args=1, brackets="required")
def _footer(ctx, text, index_or_icon="", *rest):
    if index_or_icon and not index_or_icon.strip().isdigit():  # $footer[text;iconURL;(index)]
        _e(ctx, rest[0] if rest else "").set_footer(text=text, icon_url=index_or_icon)
    else:
        e = _e(ctx, index_or_icon)
        e.set_footer(text=text, icon_url=e.footer.icon_url if e.footer else None)
    return ""


@fn("footerIcon", min_args=1, brackets="required")
def _footericon(ctx, url, index=""):
    e = _e(ctx, index)
    e.set_footer(text=(e.footer.text if e.footer else "") or "​", icon_url=url)
    return ""


@fn("image", min_args=1, brackets="required")
def _image(ctx, url, index=""):
    _e(ctx, index).set_image(url=url)
    return ""


@fn("thumbnail", min_args=1, brackets="required")
def _thumbnail(ctx, url, index=""):
    _e(ctx, index).set_thumbnail(url=url)
    return ""


@fn("author", min_args=0, brackets="optional")
def _author(ctx, text="", index_or_icon="", url=""):
    if text == "" and not index_or_icon:
        return ctx.author.name if ctx.author else ""  # bare $author (fork): author name
    if index_or_icon and not index_or_icon.strip().isdigit():  # fork: $author[name;icon;url]
        _e(ctx, "").set_author(name=text, icon_url=index_or_icon, url=url or None)
    else:
        e = _e(ctx, index_or_icon)
        e.set_author(name=text, icon_url=e.author.icon_url if e.author else None, url=e.author.url if e.author else None)
    return ""


@fn("authorIcon", min_args=1, brackets="required")
def _authoricon(ctx, url, index=""):
    e = _e(ctx, index)
    e.set_author(name=(e.author.name if e.author else "") or "​", icon_url=url, url=e.author.url if e.author else None)
    return ""


@fn("authorURL", min_args=1, brackets="required")
def _authorurl(ctx, url, index=""):
    e = _e(ctx, index)
    e.set_author(name=(e.author.name if e.author else "") or "​", icon_url=e.author.icon_url if e.author else None, url=url)
    return ""


@fn("embeddedURL", min_args=1, brackets="required")
def _embeddedurl(ctx, url, index=""):
    _e(ctx, index).url = url
    return ""


@fn("addField", min_args=2, brackets="required")
def _addfield(ctx, name, value, inline="no", index=""):
    _e(ctx, index).add_field(name=name, value=value, inline=truthy(inline, False) if inline else False)
    return ""


@fn("addTimestamp")
@fn("addTimestampComplex")
def _addtimestamp(ctx, index="", ms=""):
    e = _e(ctx, index)
    if ms.strip():
        e.timestamp = datetime.datetime.fromtimestamp(int(ms) / 1000, datetime.timezone.utc)
    else:
        e.timestamp = datetime.datetime.now(datetime.timezone.utc)
    return ""


@fn("attachment", min_args=1, brackets="required")
def _attachment(ctx, source, name="file"):
    """D.js-BDscript ``$attachment[url or path or text;name]``: attach a file."""
    import io
    import os
    from ....file import File
    if source.startswith(("http://", "https://")):
        import urllib.request
        with urllib.request.urlopen(source, timeout=15) as r:
            data = r.read(25 * 1024 * 1024)
        ctx.response.files.append(File(io.BytesIO(data), filename=name or os.path.basename(source)))
    elif os.path.isfile(source) and getattr(ctx.bot, "allow_files", False):
        ctx.response.files.append(File(source, filename=name or os.path.basename(source)))
    else:
        ctx.response.files.append(File(io.BytesIO(source.encode()), filename=name or "file.txt"))
    return ""


@fn("getEmbedData", min_args=4, brackets="required")
async def _getembeddata(ctx, channel_id, message_id, index, prop):
    ch = get_channel(ctx, channel_id)
    msg = await ch.fetch_message(message_id)
    embeds = getattr(msg, "embeds", []) or []
    i = to_int(index)
    if not 0 < i <= len(embeds):
        return ""
    e = embeds[i - 1]
    p = prop.strip().lower()
    return {"title": e.title, "description": e.description, "footer": e.footer.text if e.footer else "",
            "color": f"#{e.colour.value:06x}" if e.colour else "", "image": e.image.url if e.image else "",
            "timestamp": str(int(e.timestamp.timestamp())) if e.timestamp else ""}.get(p, "") or ""


@fn("sendEmbedMessage", min_args=2, brackets="required")
async def _sendembed(ctx, channel_id, content="", title="", title_url="", description="", color="", author="",
                     author_icon="", footer="", footer_icon="", thumbnail="", image="", add_ts="no", return_id="no"):
    from ....embeds import Embed
    ch = get_channel(ctx, channel_id)
    e = Embed(title=title or None, url=title_url or None, description=description or None)
    if color:
        e.colour = colour_value(color)
    if author:
        e.set_author(name=author, icon_url=author_icon or None)
    if footer:
        e.set_footer(text=footer, icon_url=footer_icon or None)
    if thumbnail:
        e.set_thumbnail(url=thumbnail)
    if image:
        e.set_image(url=image)
    if truthy(add_ts):
        e.timestamp = datetime.datetime.now(datetime.timezone.utc)
    msg = await ch.send(content or None, embed=e)
    return str(msg.id) if truthy(return_id) else ""


@fn("editEmbedIn", min_args=1, brackets="required")
async def _editembedin(ctx, when, title="", description="", footer="", color=""):
    import asyncio
    from ....embeds import Embed
    from ..util import seconds
    e = Embed(title=title or None, description=description or None)
    if footer:
        e.set_footer(text=footer)
    if color:
        e.colour = colour_value(color)

    async def later():
        await asyncio.sleep(seconds(when))
        for mid in ctx.sent_ids[-1:]:
            try:
                m = await ctx.channel.fetch_message(mid)
                await m.edit(embed=e)
            except Exception:
                pass
    asyncio.ensure_future(later())
    return ""


# -- Components V2, rendered with embeds (Vector has no component layouts) ----------------------------------
def _named(ctx, name: str, kind: str):
    reg = ctx.extras.setdefault("v2", {})
    if name not in reg:
        raise BDScriptError(f"no {kind} named '{name}'")
    return reg[name]


@fn("addContainer", min_args=1, brackets="required")
def _addcontainer(ctx, name, color="", spoiler="no"):
    index = max(ctx.response.embeds or {0: None}) + 1
    e = ctx.response.embed(index)
    if color:
        e.colour = colour_value(color)
    ctx.extras.setdefault("v2", {})[name] = {"kind": "container", "embed": e}
    return ""


def _target_embed(ctx, name: str):
    if not name:
        return ctx.response.embed(max(ctx.response.embeds or {1: None}))
    item = _named(ctx, name, "container/section")
    return item["embed"]


@fn("addSection", min_args=1, brackets="required")
def _addsection(ctx, name, container=""):
    e = _target_embed(ctx, container)
    ctx.extras.setdefault("v2", {})[name] = {"kind": "section", "embed": e}
    return ""


@fn("addTextDisplay", min_args=1, brackets="required")
def _addtext(ctx, content, target=""):
    e = _target_embed(ctx, target)
    e.description = (e.description + "\n" if e.description else "") + content
    return ""


@fn("addSeparator", brackets="optional")
def _addsep(ctx, divider="yes", spacing="", container=""):
    e = _target_embed(ctx, container)
    if e.description:
        e.description += "\n​" if not truthy(divider, True) else "\n―――――――――"
    return ""


@fn("addThumbnail", min_args=1, brackets="required")
def _addthumb(ctx, url, desc="", spoiler="no", section=""):
    _target_embed(ctx, section).set_thumbnail(url=url)
    return ""


@fn("addMediaGallery", min_args=1, brackets="required")
def _addgallery(ctx, name, container=""):
    e = _target_embed(ctx, container)
    ctx.extras.setdefault("v2", {})[name] = {"kind": "gallery", "embed": e}
    return ""


@fn("addMediaGalleryItem", min_args=1, brackets="required")
def _addgalleryitem(ctx, url, desc="", spoiler="no", gallery=""):
    e = _target_embed(ctx, gallery)
    if not e.image.url:
        e.set_image(url=url)
    else:
        e.description = (e.description + "\n" if e.description else "") + f"[{desc or 'image'}](<{url}>)"
    return ""
