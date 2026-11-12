# Porting a discord.py bot to Vector

Most bots run unchanged. Three steps:

```sh
pip install vector-sdk-py
vector-port check path/to/your-bot        # find what needs attention (add --fix to repair SQL id columns)
vector-run bot.py                         # run the bot; `import discord` resolves to vector
```

`vector-run` aliases `discord`, `discord.ext.commands`, `.tasks`, `.menus`, `discord.ui`, `discord.utils`,
`discord.errors` and `discord.abc` to this library. To make it permanent, replace `import discord` with
`import vector as discord` (or `import vector.compat; vector.compat.install()` as the first import).

Log in with a Vector bot key instead of a token: `bot.run(os.environ["VECTOR_NSEC"])` (or `bot.run(token)` with
your `nsec1…`).

## What works the same

Decorators and events, `commands.Bot`/`Cog`/`Context`, checks, cooldowns, converters, `wait_for`, `tasks.loop`,
`Embed`, `ui.View`/`Button`/`Select`/`Modal` (as reactions), `ext.menus`, `load_extension`/`add_cog` (sync and
awaited forms), slash-style commands (published to Vector's `/` picker).

## What is different

| Discord | Vector | What to do |
|---|---|---|
| Servers ("guilds") | Communities (`guild` and `community` both work) | nothing |
| Integer snowflake IDs | 64-hex strings and `npub…` keys | keep IDs as `str`; see below |
| Hard-coded IDs (owner, channels) | different values | move them to config; `vector-port` flags them |
| Bot token | `nsec…` secret key | pass it to `bot.run` |
| Embeds | Rendered as Vector markdown (quote bar, table for fields, always Vector's colours) | nothing; colours you set are ignored |
| Buttons, selects | Emoji reactions under the message | nothing; a button without an emoji gets 🇦 🇧 🇨 |
| Threads, webhooks, stages, stickers, polls, Components V2, `FlagConverter` | not in Vector | stubs: the bot starts, using one raises `vector.NotSupportedOnVector` |
| Presence/status, intents | partly ignored | `change_presence` may fail; intents are accepted |
| Several bots in one process | one bot per process | run extra bots as separate processes |

## IDs and databases

Vector IDs are strings, so every place a bot stores a Discord ID needs a text column.

* SQLite is forgiving: a text value in an ordinary `INTEGER` column is stored as text, so many bots just work.
* `INTEGER PRIMARY KEY` is the exception: SQLite requires real integers there and raises `datatype mismatch`.
  Change ID columns to `TEXT PRIMARY KEY`.
* `vector-port check --fix` rewrites ID-shaped columns (`GuildID`, `user_id`, `channel_id`, …) from `INTEGER` to
  `TEXT` in `.sql` files and SQL strings in `.py` files. A plain `id INTEGER PRIMARY KEY` row number is left alone.
* Delete the old database file once, or migrate it, because existing rows hold Discord snowflakes that match nothing
  on Vector.
* Remove `int(...)` around IDs and comparisons with literal integers.

## Troubleshooting

* `ImportError` for a `discord` name: `vector-port check` reports whether it is missing (error) or a stub (warning).
* `NotSupportedOnVector`: the bot used a Discord-only feature; wrap or remove that code path.
* Commands do nothing in DMs or communities: check the bot was invited and, in a community, has the needed role.
* Run `vector-port` again after edits; it exits non-zero while errors remain.
