# aoi.js-style interface

`vector.ext.aoijs` gives vector-sdk-py the API of [aoi.js](https://github.com/aoijs/aoi.js): `AoiClient`,
`client.command({...})`, `readyCommand`, `variables`, `loadCommands`, `addFunction` and friends. The `code` strings
are **BDScript** (see [bdscript.md](bdscript.md)), the same engine as the rest of the SDK, so all of its functions
work inside them. This is the interface, not a port of aoi.js's own function set.

```python
from vector.ext.aoijs import AoiClient

client = AoiClient({
    "prefix": "!",
    "intents": ["MessageContent"], "events": ["onMessage"],     # accepted, ignored
    "database": {"path": "./database/aoi.db"},                  # SQLite
})
client.variables({"coins": 0})
client.command({"name": "ping", "aliases": ["p"], "code": "Pong! $ping ms"})
client.run("nsec1...")           # or set VECTOR_NSEC; client.login(...) works too
```

## Options

`token`, `prefix` (string or list), `database` (a SQLite path or `{"path": ...}`), `mentionAuthor`, plus any
`vector.Client` option (`data_dir`, ...). aoi.js's `intents`, `events`, `respondOnEdit`, `sharding`, `cache` and
`debugs` are accepted so ported code loads. **Storage is always SQLite** (default `./database/aoi.db`); aoi.js's
database `type` and `db` are ignored.

## Commands

| aoi.js | here |
|---|---|
| `client.command({name, aliases, code, nonPrefixed})` | same, several dicts at once |
| `readyCommand`, `joinCommand`, `leaveCommand`, `banAddCommand`, `banRemoveCommand`, `deletedCommand`, `reactionAddCommand` | same; `channel` sends there |
| `awaitedCommand({name, code})` | same (use `$awaitFunc[name]` to trigger) |
| `interactionCommand({name, prototype, code})` | `name` is the button/menu/modal custom id; `prototype: "slash"` defines a slash command |
| `functionErrorCommand({code})` | renders function errors; `$handleError[function]`, `[command]`, `[error]` |
| `loopCommand({every, channel, executeOnStartup, code})` | `every` in ms or `"1h30m"` |
| `variables({...}, table)` | table accepted and ignored |
| `loadCommands(dir, debug)` | `.py` files set `exports = {...}` or `[...]`; `.json` and `.bds` work too |
| `addFunction({name, params, type, code})` | `type: "aoi.js"` is BDScript with `{param}` placeholders; `"djs"` takes a Python callable `(ctx, *args)` |
| `onMessage()`, `onInteractionCreate()`, ... | no-ops (every event is on); chainable |
| `status(...)` | accepted; Vector bots have no presence |

Commands for Discord-only events (`guildJoinCommand`, `roleCreateCommand`, `presenceUpdateCommand`, ...) are
accepted so ported bots still load, but never run.

## Notes for aoi.js users

* Code is BDScript, not aoi.js's function set. BDScript runs top to bottom, and its embed functions don't take an
  index first (`$title[text]`, not `$title[1;text]`). Message formatters such as `{newEmbed:...}` are not supported.
* Every BDScript function is available, plus the Vector-only ones in [bdscript.md](bdscript.md).
* Already running a regular bot? `BDScript(bot)` attaches the same engine to it; see [bdscript.md](bdscript.md).
* Example bot: [examples/aoijs](../examples/aoijs).
