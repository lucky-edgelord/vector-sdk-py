"""Translate Discord / Slack / GitHub webhook payloads into Vector messages, and messages back into Discord JSON."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ...embeds import Embed

MAX_CONTENT = 2000
MAX_EMBEDS = 10


class PayloadError(ValueError):
    """Bad request; ``code`` is the Discord error code."""

    def __init__(self, message: str, code: int = 50035) -> None:
        super().__init__(message)
        self.code = code


def _colour(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        v = value.lstrip("#")
        try:
            return int(v, 16) if len(v) in (3, 6) else None
        except ValueError:
            return None
    return None


def discord_payload(payload: Mapping[str, Any]) -> Tuple[str, List[Embed]]:
    """A Discord "execute webhook" body -> (text, embeds). ``username`` becomes a bold first line, since Vector
    messages always come from the bot's own identity."""
    content = payload.get("content") or ""
    if not isinstance(content, str):
        raise PayloadError("content: must be a string")
    if len(content) > MAX_CONTENT:
        raise PayloadError(f"content: Must be {MAX_CONTENT} or fewer in length.")
    raw_embeds = payload.get("embeds") or []
    if not isinstance(raw_embeds, list) or len(raw_embeds) > MAX_EMBEDS:
        raise PayloadError(f"embeds: Must be {MAX_EMBEDS} or fewer in length.")
    embeds = [Embed.from_dict(e) for e in raw_embeds if isinstance(e, dict)]
    name = payload.get("username")
    if name and isinstance(name, str):
        content = f"**{name}**\n{content}" if content else f"**{name}**"
    return content, embeds


def slack_payload(payload: Mapping[str, Any]) -> Tuple[str, List[Embed]]:
    """Slack incoming-webhook body (``text`` + ``attachments``) -> (text, embeds)."""
    text = str(payload.get("text") or "")
    embeds: List[Embed] = []
    for a in payload.get("attachments") or []:
        e = Embed(title=a.get("title"), description=a.get("text") or a.get("fallback"), url=a.get("title_link"),
                  colour=_colour(a.get("color")))
        if a.get("author_name"):
            e.set_author(name=a["author_name"], url=a.get("author_link"))
        for f in a.get("fields") or []:
            e.add_field(name=str(f.get("title", "")), value=str(f.get("value", "")), inline=bool(f.get("short")))
        if a.get("footer"):
            e.set_footer(text=a["footer"])
        if a.get("image_url"):
            e.set_image(url=a["image_url"])
        if a.get("ts"):
            e.timestamp = datetime.datetime.fromtimestamp(int(a["ts"]), datetime.timezone.utc)
        embeds.append(e)
    name = payload.get("username")
    if name:
        text = f"**{name}**\n{text}" if text else f"**{name}**"
    if len(text) > MAX_CONTENT:
        text = text[: MAX_CONTENT - 1] + "…"
    return text, embeds[:MAX_EMBEDS]


def _short(sha: str) -> str:
    return sha[:7]


def github_payload(event: str, p: Mapping[str, Any]) -> Optional[Tuple[str, List[Embed]]]:
    """A GitHub webhook delivery -> (text, embeds); ``None`` for events we ignore."""
    repo = (p.get("repository") or {}).get("full_name", "")
    sender = (p.get("sender") or {}).get("login", "")
    e = Embed(colour=0x59FCB3)
    e.set_author(name=sender or repo, url=(p.get("sender") or {}).get("html_url"))
    if event == "ping":
        e.title = f"Webhook connected: {repo}"
        e.description = p.get("zen", "")
    elif event == "push":
        commits = p.get("commits") or []
        branch = str(p.get("ref", "")).replace("refs/heads/", "")
        e.title = f"[{repo}:{branch}] {len(commits)} new commit{'s' if len(commits) != 1 else ''}"
        e.url = p.get("compare")
        e.description = "\n".join(
            f"[`{_short(c['id'])}`]({c.get('url', '')}) {str(c.get('message', '')).splitlines()[0][:80]}"
            for c in commits[:8])
        if len(commits) > 8:
            e.description += f"\n… and {len(commits) - 8} more"
        if not commits:
            return None
    elif event in ("issues", "pull_request"):
        obj = p.get("issue") or p.get("pull_request") or {}
        action = p.get("action", "")
        if event == "pull_request" and action == "closed" and obj.get("merged"):
            action = "merged"
        if action not in ("opened", "closed", "reopened", "merged"):
            return None
        kind = "pull request" if event == "pull_request" else "issue"
        e.title = f"[{repo}] {kind.capitalize()} {action}: #{obj.get('number')} {obj.get('title', '')}"[:250]
        e.url = obj.get("html_url")
        e.description = (obj.get("body") or "")[:300] if action == "opened" else None
    elif event == "issue_comment":
        if p.get("action") != "created":
            return None
        i, c = p.get("issue") or {}, p.get("comment") or {}
        e.title = f"[{repo}] New comment on #{i.get('number')}: {i.get('title', '')}"[:250]
        e.url = c.get("html_url")
        e.description = (c.get("body") or "")[:400]
    elif event == "release":
        if p.get("action") != "published":
            return None
        r = p.get("release") or {}
        e.title = f"[{repo}] Release {r.get('tag_name', '')}: {r.get('name') or ''}"[:250]
        e.url = r.get("html_url")
        e.description = (r.get("body") or "")[:400]
    elif event == "star" and p.get("action") == "created":
        e.title = f"⭐ {sender} starred {repo}"
        e.url = (p.get("repository") or {}).get("html_url")
    elif event == "fork":
        e.title = f"🍴 {sender} forked {repo}"
        e.url = (p.get("forkee") or {}).get("html_url")
    else:
        return None
    return "", [e]


def message_json(*, msg_id: str, channel_id: str, webhook_id: str, name: str, content: str, embeds: List[Embed],
                 timestamp: Optional[datetime.datetime] = None, edited: bool = False) -> Dict[str, Any]:
    """A Discord message object (the subset webhook clients read)."""
    ts = (timestamp or datetime.datetime.now(datetime.timezone.utc)).isoformat()
    return {
        "id": msg_id, "type": 0, "content": content, "channel_id": channel_id, "webhook_id": webhook_id,
        "author": {"id": webhook_id, "username": name, "avatar": None, "discriminator": "0000", "bot": True},
        "attachments": [], "embeds": [e.to_dict() for e in embeds], "mentions": [], "mention_roles": [],
        "mention_everyone": False, "pinned": False, "tts": False, "flags": 0, "components": [],
        "timestamp": ts, "edited_timestamp": ts if edited else None,
    }
