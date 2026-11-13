"""Buttons, select menus, modals, interactions and slash commands."""

from __future__ import annotations

from ..context import ButtonSpec, ModalSpec, SelectSpec
from ..registry import BDScriptError, fn
from ..util import to_int, truthy


def _rows(ctx):
    return ctx.response.rows


def _place(ctx, item, new_row: bool) -> None:
    rows = _rows(ctx)
    if new_row and rows[-1]:
        rows.append([])
    if len(rows[-1]) >= 5:
        rows.append([])
    if sum(len(r) for r in rows) >= 25:
        raise BDScriptError("a message can have at most 25 components")
    rows[-1].append(item)


def _find(rows, cid):
    for row in rows:
        for item in row:
            if getattr(item, "custom_id", None) == cid or getattr(item, "url", None) == cid:
                return item
    return None


async def _message_rows(ctx, message_id):
    """Component rows of an already-sent message (for edits)."""
    view = ctx.bot.views.get(str(message_id))
    if view is None:
        raise BDScriptError(f"message {message_id} has no components this bot knows about")
    return view


def _all_ids(rows):
    return [getattr(i, "custom_id", None) for r in rows for i in r]


@fn("addButton", min_args=4, brackets="required")
async def _addbutton(ctx, new_row, cid, label="", style="secondary", disabled="no", emoji="", message_id=""):
    style = style.strip().lower() or "secondary"
    is_url = cid.startswith(("http://", "https://"))
    if style == "link" and not is_url:
        raise BDScriptError("link buttons need a URL")
    spec = ButtonSpec(custom_id=cid, label=label, style="link" if is_url else style,
                      disabled=truthy(disabled, False), emoji=emoji or None, url=cid if is_url else None,
                      new_row=truthy(new_row, False))
    if message_id.strip():
        await ctx.bot.edit_components(ctx, message_id.strip(), lambda rows: _append(rows, spec))
        return ""
    if not is_url and cid in _all_ids(_rows(ctx)):
        raise BDScriptError(f"duplicate button ID '{cid}'")
    _place(ctx, spec, spec.new_row)
    return ""


def _append(rows, spec):
    if spec.new_row and rows[-1]:
        rows.append([])
    if len(rows[-1]) >= 5:
        rows.append([])
    rows[-1].append(spec)


@fn("addActionRow", brackets="optional")
def _addrow(ctx, *a):
    """D.js-BDscript: start a new row."""
    if ctx.response.rows[-1]:
        ctx.response.rows.append([])
    return ""


@fn("editButton", min_args=3, brackets="required")
async def _editbutton(ctx, cid, label, style, disabled="no", emoji="", message_id=""):
    def apply(rows):
        b = _find(rows, cid)
        if b is None:
            raise BDScriptError(f"no button '{cid}'")
        b.label, b.style, b.disabled, b.emoji = label, style.strip().lower() or b.style, truthy(disabled, False), emoji or None
    mid = message_id.strip() or _interaction_message_id(ctx)
    if mid:
        await ctx.bot.edit_components(ctx, mid, apply)
    else:
        apply(_rows(ctx))
    return ""


def _interaction_message_id(ctx):
    m = getattr(ctx.interaction, "message", None)
    return str(m.id) if m is not None else ""


@fn("removeButtons")
@fn("removeButtonsComplex")
async def _removebuttons(ctx, message_id=""):
    mid = message_id.strip() or _interaction_message_id(ctx)
    if mid:
        await ctx.bot.edit_components(ctx, mid, lambda rows: rows.__setitem__(slice(None), [[i for i in r if not isinstance(i, ButtonSpec)] for r in rows]))
    else:
        ctx.response.rows = [[i for i in r if not isinstance(i, ButtonSpec)] for r in ctx.response.rows] or [[]]
    return ""


@fn("removeAllComponents")
@fn("removeAllComponentsComplex")
async def _removeall(ctx, message_id=""):
    mid = message_id.strip() or _interaction_message_id(ctx)
    if mid:
        await ctx.bot.edit_components(ctx, mid, lambda rows: rows.__setitem__(slice(None), [[]]))
    else:
        ctx.response.rows = [[]]
    return ""


@fn("removeComponent", min_args=1, brackets="required")
async def _removecomponent(ctx, cid, message_id=""):
    def apply(rows):
        rows[:] = [[i for i in r if getattr(i, "custom_id", None) != cid and getattr(i, "url", None) != cid] for r in rows]
    mid = message_id.strip() or _interaction_message_id(ctx)
    if mid:
        await ctx.bot.edit_components(ctx, mid, apply)
    else:
        apply(ctx.response.rows)
    return ""


@fn("newSelectMenu", min_args=3, brackets="required")
async def _newselect(ctx, cid, mn, mx, placeholder="", message_id=""):
    spec = SelectSpec(custom_id=cid, placeholder=placeholder, min_values=to_int(mn), max_values=to_int(mx))
    if message_id.strip():
        await ctx.bot.edit_components(ctx, message_id.strip(), lambda rows: rows.append([spec]))
        return ""
    if ctx.response.rows[-1]:
        ctx.response.rows.append([])
    ctx.response.rows[-1].append(spec)
    ctx.response.rows.append([])
    return ""


def _select(rows, cid):
    s = _find(rows, cid)
    if not isinstance(s, SelectSpec):
        raise BDScriptError(f"no select menu '{cid}'")
    return s


@fn("addSelectMenuOption", min_args=3, brackets="required")
async def _addoption(ctx, cid, label, value, description="", default="no", emoji="", message_id=""):
    opt = {"label": label, "value": value, "description": description or None, "default": truthy(default, False),
           "emoji": emoji or None}
    mid = message_id.strip()
    if mid:
        await ctx.bot.edit_components(ctx, mid, lambda rows: _select(rows, cid).options.append(opt))
    else:
        s = _select(ctx.response.rows, cid)
        if len(s.options) >= 25:
            raise BDScriptError("a select menu can have at most 25 options")
        s.options.append(opt)
    return ""


@fn("editSelectMenu", min_args=3, brackets="required")
async def _editselect(ctx, cid, mn, mx, placeholder="", message_id=""):
    def apply(rows):
        s = _select(rows, cid)
        s.min_values, s.max_values, s.placeholder = to_int(mn), to_int(mx), placeholder or s.placeholder
    mid = message_id.strip() or _interaction_message_id(ctx)
    await (ctx.bot.edit_components(ctx, mid, apply) if mid else _sync(apply, ctx.response.rows))
    return ""


async def _sync(f, rows):
    f(rows)


@fn("editSelectMenuOption", min_args=3, brackets="required")
async def _editoption(ctx, cid, label, value, description="", default="no", emoji="", message_id=""):
    def apply(rows):
        for r in rows:
            for item in r:
                if isinstance(item, SelectSpec):
                    for o in item.options:
                        if o["value"] == value or (item.custom_id == cid and o["label"] == label):
                            o.update(label=label, value=value, description=description or None,
                                     default=truthy(default, False), emoji=emoji or None)
                            return
        raise BDScriptError(f"no select option '{value}'")
    mid = message_id.strip() or _interaction_message_id(ctx)
    await (ctx.bot.edit_components(ctx, mid, apply) if mid else _sync(apply, ctx.response.rows))
    return ""


@fn("newModal", min_args=2, brackets="required")
def _newmodal(ctx, cid, title):
    ctx.response.modal = ModalSpec(custom_id=cid, title=title)
    return ""


@fn("addTextInput", min_args=3, brackets="required")
def _addtextinput(ctx, cid, style, label, mn="", mx="", required="yes", value="", placeholder=""):
    if ctx.response.modal is None:
        raise BDScriptError("use $newModal first")
    if style.strip().lower() not in ("short", "paragraph", "long"):
        raise BDScriptError(f"invalid text input style '{style}' (short/paragraph)")
    ctx.response.modal.inputs.append({"id": cid, "style": style.strip().lower(), "label": label,
                                      "min": to_int(mn) if mn.strip() else None, "max": to_int(mx) if mx.strip() else None,
                                      "required": truthy(required, True), "value": value, "placeholder": placeholder})
    return ""


@fn("input", min_args=1, brackets="required")
def _input(ctx, cid):
    return str((ctx.extras.get("inputs") or {}).get(cid, ""))


@fn("customID", brackets="none")
@fn("interactionID", brackets="none")
def _customid(ctx):
    return ctx.extras.get("custom_id", "")


@fn("selectMenuValues", brackets="optional")
@fn("interactionValues", brackets="optional")
def _values(ctx, sep=", "):
    return (sep or ", ").join(ctx.extras.get("values") or [])


@fn("isSlash", brackets="none")
def _isslash(ctx):
    return bool(ctx.extras.get("slash"))


@fn("slashOption", min_args=1, brackets="required")
def _slashoption(ctx, name):
    return str((ctx.extras.get("options") or {}).get(name, ""))


@fn("slashID")
@fn("slashIDComplex")
def _slashid(ctx, name=""):
    n = name.strip() or ctx.extras.get("slash_name", "")
    return n  # Vector slash commands are identified by name


@fn("slashCommandsCount", brackets="none")
def _slashcount(ctx):
    return str(len(ctx.bot.slash_commands))


@fn("registerGuildCommands")
@fn("registerGuildCommandsComplex")
@fn("createSlashCommand", status="partial", note="Vector slash commands are bot-wide; the server argument is accepted")
def _register(ctx, *names):
    """Publish slash commands (Vector's `/` picker is bot-wide, so the guild part is accepted and ignored)."""
    names = [n for n in names if n.strip()]
    if names and len(names) >= 2 and (names[0].lower() == "global" or names[0].isdigit() or len(names[0]) == 64):
        names = names[1:]  # fork: $createSlashCommand[global|guildID;name]
    ctx.bot.publish_slash(names or None)
    return ""


@fn("unregisterGuildCommands")
@fn("unregisterGuildCommandsComplex")
def _unregister(ctx, *names):
    ctx.bot.unpublish_slash([n for n in names if n.strip()] or None)
    return ""
