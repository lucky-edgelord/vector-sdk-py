# BDScript on Vector

`vector.ext.bdscript` runs **BDScript 2** (Bot Designer for Discord) and **D.js-BDscript** code on Vector. Every
BDFD function (wiki and changelog), every function in D.js-BDscript, and a set of Vector-only functions are
implemented: see the [function reference](bdscript-functions.md). A test checks the list stays complete.

## Run a bot

```sh
pip install vector-sdk-py
VECTOR_NSEC=nsec1... vector-bdscript run ./my-bot      # files reload when they change
vector-bdscript check ./my-bot                         # syntax-check every command
vector-bdscript functions                              # list functions and their status
```

A bot folder holds one command per file plus an optional `bot.json` (prefix, owners, variables, slash commands).
See [`examples/bdscript`](../examples/bdscript).

```
---
trigger: !daily
---
$nomention
$cooldown[24h;Come back in %time%.]
$setUserVar[money;$sum[$getUserVar[money];100]]
+100 coins! You now have $getUserVar[money].
```

Header keys: `trigger` (a full trigger such as `!ping`, or a callback such as `$onJoined[channelID]`), `name`
(uses the bot prefix), `aliases`, `type` (D.js-BDscript types), `description`. `.json` files and `.py` files with a
`command` dict / `commands` list work too.

## From Python

```python
from vector.ext.bdscript import BDBot

bot = BDBot(prefix="!", owners=["npub1..."])
bot.variables({"money": 0})
bot.command(trigger="!ping", code="$nomention Pong! $ping ms")
bot.command(trigger="$onInteraction[vote_yes]", code="$username voted yes")
bot.slash_command("balance", "Show a balance", [{"name": "user", "type": "USER"}],
                  code="$getUserVar[money;$message[user]]")
bot.manager.load("./commands")
bot.run()                       # key from $VECTOR_NSEC, or bot.run("nsec1...")
```

D.js-BDscript code runs unchanged:

```python
from vector.ext.bdscript import Bot   # same class

bot = Bot(prefix="!")
bot.variable([{"name": "coins", "default": 0, "type": "INTEGER"}])
bot.command({"type": "basicCommand", "name": "coins",
             "code": "$getVar[coins;$authorID;user] coins"})
bot.event("onMessage")
bot.login("nsec1...")
```

The fork's unfinished parts are complete here: all functions, custom prefixes (`BDBot(prefix_variable="prefix")`
reads a per-community `$setServerVar[prefix;?]`), full embeds, the condensed `$user[]`, `$member[]`, `$server[]`,
`$role[]`, `$channel[]`, `$client[]`, buttons and select menus, and music (`$joinVoice`, `$playSong`, queue).

## Language

Everything in BDScript 2: top-to-bottom evaluation, `$if/$elseif/$else/$endif`, `$try/$catch/$error[]/$endtry`,
`$async[name]/$endasync/$await[name]`, `$eval[]`, `$var[]`, `$optOff[]`, `$c[]` comments, `$stop` (sends what's
queued), escapes `\; \[ \] \$ \\` and `%{DOL}%`, `%{-SEMICOL-}%`, `%semi%`, cached `$random` with uncached `$'random`
variants, BDFD error messages (`❌ Function $sum at 2:5 returned an error: ...`), `$suppressErrors`. D.js-BDscript's
inline `$if[condition;then;else]` works too (a `$if` with two or three arguments).

## Callbacks (triggers)

`$onJoined[channel]`, `$onLeave[channel]`, `$onBanAdd`, `$onBanRemove`, `$onMessageDelete`, `$onInteraction` /
`$onInteraction[customID]`, `$awaitedCommand[name]` / `$awaitedCommandError[name]` (with `$awaitFunc`),
`$onAutoComplete[command]`, `$alwaysReply`, `$messageContains[...]`, `$awaitReactions`. D.js-BDscript types:
`basicCommand`, `readyCommand`, `slashCommand`, `buttonCommand`, `musicStartCommand`, `musicEndCommand`.

## How Discord features map to Vector

| BDScript | On Vector |
|---|---|
| Servers, `$guildID`, `$serverName` | Communities (`$communityID`, `$communityName` also work) |
| IDs | 64-hex IDs and `npub`s; mentions `<@id>` are accepted everywhere |
| Embeds | Vector's quote-style embeds (Vector colours) |
| Buttons, select menus | Emoji reactions; buttons without an emoji get 🇦 🇧 🇨 |
| Modals | The bot asks each field in chat, then runs `$onInteraction[modalID]` with `$input[]` |
| `$ephemeral` | Sent to the user's DMs |
| Slash commands | Vector's `/` picker (bot-wide) |
| Custom emoji | Emoji packs (`$subscribeEmojiPack`, `<:name:id>` and `:name:`) |
| Webhooks | `vector.Webhook` (`$webhookCreate`, `$webhookSend`, …) |
| Threads | A channel next to the parent (*partial*) |
| Boosts, HypeSquad, regions, shards, premium | Neutral values (*noop*), so code keeps running |
| `$ai`, `$aiDecide` … | Your model: `BDBot(ai=callable)`, or Anthropic's API with `ANTHROPIC_API_KEY` |
| HTTP | Standard library, 35 s timeout, 5 requests per run (`BDBot(http_limit=...)`) |

## Vector-only functions

`$npub[user]`, `$authorNpub`, `$botNpub`, `$isNpub[text]`, `$userAbout[user]`, `$isDM`,
`$expireIn[duration]` (disappearing reply), `$hideMessage[(channel;message)]`, `$sendMiniApp[name or URL;(channel)]`,
`$uploadImage[URL or attachment #]`, `$joinCommunity[invite]`, `$createCommunity[name;(description)]`,
`$pendingInvites`, `$acceptInvite[id]`, `$grantAdmin[user]`, `$revokeAdmin[user]`, `$communityRelays`,
`$containRaid[window;user;...]`, `$grantChannelAccess[channel;user]`, `$revokeChannelAccess[channel;user]`,
`$setChannelPrivate[channel;yes/no]`, `$setChannelReadOnly[channel;yes/no]`, `$isReadOnly`, `$blockUser`,
`$unblockUser`, `$setLocalNickname`, `$setBotName`, `$setBotAbout`, `$setBotAvatar`, `$setBotBanner`,
`$setBotStatus`, `$subscribeEmojiPack`, `$unsubscribeEmojiPack`, `$emojiPacks`, `$botEmojis`, `$say[text]`
(voice TTS), `$sendDM[user;text]`, and `$community...` names for every `$server...` function.

## Safety switches

`$exec` is off unless `BDBot(allow_exec=True)`; local file paths (for `$attachment`, `$sendMiniApp`, music) need
`allow_files=True`; HTTP can be turned off with `allow_http=False`.
