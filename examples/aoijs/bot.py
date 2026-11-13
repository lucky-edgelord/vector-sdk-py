"""An aoi.js-style bot on Vector.   VECTOR_NSEC=nsec1... python examples/aoijs/bot.py"""
from vector.ext.aoijs import AoiClient

client = AoiClient({
    "prefix": "!",
    "intents": ["MessageContent", "Guilds", "GuildMessages"],   # accepted for familiarity
    "events": ["onMessage", "onInteractionCreate"],
    "database": {"path": "./database/aoi.db"},                   # SQLite
})

client.variables({"coins": 0})
client.command({"name": "ping", "code": "Pong! $ping ms"})
client.command({"name": "coins", "aliases": ["bal"], "code": "$username has $getUserVar[coins] coins."})
client.command({"name": "work", "code": "$cooldown[1h;Come back in %time%]"
                                        "$setUserVar[coins;$sum[$getUserVar[coins];10]]You earned 10 coins!"})
client.readyCommand({"code": "$log[Logged in as $clientName]"})
client.functionErrorCommand({"code": "Oops, $handleError[function] failed: $handleError[error]"})
client.loopCommand({"every": "1h", "channel": "<channel id>", "code": "Still here!"})
client.addFunction({"name": "$greet", "params": ["who"], "type": "aoi.js", "code": "Hello {who}!"})
client.loadCommands("./examples/aoijs/commands", True)

client.run()
