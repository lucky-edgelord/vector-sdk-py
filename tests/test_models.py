import datetime

import vector
from vector.ext.commands.core import StringView


def test_embed_renders_vector_markdown():
    e = vector.Embed(title="Stats", url="https://example.com", description="All good", colour=vector.Colour.blurple(),
                     timestamp=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))
    e.set_author(name="Kit")
    e.add_field(name="CPU", value="12%")
    e.add_field(name="RAM", value="1 GB")
    e.add_field(name="Notes", value="none", inline=False)
    e.set_footer(text="vector")
    e.set_image(url="attachment://chart.png")
    md = e.to_markdown()
    assert "<color #5865f2>▍</color>" in md
    assert "[Stats](https://example.com)" in md
    assert "**CPU** │ **RAM**" in md and "12% │ 1 GB" in md
    assert "-# vector • <t:1767225600:f>" in md
    assert e.attachment_names() == ["chart.png"]
    assert vector.Embed.from_dict(e.to_dict()) == e


def test_permissions_discord_names_and_vector_names():
    p = vector.Permissions(kick_members=True, ban_members=True, embed_links=True)
    assert p.kick and p.kick_members and p.ban
    assert p.embed_links  # discord-only permission reads as granted
    assert not p.manage_roles
    ow = vector.PermissionOverwrite(send_messages=False, view_channel=True)
    allow, deny = ow.pair()
    assert allow.view_channel and deny.send_messages
    assert vector.PermissionOverwrite.from_pair(allow, deny) == ow


def test_colour_presets_and_parsing():
    assert vector.Color.red().value == 0xE74C3C
    assert vector.Colour.from_str("#ff0000").to_rgb() == (255, 0, 0)


def test_stringview_quotes():
    v = StringView('one "two words" three')
    words = []
    while not v.eof:
        v.skip_ws()
        words.append(v.get_quoted_word())
    assert words == ["one", "two words", "three"]


def test_utils_get_find():
    class O:
        def __init__(self, name, n):
            self.name, self.n = name, n

    items = [O("a", 1), O("b", 2)]
    assert vector.utils.get(items, name="b").n == 2
    assert vector.utils.find(lambda o: o.n == 1, items).name == "a"
    assert vector.utils.format_dt(datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc), "R") == "<t:1767225600:R>"
