"""Discord-compatible webhooks for Vector (needs ``pip install vector-sdk-py[webhooks]``)."""

from .store import Webhook, WebhookStore

__all__ = ("Webhook", "WebhookStore", "create_app", "WebhookCog", "serve")


def __getattr__(name: str):  # FastAPI is optional, so import lazily
    if name == "create_app":
        from .app import create_app
        return create_app
    if name == "WebhookCog":
        from .cog import WebhookCog
        return WebhookCog
    if name == "serve":
        from .cli import serve
        return serve
    raise AttributeError(name)
