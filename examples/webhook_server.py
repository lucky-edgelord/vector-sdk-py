"""A Discord-compatible webhook server for Vector (FastAPI + vector-sdk-py).

    pip install "vector-sdk-py[webhooks]"
    export VECTOR_NSEC=nsec1...        # your bot's key
    export WEBHOOKS_ADMIN_KEY=change-me
    python examples/webhook_server.py

Then, in a Vector channel where the bot is, an admin types ``!webhook create deploys``; the bot DMs a URL like
``http://localhost:8080/api/webhooks/<id>/<token>``. Use it anywhere a Discord webhook URL works:

    curl -X POST "$URL" -H 'content-type: application/json' \\
         -d '{"content": "hello", "embeds": [{"title": "Deploy", "description": "ok", "fields": [
              {"name": "Env", "value": "prod", "inline": true}, {"name": "Time", "value": "42s", "inline": true}]}]}'

    curl -X POST "$URL/slack"  -d '{"text": "from a Slack integration"}' -H 'content-type: application/json'
    # GitHub: add "$URL/github" as a webhook (content type application/json) in the repo settings

Or create hooks over HTTP:  POST /admin/webhooks  with ``Authorization: Bearer $WEBHOOKS_ADMIN_KEY`` and
``{"channel_id": "...", "name": "ops"}``. ``vector-webhooks serve`` does the same as this script.
"""

import asyncio
import os

from vector.ext.webhooks import serve

if __name__ == "__main__":
    asyncio.run(serve(
        os.environ["VECTOR_NSEC"],
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8080")),
        base_url=os.environ.get("WEBHOOKS_BASE_URL"),      # the public URL, shown in created webhook links
        admin_key=os.environ.get("WEBHOOKS_ADMIN_KEY"),
    ))
