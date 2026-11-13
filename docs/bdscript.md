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

## Inside a regular bot (discord.py style)

You don't need a `BDBot` to use BDScript. `BDScript` attaches to a bot you already have (`vector.Client` or
`commands.Bot`). It only adds extra listeners, so your own `on_message` and commands keep working.

```python
from vector.ext import commands
from vector.ext.bdscript import BDScript, BDScriptError

bot = commands.Bot(command_prefix="!")
bd = BDScript(bot)                     # BDScript(bot, listen=False) hooks no events at all: library mode

# BDScript as real discord.py-style commands (aliases, help and the "/" picker work); words after the
# command are $message[1], $message[2]...
bd.add_command("balance", "$nomention You have $getUserVar[money] coins.")
bd.add_command("shout", "$toUpperCase[$message]!", aliases=["yell"])

@bot.command()
async def hello(ctx):
    result = await bd.run("Hi $username! $title[Hello]$description[From BDScript]", ctx)   # sends the reply
    print(result.text, result.embeds, result.ok)

@bot.command()
async def quiet(ctx):
    r = await bd.run("$sum[2;3]", ctx, send=False)        # don't send, just inspect
    await ctx.send(f"5? {r.text == '5'}")
```

`run(code, ctx=None, *, send=None, args=None, vars=None, message=, channel=, author=, guild=)` is async and
returns a `Result`:

| field | meaning |
|---|---|
| `text` / `str(result)` | the final text (with BDFD-style error text if the script failed) |
| `ok`, `failure` | `False` plus the message when a function errored or a `$onlyIf`/`$argsCheck` guard failed |
| `embeds`, `rows`, `reactions`, `files` | what the script queued: `vector.Embed` objects, button/select rows, ... |
| `sent` | ids of messages the script sent itself (`$sendMessage`...) |
| `context` | the BDScript `Context`, for the curious |

`ctx` can be a `commands.Context`, a `Message` or a channel. Without one, give `channel=`/`author=`, or nothing at
all for pure computation. By default the reply is sent when there is a channel to send to.

Evaluate without sending anything:

```python
text = await bd.evaluate_async("$calculate[6*7] $toTitleCase[a b]")     # "42 A B"
text = bd.evaluate("$sum[2;3]")                                         # sync, for scripts/REPLs/tests
await bd.run("$getVar[money] / $message[1]", args="3", vars={"x": 1}, send=False)
```

### Teach BDScript new functions in Python

```python
@bd.function("shout")
def shout(ctx, text=""):                   # strings in, a string out; async works too
    if not text:
        raise BDScriptError("nothing to shout")      # shows as a normal function error
    return text.upper() + "!"
# BDScript:  $shout[hello]  ->  HELLO!
```

Registered functions are process-wide, so they work in every engine and in `.bds` files.

### Drop-in cog

`bot.load_extension("vector.ext.bdscript.cog")` adds owner-only `!bd eval <code>`, `!bd check <code>` and
`!bd functions [filter]`, and sets `bot.bd` to the engine.

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
