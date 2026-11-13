"""SQLite storage for webhooks (tokens are stored hashed, shown once at creation)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class Webhook:
    id: str
    name: str
    channel_id: str
    community_id: Optional[str]
    created_by: Optional[str]
    created_at: int


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class WebhookStore:
    def __init__(self, path: str = "webhooks.db") -> None:
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS webhooks (
                    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, name TEXT NOT NULL, channel_id TEXT NOT NULL,
                    community_id TEXT, created_by TEXT, created_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY, webhook_id TEXT NOT NULL, channel_id TEXT NOT NULL);
                """
            )

    @staticmethod
    def _row(r: tuple) -> Webhook:
        return Webhook(id=r[0], name=r[1], channel_id=r[2], community_id=r[3], created_by=r[4], created_at=r[5])

    _COLS = "id, name, channel_id, community_id, created_by, created_at"

    def create(self, name: str, channel_id: str, community_id: Optional[str] = None,
               created_by: Optional[str] = None) -> Tuple[Webhook, str]:
        """Make a webhook; returns it with its secret token (only available now)."""
        wid = str(secrets.randbelow(10**18) + 10**18)  # 19 digits, so tools expecting Discord-shaped ids accept it
        token = secrets.token_urlsafe(48)
        now = int(time.time())
        with self._lock, self._db:
            self._db.execute("INSERT INTO webhooks VALUES (?,?,?,?,?,?,?)",
                             (wid, _hash(token), name[:80] or "webhook", channel_id, community_id, created_by, now))
        return Webhook(wid, name[:80] or "webhook", channel_id, community_id, created_by, now), token

    def verify(self, wid: str, token: str) -> Optional[Webhook]:
        with self._lock:
            r = self._db.execute(f"SELECT {self._COLS}, token_hash FROM webhooks WHERE id=?", (wid,)).fetchone()
        if r is None or not hmac.compare_digest(r[-1], _hash(token)):
            return None
        return self._row(r[:-1])

    def get(self, wid: str) -> Optional[Webhook]:
        with self._lock:
            r = self._db.execute(f"SELECT {self._COLS} FROM webhooks WHERE id=?", (wid,)).fetchone()
        return self._row(r) if r else None

    def list(self, channel_id: Optional[str] = None, community_id: Optional[str] = None) -> List[Webhook]:
        q, args = f"SELECT {self._COLS} FROM webhooks", []
        cond = []
        if channel_id:
            cond.append("channel_id=?"); args.append(channel_id)
        if community_id:
            cond.append("community_id=?"); args.append(community_id)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        with self._lock:
            return [self._row(r) for r in self._db.execute(q + " ORDER BY created_at", args)]

    def rename(self, wid: str, name: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE webhooks SET name=? WHERE id=?", (name[:80], wid))

    def delete(self, wid: str) -> bool:
        with self._lock, self._db:
            n = self._db.execute("DELETE FROM webhooks WHERE id=?", (wid,)).rowcount
            self._db.execute("DELETE FROM messages WHERE webhook_id=?", (wid,))
        return bool(n)

    def add_message(self, message_id: str, webhook_id: str, channel_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO messages VALUES (?,?,?)", (message_id, webhook_id, channel_id))

    def message_channel(self, message_id: str, webhook_id: str) -> Optional[str]:
        with self._lock:
            r = self._db.execute("SELECT channel_id FROM messages WHERE message_id=? AND webhook_id=?",
                                 (message_id, webhook_id)).fetchone()
        return r[0] if r else None

    def drop_message(self, message_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM messages WHERE message_id=?", (message_id,))

    def close(self) -> None:
        self._db.close()
