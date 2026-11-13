"""Vector-only functions: things the Vector SDK can do that BDScript has no function for.

npubs and profiles, Mini Apps, community admins, private/read-only channels, disappearing and hidden messages,
blocking, emoji packs, image hosting, relays, raid containment, and ``$community...`` names for the ``$server...``
functions.
"""

from __future__ import annotations

import datetime
import os
import tempfile

from ..parser import escape
from ..registry import FUNCTIONS, BDScriptError, alias, fn
from ..util import get_channel, get_guild, get_member, get_user, seconds, strip_mention, truthy


# -- identity & profiles -----------------------------------------------------------------------------------
@fn("npub")
def _npub(ctx, uid=""):
    u = get_user(ctx, uid)
    return getattr(u, "npub", "") or str(u.id)


@fn("authorNpub", brackets="none")
def _authornpub(ctx):
    return getattr(ctx.author, "npub", "") or ctx.author_id


@fn("botNpub", brackets="none")
def _botnpub(ctx):
    return ctx.client.npub or ""


@fn("isNpub", min_args=1, brackets="required")
def _isnpub(ctx, text):
    t = strip_mention(text)
    return t.startswith("npub1") and len(t) == 63


@fn("userAbout")
def _userabout(ctx, uid=""):
    return escape(getattr(get_user(ctx, uid), "about", "") or "")


@fn("isDM", brackets="none")
def _isdm(ctx):
    return ctx.guild is None


@fn("setBotName", min_args=1, brackets="required")
async def _setbotname(ctx, name):
    await ctx.client.user.edit(username=name)
    return ""


@fn("setBotAbout", min_args=1, brackets="required")
async def _setbotabout(ctx, *text):
    await ctx.client.user.edit(about=";".join(text))
    return ""


@fn("setBotAvatar", min_args=1, brackets="required")
async def _setbotavatar(ctx, url):
    await ctx.client.user.edit(avatar=url.strip())
    return ""


@fn("setBotBanner", min_args=1, brackets="required")
async def _setbotbanner(ctx, url):
    await ctx.client.user.edit(banner=url.strip())
    return ""


@fn("setBotStatus", min_args=0, brackets="required")
async def _setbotstatus(ctx, *text):
    await ctx.client.set_status(";".join(text))
    return ""


@fn("blockUser", min_args=1, brackets="required")
async def _block(ctx, uid):
    await ctx.client.block(get_user(ctx, uid, required=False) or strip_mention(uid))
    return ""


@fn("unblockUser", min_args=1, brackets="required")
async def _unblock(ctx, uid):
    await ctx.client.unblock(get_user(ctx, uid, required=False) or strip_mention(uid))
    return ""


@fn("setLocalNickname", min_args=2, brackets="required")
async def _localnick(ctx, uid, nick):
    await ctx.client.set_local_nickname(get_user(ctx, uid, required=False) or strip_mention(uid), nick)
    return ""


# -- messages ----------------------------------------------------------------------------------------------
@fn("expireIn", min_args=1, brackets="required")
@fn("disappearIn", min_args=1, brackets="required")
def _expirein(ctx, duration):
    """Make the response a disappearing message (deleted for everyone after ``duration``)."""
    ctx.response.expires_in = seconds(duration)
    return ""


@fn("hideMessage")
async def _hide(ctx, cid="", mid=""):
    """Hide a message for the bot only (``$deleteMessage`` deletes it for everyone)."""
    from .messages import _target_msg
    msg = await _target_msg(ctx, cid, mid)
    await msg.hide()
    return ""


@fn("sendMiniApp", min_args=1, brackets="required")
@fn("sendXdc", min_args=1, brackets="required")
async def _sendxdc(ctx, source, cid="", return_id="no"):
    """Share a Mini App (``.xdc``): a file path (if ``BDBot(allow_files=True)``), a URL, or a name registered
    with ``bot.mini_apps``."""
    path = ctx.bot.mini_apps.get(source.strip())
    if path is None and source.startswith(("http://", "https://")):
        import urllib.request
        fd, path = tempfile.mkstemp(suffix=".xdc")
        with os.fdopen(fd, "wb") as f, urllib.request.urlopen(source.strip(), timeout=20) as r:
            f.write(r.read(50 * 1024 * 1024))
    if path is None and getattr(ctx.bot, "allow_files", False) and os.path.isfile(source.strip()):
        path = source.strip()
    if path is None:
        raise BDScriptError(f"unknown Mini App '{source}' (register it: bot.mini_apps['name'] = 'app.xdc')")
    app = await get_channel(ctx, cid).send_xdc(path)
    return str(getattr(app, "message_id", "") or "") if truthy(return_id) else ""


@fn("uploadImage", min_args=1, brackets="required")
async def _uploadimage(ctx, source):
    """Host an image (URL, or the Nth attachment of the message) on Vector's file server; returns its URL."""
    src = source.strip()
    data = None
    if src.isdigit():
        atts = list(getattr(ctx.message, "attachments", []) or [])
        i = int(src)
        if not 0 < i <= len(atts):
            raise BDScriptError(f"no attachment {i}")
        data = await atts[i - 1].read()
    elif src.startswith(("http://", "https://")):
        import urllib.request
        with urllib.request.urlopen(src, timeout=20) as r:
            data = r.read(25 * 1024 * 1024)
    else:
        raise BDScriptError("give an image URL or an attachment number")
    fd, path = tempfile.mkstemp(suffix=".png")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    try:
        return await ctx.client.upload_image(path)
    finally:
        os.unlink(path)


# -- communities -------------------------------------------------------------------------------------------
@fn("joinCommunity", min_args=1, brackets="required")
async def _join(ctx, invite, return_id="yes"):
    g = await ctx.client.join(invite.strip())
    return str(g.id) if truthy(return_id, True) else ""


@fn("createCommunity", min_args=1, brackets="required")
async def _createcommunity(ctx, name, description="", first_channel="", return_id="yes"):
    g = await ctx.client.create_community(name, description=description or None, first_channel=first_channel or None)
    return str(g.id) if truthy(return_id, True) else ""


@fn("pendingInvites", brackets="optional")
def _pending(ctx, sep=", "):
    return (sep or ", ").join(str(getattr(p, "community_id", getattr(p, "id", ""))) for p in ctx.client.pending_invites())


@fn("acceptInvite", min_args=1, brackets="required")
async def _accept(ctx, cid):
    await ctx.client.accept_invite(cid.strip())
    return ""


@fn("grantAdmin", min_args=1, brackets="required")
async def _grantadmin(ctx, uid):
    await get_member(ctx, uid).grant_admin()
    return ""


@fn("revokeAdmin", min_args=1, brackets="required")
async def _revokeadmin(ctx, uid):
    await get_member(ctx, uid).revoke_admin()
    return ""


@fn("communityRelays", brackets="optional")
@fn("relays", brackets="optional")
def _relays(ctx, sep=", ", gid=""):
    return (sep or ", ").join(get_guild(ctx, gid).relays)


@fn("containRaid", min_args=2, brackets="required")
async def _containraid(ctx, window, *uids):
    """Remove raiders and undo their messages from the last ``window`` (e.g. ``10m``)."""
    g = get_guild(ctx)
    users = [get_member(ctx, u, required=False) or strip_mention(u) for u in uids if u.strip()]
    await g.contain_raid(users, window=datetime.timedelta(seconds=seconds(window)))
    return ""


# -- channels ----------------------------------------------------------------------------------------------
@fn("grantChannelAccess", min_args=2, brackets="required")
async def _grantaccess(ctx, cid, uid):
    await get_channel(ctx, cid).grant_access(get_member(ctx, uid))
    return ""


@fn("revokeChannelAccess", min_args=2, brackets="required")
async def _revokeaccess(ctx, cid, uid):
    await get_channel(ctx, cid).revoke_access(get_member(ctx, uid))
    return ""


@fn("setChannelPrivate", min_args=2, brackets="required")
async def _private(ctx, cid, value):
    await get_channel(ctx, cid).edit(private=truthy(value))
    return ""


@fn("setChannelReadOnly", min_args=2, brackets="required")
async def _readonly(ctx, cid, value):
    await get_channel(ctx, cid).edit(read_only=truthy(value))
    return ""


@fn("isReadOnly")
def _isreadonly(ctx, cid=""):
    c = get_channel(ctx, cid)
    return bool(getattr(c, "read_only", False))


# -- emoji packs -------------------------------------------------------------------------------------------
@fn("subscribeEmojiPack", min_args=1, brackets="required")
async def _subpack(ctx, naddr):
    await ctx.client.subscribe_emoji_pack(naddr.strip())
    return ""


@fn("unsubscribeEmojiPack", min_args=1, brackets="required")
async def _unsubpack(ctx, naddr):
    await ctx.client.unsubscribe_emoji_pack(naddr.strip())
    return ""


@fn("emojiPacks", brackets="optional")
def _packs(ctx, sep=", "):
    return (sep or ", ").join(str(p.get("name") or p.get("id") or "") for p in ctx.client.emoji_packs())


@fn("botEmojis", brackets="optional")
def _botemojis(ctx, sep=" "):
    return (sep or " ").join(str(e) for e in ctx.client.emojis)


# -- $community... names for the $server... functions ------------------------------------------------------
def register_aliases() -> None:
    pairs = {
        "communityID": "guildID", "communityName": "serverName", "communityIcon": "serverIcon",
        "communityOwner": "serverOwner", "communityDescription": "serverDescription",
        "communityMembersCount": "membersCount", "communityCount": "serverCount", "communityExists": "guildExists",
        "communityNames": "serverNames", "communityInvite": "getServerInvite", "leaveCommunity": "botLeave",
        "communityInfo": "serverInfo", "communityEmojis": "serverEmojis", "communityChannelExists": "serverChannelExists",
        "randomCommunityID": "randomGuildID", "communityBanner": "guildBanner",
        "setCommunityVar": "setServerVar", "getCommunityVar": "getServerVar", "resetCommunityVar": "resetServerVar",
        "communityLeaderboard": "serverLeaderboard", "communityCooldown": "serverCooldown",
        "onlyForCommunities": "onlyForServers", "blackListCommunities": "blackListServers",
    }
    for new, old in pairs.items():
        if new.lower() not in FUNCTIONS:
            alias(new, old)
