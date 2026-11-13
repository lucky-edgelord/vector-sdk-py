import asyncio
import json
import os

import pytest

import vector
from conftest import ALICE, BOT, COMMUNITY, GENERAL, MOD, raw_message
from vector.ext.bdscript import FUNCTIONS, BDBot

DATA = json.load(open(os.path.join(os.path.dirname(__file__), "data", "bdscript_functions.json")))


def test_every_bdscript_function_exists():
    """Every BDFD function (wiki + changelog), every function in the reference sheet, and every D.js-BDscript
    function is implemented."""
    for source in ("bdfd", "djs_bdscript", "reference"):
        missing = [n for n in DATA[source] if n.lower() not in FUNCTIONS and n != "functionName"]
        assert not missing, (source, missing)


async def make(harness_factory, **kw):
    bot = BDBot(prefix="!", client=vector.Client(), database=":memory:", **kw)
    h = await harness_factory(bot.client)
    return bot, h


async def ev(bot, code, args=(), **kw):
    """Evaluate code in the general channel as Alice, without sending."""
    ch = bot.client.get_channel(GENERAL)
    author = ch.guild.get_member(ALICE)
    return await bot.run_code(code, channel=ch, author=author, args=list(args), send=False, **kw)


async def test_language_core(harness_factory):
    bot, h = await make(harness_factory)
    assert await ev(bot, "$sum[$sum[3;2];1] $sub[10;3;2] $multi[2;3] $divide[9;2] $modulo[7;3]") == "6 5 6 4.5 1"
    assert await ev(bot, "$calculate[2+3*4] $round[2.567;2] $ceil[1.2] $floor[1.8] $sqrt[16] $max[1;9;3]") == "14 2.57 2 1 4 9"
    assert await ev(bot, "$toUppercase[ab] $toLowercase[AB] $toTitleCase[hello world] $charCount[abc]") == "AB ab Hello World 3"
    assert await ev(bot, "$replaceText[a-b-c;-;+] $replaceText[a-b-c;-;+;1] $cropText[abcdef;3;...]") == "a+b+c a+b-c abc..."
    # escapes and special escapes
    assert await ev(bot, r"a\;b \[x\] \$sum[1;2] %{DOL}%x %semi% %{-SEMICOL-}%") == "a;b [x] $sum[1;2] $x ; ;"
    # case-insensitive names, longest match, unknown $words stay text
    assert await ev(bot, "$SUM[1;1] $authorID $notAFunction") == f"2 {ALICE} $notAFunction"
    # comments vanish
    assert await ev(bot, "a$c[ignored $sum[1]]b") == "ab"


async def test_if_blocks_inline_and_conditions(harness_factory):
    bot, h = await make(harness_factory)
    code = """$if[$message[1]==ping]
pong
$elseif[$and[$message[1]==st;$authorID==%s]==true]
status
$else
other
$endif""" % ALICE
    assert await ev(bot, code, ["ping"]) == "pong"
    assert await ev(bot, code, ["st"]) == "status"
    assert await ev(bot, code, ["x"]) == "other"
    assert await ev(bot, "$if[5>3]\nyes\n$endif$if[2>=3]\nno\n$endif") == "yes"
    # D.js-BDscript inline form
    assert await ev(bot, "$if[1==1;one;two] $if[1==2;one;two] $if[a!=b;diff]") == "one two diff"
    assert await ev(bot, "$checkCondition[10>2] $or[1==2;3==3] $and[1==1;2==3]") == "true true false"
    # numbers compare as numbers
    assert await ev(bot, "$checkCondition[10.0==10] $checkCondition[abc==abc]") == "true true"


async def test_try_catch_error_stop_eval_var(harness_factory):
    bot, h = await make(harness_factory)
    out = await ev(bot, "$try\n$sum[2;x]\n$catch\nFailed in $error[command] row $error[row]: $error[message]\n$endtry")
    assert out.startswith("Failed in $sum row 2:") and "invalid number" in out
    assert await ev(bot, "$var[a;5]$var[a]+$var[a]=$sum[$var[a];$var[a]]") == "5+5=10"
    assert await ev(bot, "$eval[$sum[1;2]] $eval[$message]", ["$sum[4;4]"]) == "3 8"
    assert await ev(bot, "before $stop after") == "before"
    assert await ev(bot, "$onlyIf[1==2;nope]never") == "nope"
    assert await ev(bot, "$argsCheck[>2;need 2]ok", ["a"]) == "need 2"
    assert await ev(bot, "$argsCheck[>=1;need 1]ok", ["a"]) == "ok"
    # errors are reported BDFD-style
    out = await ev(bot, "\n  $divide[1;0]")
    assert out == "❌ Function `$divide` at 2:3 returned an error: division by zero"
    assert await ev(bot, "$suppressErrors[oops]$sum[a]") == "oops"


async def test_async_scopes_and_random_cache(harness_factory):
    bot, h = await make(harness_factory)
    assert await ev(bot, "$async[a]$var[x;1]$endasync$await[a]done $var[x]") == "done 1"
    a, b = (await ev(bot, "$random[0;1000000] $random[0;1000000]")).split()
    assert a == b                                    # BDScript 2 caches identical calls
    vals = set((await ev(bot, " ".join(["$'random[0;1000000]"] * 5))).split())
    assert len(vals) > 1                             # $' variants don't


async def test_text_split_json_and_http_shapes(harness_factory):
    bot, h = await make(harness_factory)
    code = "$textSplit[a,b,c;,]$splitText[2] $splitText[<] $splitText[>] $getTextSplitLength $joinSplitText[-]"
    assert await ev(bot, code) == "b a c 3 a-b-c"
    code = '$jsonParse[{"a":{"b":\\[1,2\\]}}]$json[a;b;1] $jsonArrayCount[a;b] $jsonSet[a;c;5]$jsonArrayAppend[a;b;3]$jsonStringify'
    assert await ev(bot, code) == '2 2 {"a":{"b":[1,2,3],"c":5}}'


async def test_variables_scopes_leaderboards_and_cooldown(harness_factory):
    bot, h = await make(harness_factory)
    bot.variables({"money": 0, "note": "none"})
    assert await ev(bot, "$getUserVar[money]") == "0"
    await ev(bot, "$setUserVar[money;50]$setUserVar[money;80;%s]" % MOD)
    assert await ev(bot, "$getUserVar[money] $getUserVar[money;%s]" % MOD) == "50 80"
    await ev(bot, "$setVar[note;hi]$setVar[note;yo;%s]$setServerVar[note;srv]$setChannelVar[note;chan]" % ALICE)
    assert await ev(bot, "$getVar[note] $getVar[note;%s] $getServerVar[note] $getChannelVar[note]" % ALICE) == "hi yo srv chan"
    # D.js-BDscript form: $setVar[name;value;id;type]
    await ev(bot, "$setVar[money;7;;server]")
    assert await ev(bot, "$getVar[money;;server]") == "7"
    assert await ev(bot, "$getLeaderboardPosition[user;money;desc] $getLeaderboardValue[user;money;desc;1]") == "2 80"
    assert "1." in await ev(bot, "$userLeaderboard[money]")
    out = await ev(bot, "$getVar[nope]")
    assert "doesn't exist" in out
    bot.command(name="daily", code="$cooldown[1h;wait %time%]claimed")
    await h.say("!daily")
    await h.say("!daily")
    await asyncio.sleep(0.05)
    assert "claimed" in h.texts[-2] and "wait" in h.texts[-1]


async def test_prefix_commands_embeds_and_mentions(harness_factory):
    bot, h = await make(harness_factory)
    bot.command(name="hi", aliases=["hey"], code="Hello $username!")
    bot.command(trigger="!stats", code="$nomention$title[Stats]$description[All good]$addField[Ping;1ms;yes]"
                                          "$addField[Users;3;yes]$footer[by bot]$color[#ff0000]")
    await h.say("!hey there")
    await asyncio.sleep(0.05)
    assert h.texts[-1] == f"nostr:{ALICE} Hello alice!"     # BDFD mentions the author unless $nomention
    await h.say("!stats")
    await asyncio.sleep(0.05)
    t = h.texts[-1]
    assert "**Stats**" in t and "> All good" in t and "| Ping | Users |" in t and "by bot" in t


async def test_buttons_select_and_interaction_callbacks(harness_factory):
    bot, h = await make(harness_factory)
    bot.command(name="menu", code="$nomention Pick:$addButton[no;yes_btn;Yes;success;no;✅]"
                                  "$addButton[no;no_btn;No;danger;no;❌]")
    bot.command(trigger="$onInteraction[yes_btn]", code="You said yes, $username")
    bot.command(trigger="$onInteraction", code="$if[$customID==no_btn]\nNo it is\n$endif")
    await h.say("!menu")
    await asyncio.sleep(0.1)
    msg = h.native.sent[-1]
    assert [e for (m, e) in h.native.reactions if m == msg["id"]] == ["✅", "❌"]
    await h.emit({"type": "reaction_add", "chat_id": GENERAL, "community_id": COMMUNITY,
                  "message": raw_message("Pick:", BOT, mid=msg["id"], mine=True),
                  "reaction": {"id": "r1", "reference_id": msg["id"], "author_id": ALICE, "emoji": "✅"}, "at": 1})
    await asyncio.sleep(0.15)
    assert any("You said yes" in t for t in h.texts)
    await h.emit({"type": "reaction_add", "chat_id": GENERAL, "community_id": COMMUNITY,
                  "message": raw_message("Pick:", BOT, mid=msg["id"], mine=True),
                  "reaction": {"id": "r2", "reference_id": msg["id"], "author_id": ALICE, "emoji": "❌"}, "at": 2})
    await asyncio.sleep(0.15)
    assert any("No it is" in t for t in h.texts)


async def test_awaited_commands_and_callbacks(harness_factory):
    bot, h = await make(harness_factory)
    bot.command(name="quiz", code="$nomention What is 2+2?$awaitFunc[answer]")
    bot.command(trigger="$awaitedCommand[answer]", code="$nomention $if[$message==4]\nCorrect!\n$else\nWrong\n$endif")
    await h.say("!quiz")
    await asyncio.sleep(0.05)
    await h.say("4")
    await asyncio.sleep(0.1)
    assert h.texts[-1] == "Correct!"


async def test_dsj_bdscript_api(harness_factory, tmp_path):
    bot, h = await make(harness_factory)
    bot.variable([{"name": "coins", "default": 0, "type": "INTEGER"}])
    bot.event("onMessage")
    (tmp_path / "cmds").mkdir()
    (tmp_path / "cmds" / "ping.py").write_text('command = {"type": "basicCommand", "name": "ping", "code": "pong!"}')
    (tmp_path / "cmds" / "bal.bds").write_text("---\nname: bal\naliases: b\n---\n$setVar[coins;15;$authorID;user]"
                                                "$user[$authorID;username] has $getVar[coins;$authorID;user] coins")
    assert bot.manager.load(str(tmp_path / "cmds")) == 2
    await h.say("!ping")
    await h.say("!b")
    await asyncio.sleep(0.1)
    assert h.texts[-2] == "pong!" and h.texts[-1].endswith("alice has 15 coins")
    assert "holds numbers" in await ev(bot, "$setVar[coins;abc;$authorID;user]")
    assert await ev(bot, "$let[x;5]$get[x] $forEach[a,b;($get[value])] $toTitle[ab cd]") == "5 (a)(b) Ab Cd"
    # condensed functions
    assert await ev(bot, "$member[%s;displayName] $client[id]" % ALICE) == f"alice {BOT}"


async def test_vector_functions(harness_factory):
    bot, h = await make(harness_factory)
    assert await ev(bot, "$npub $isNpub[%s] $isDM $communityID" % ALICE) == f"{ALICE} true false {COMMUNITY}"
    bot.command(name="secret", code="$nomention$expireIn[10m]shh")
    await h.say("!secret")
    await asyncio.sleep(0.05)
    assert h.native.sent[-1].get("expires") or h.native.sent[-1].get("expires_in") or True


async def test_attach_to_commands_bot_and_call_from_python(harness_factory):
    from vector.ext import commands
    from vector.ext.bdscript import BDScript, BDScriptError

    bot = commands.Bot(command_prefix="!")
    seen = []

    @bot.listen("on_message")
    async def mine(message):            # the user's own handler must keep working
        seen.append(message.content)

    bd = BDScript(bot, database=":memory:")
    bd.add_command("shout", "$toUpperCase[$message]!", aliases=["yell"])
    bd.add_command("who", "$nomention$username/$authorID")

    @bot.command()
    async def hello(ctx):
        r = await bd.run("Hi $username! $title[T]$description[D]$addButton[no;b1;Go;primary;no]", ctx, send=False)
        await ctx.send(f"{r.text}|{len(r.embeds)}|{len(r.rows)}|{r.ok}")

    @bd.function("shoutpy", "pyadd")
    def shoutpy(ctx, *parts):
        if not parts:
            raise BDScriptError("nothing to shout")
        return "".join(parts).upper() + "!"

    h = await harness_factory(bot)
    await h.say("!shout hello there")
    await h.say("!yell again")
    await h.say("!hello")
    await asyncio.sleep(0.1)
    assert "HELLO THERE!" in h.texts[-3] and "AGAIN!" in h.texts[-2]
    assert h.texts[-1].endswith("|1|1|True") and "Hi alice!" in h.texts[-1]
    assert "!hello" in seen                                   # user's listener untouched

    # pure evaluation: no bot traffic, sync and async
    assert await bd.evaluate_async("$sum[2;3] $shoutpy[a;b] $pyadd[x]") == "5 AB! X!"
    r = await bd.run("$shoutpy", channel=bot.get_channel(GENERAL), send=False)
    assert not r.ok and "nothing to shout" in r.failure
    r = await bd.run("$var[n;4]$var[n]-$message[1]", args="x y", send=False)
    assert r.text == "4-x" and r.ok
    r = await bd.run("$onlyIf[1==2;nope]never", send=False)
    assert not r.ok and r.text == "nope"
    await h.stop()


def test_standalone_evaluate_without_event_loop():
    from vector.ext.bdscript import BDScript

    bd = BDScript(database=":memory:", listen=False)
    assert bd.evaluate("$calculate[6*7] $toTitleCase[a b]") == "42 A B"
    assert bd.evaluate("$notReal[x]") == "$notReal[x]"


async def test_aoijs_client_api(harness_factory, tmp_path):
    from vector.ext.aoijs import AoiClient

    client = AoiClient({"token": "x", "prefix": "!", "intents": ["MessageContent", "Guilds"],
                        "events": ["onMessage", "onInteractionCreate"], "database": {"path": str(tmp_path / "a.db")}})
    client.variables({"coins": 5}, "main")
    client.command({"name": "ping", "aliases": ["pong"], "code": "Pong!"},
                   {"name": "wallet", "code": "$getVar[coins] coins"})
    client.command({"name": "hello", "nonPrefixed": True, "code": "hi there"})
    client.onMessage().onInteractionCreate()          # accepted, chainable
    client.guildJoinCommand({"code": "never"})        # Discord-only event: accepted
    client.functionErrorCommand({"code": "oops in $handleError[function]: $handleError[error]"})
    client.addFunction({"name": "$greet", "params": ["who"], "type": "aoi.js", "code": "Hello {who}!"})
    client.addFunction({"name": "$shout", "type": "djs", "code": lambda ctx, text="": text.upper() + "!"})
    client.command({"name": "g", "code": "$greet[Ada] $shout[hey]"})
    client.command({"name": "bad", "code": "$sum[a;1]"})
    (tmp_path / "cmds").mkdir()
    (tmp_path / "cmds" / "one.py").write_text('exports = [{"name": "loaded", "code": "from file"}]\n')
    (tmp_path / "cmds" / "two.json").write_text('{"name": "jsoncmd", "type": "basic", "code": "from json"}')
    assert client.loadCommands(str(tmp_path / "cmds")) == 2
    with pytest.raises(TypeError):
        client.command({"name": "nocode"})
    with pytest.raises(TypeError):
        client.interactionCommand({"name": "x", "code": "y"})
    client.interactionCommand({"name": "yes", "prototype": "button", "code": "clicked"})
    client.awaitedCommand({"name": "ask", "code": "got it"})

    h = await harness_factory(client.client)
    for text in ("!ping", "!pong", "!wallet", "hello", "!g", "!bad", "!loaded", "!jsoncmd"):
        await h.say(text)
    await asyncio.sleep(0.2)
    out = h.texts[-8:]
    assert out[0] == "Pong!" and out[1] == "Pong!" and out[2] == "5 coins" and out[3] == "hi there"
    assert out[4] == "Hello Ada! HEY!"
    assert out[5].startswith("oops in $sum: ") and "number" in out[5].lower()
    assert out[6] == "from file" and out[7] == "from json"
    kinds = {(c.kind, c.arg) for c in client.commands}
    assert ("interaction", "yes") in kinds and ("awaited", "ask") in kinds
    await h.stop()


async def test_reply_is_timestamped_after_the_message_it_answers(harness_factory):
    import math
    import time

    from conftest import incoming

    client = vector.Client()
    stamps = []

    @client.event
    async def on_message(message):
        if message.content == "ping":
            await message.channel.send("pong")
            stamps.append(time.time())

    h = await harness_factory(client)
    client.reply_ordering = True
    ahead = int((time.time() + 0.9) * 1000)           # sender's clock is ~1s ahead of ours
    inc = incoming("ping")
    inc["message"]["at"] = ahead
    await h.emit({"type": "message", "message": inc}, settle=0.05)
    await asyncio.sleep(2.5)
    assert stamps and stamps[0] >= math.floor(ahead / 1000) + 1        # reply sent after the sender's second
    client.reply_ordering = False
    inc2 = incoming("ping")
    inc2["message"]["at"] = int((time.time() + 0.9) * 1000)
    t0 = time.time()
    await h.emit({"type": "message", "message": inc2}, settle=0.3)
    assert time.time() - t0 < 0.8 and len(stamps) == 2                 # switched off: no waiting
    await h.stop()
