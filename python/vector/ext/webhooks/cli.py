"""``vector-webhooks serve``: run the bot and the HTTP server together in one process."""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any, Optional

from .store import WebhookStore


async def serve(nsec: str, *, host: str = "0.0.0.0", port: int = 8080, db: str = "webhooks.db",
                base_url: Optional[str] = None, admin_key: Optional[str] = None, data_dir: Optional[str] = None,
                prefix: str = "!") -> None:
    import uvicorn

    from ... import Intents
    from ...ext import commands
    from .app import create_app
    from .cog import WebhookCog

    base_url = base_url or f"http://localhost:{port}"
    store = WebhookStore(db)
    bot = commands.Bot(command_prefix=prefix, intents=Intents.all(), data_dir=data_dir)
    await bot.add_cog(WebhookCog(bot, store, base_url))
    app = create_app(bot, store, admin_key=admin_key, base_url=base_url)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
    await asyncio.gather(bot.start(nsec), server.serve())


def main(argv: Optional[list] = None) -> None:
    ap = argparse.ArgumentParser(prog="vector-webhooks", description="Discord-compatible webhooks for Vector")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the bot and the webhook server")
    s.add_argument("--nsec", default=os.environ.get("VECTOR_NSEC"), help="bot secret key (or $VECTOR_NSEC)")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8080)
    s.add_argument("--db", default=os.environ.get("WEBHOOKS_DB", "webhooks.db"))
    s.add_argument("--base-url", default=os.environ.get("WEBHOOKS_BASE_URL"), help="public URL shown in created hooks")
    s.add_argument("--admin-key", default=os.environ.get("WEBHOOKS_ADMIN_KEY"), help="enables POST /admin/webhooks")
    s.add_argument("--data-dir", default=os.environ.get("VECTOR_DATA_DIR"))
    args = ap.parse_args(argv)
    if not args.nsec:
        ap.error("--nsec or $VECTOR_NSEC is required")
    asyncio.run(serve(args.nsec, host=args.host, port=args.port, db=args.db, base_url=args.base_url,
                      admin_key=args.admin_key, data_dir=args.data_dir))


if __name__ == "__main__":
    main()
