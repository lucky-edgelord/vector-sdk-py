# Discord-compatible webhooks

Run one small server and any tool that can post to a Discord webhook (GitHub, Grafana, CI, uptime monitors, your own
scripts) can post to a Vector channel instead. You swap the URL; nothing else changes.

## 1. Install and run

```sh
pip install "vector-sdk-py[webhooks]"

export VECTOR_NSEC=nsec1...                       # your bot's secret key
export WEBHOOKS_ADMIN_KEY="$(openssl rand -hex 24)"   # optional: enables creating hooks over HTTP
vector-webhooks serve --base-url https://hooks.example.com --port 8080
```

* The bot and the HTTP server run in one process. `--base-url` is the public address people will reach it at; it
  only affects the URLs shown when you create hooks.
* Data lives in `webhooks.db` (SQLite, `--db` to move it). Tokens are stored hashed.
* Put it behind HTTPS (Caddy, nginx, a tunnel such as Cloudflare Tunnel). The token in the URL is the secret, so
  never expose plain HTTP on the internet.
* Same thing as a script: [`examples/webhook_server.py`](../examples/webhook_server.py).

## 2. Create a webhook

**From Vector:** add the bot to a community, then in the channel you want to post into (you need `manage_channels`):

```
!webhook create deploys
```

The bot DMs you the URL, shown once: `https://hooks.example.com/api/webhooks/<id>/<token>`.
`!webhook list` shows the channel's hooks and `!webhook delete <id>` removes one.

**Over HTTP** (needs `WEBHOOKS_ADMIN_KEY`):

```sh
curl -X POST https://hooks.example.com/admin/webhooks \
  -H "Authorization: Bearer $WEBHOOKS_ADMIN_KEY" -H 'content-type: application/json' \
  -d '{"channel_id": "<channel id>", "name": "deploys"}'
# -> {"id": "...", "token": "...", "url": "https://hooks.example.com/api/webhooks/<id>/<token>"}
```

`GET /admin/webhooks` lists hooks and `DELETE /admin/webhooks/<id>` removes one.

## 3. Post to it

```sh
URL="https://hooks.example.com/api/webhooks/<id>/<token>"

# plain message
curl -X POST "$URL" -H 'content-type: application/json' -d '{"content": "hello"}'

# embed with fields (shown as a quote block with a fields table)
curl -X POST "$URL" -H 'content-type: application/json' -d '{
  "username": "Deploy Bot",
  "embeds": [{"title": "Deploy succeeded", "url": "https://example.com", "description": "Release **v1.4.2** is live.",
    "fields": [{"name": "Env", "value": "prod", "inline": true}, {"name": "Time", "value": "42s", "inline": true}],
    "footer": {"text": "CI pipeline"}, "timestamp": "2026-11-12T19:50:00Z"}]}'

# file upload
curl -X POST "$URL" -F 'payload_json={"content":"report"}' -F 'files[0]=@chart.png'

# get the message back (so you can edit or delete it later)
curl -X POST "$URL?wait=true" -H 'content-type: application/json' -d '{"content": "building..."}'
curl -X PATCH "$URL/messages/<message id>" -H 'content-type: application/json' -d '{"content": "done"}'
curl -X DELETE "$URL/messages/<message id>"
```

Python:

```python
import httpx
httpx.post(URL, json={"content": "hello", "embeds": [{"title": "Hi", "description": "from Python"}]})
```

## 4. Plug in existing tools

| Tool | What to do |
|---|---|
| Anything with a "Discord webhook" box | paste the URL |
| GitHub | Repo → Settings → Webhooks → Payload URL = `<URL>/github`, content type `application/json`. Push, issues, pull requests (opened/closed/merged), comments, releases, stars and forks are shown; other events are accepted and ignored |
| Slack-style senders (many alerting tools) | use `<URL>/slack` |
| Grafana, Uptime Kuma, Sentry, Healthchecks | their Discord notifier with this URL |

## What works and what doesn't

| Discord feature | On Vector |
|---|---|
| `content` (max 2000), `embeds` (max 10), files, `?wait=true` | yes |
| `username` | shown as a bold first line (messages come from the bot) |
| `avatar_url`, `tts`, `components`, `allowed_mentions`, `thread_id` | accepted and ignored |
| Embed colour | ignored; embeds always use Vector's own colours |
| Embed images | attach a file, or give an image URL (it is downloaded and attached) |
| Edit / delete messages | yes, for messages this webhook sent |
| Rate limit | 5 requests per 2 seconds per webhook, `429` with `Retry-After` |

A post with attached files or an embed image goes out as several chat messages (text, image, footer), so edit and
delete only affect the last one.

## Errors

JSON in Discord's shape, `{"message": ..., "code": ...}`: `401` bad token, `404` unknown webhook/channel/message,
`400` empty or oversized payload or bad JSON, `429` rate limited.

## Library use

```python
from vector.ext import commands
from vector.ext.webhooks import WebhookStore, WebhookCog, create_app

bot = commands.Bot(command_prefix="!")
store = WebhookStore("webhooks.db")
await bot.add_cog(WebhookCog(bot, store, "https://hooks.example.com"))
app = create_app(bot, store, admin_key="...", base_url="https://hooks.example.com")  # a FastAPI app; run with uvicorn
```

`create_app` returns a normal FastAPI app, so you can mount it inside a bigger service.
