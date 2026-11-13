"""SQLite storage for BDScript variables and cooldowns."""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

SCOPES = ("global", "user", "user_global", "server", "channel")


class Storage:
    def __init__(self, path: str = "bdscript.db") -> None:
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock, self.db:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS vars (scope TEXT NOT NULL, name TEXT NOT NULL, key TEXT NOT NULL,
                    value TEXT NOT NULL, PRIMARY KEY (scope, name, key));
                CREATE INDEX IF NOT EXISTS vars_name ON vars (scope, name);
                CREATE TABLE IF NOT EXISTS cooldowns (kind TEXT NOT NULL, command TEXT NOT NULL, key TEXT NOT NULL,
                    until REAL NOT NULL, PRIMARY KEY (kind, command, key));
                CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                """
            )

    # -- variables ------------------------------------------------------------------------------------------
    def get(self, scope: str, name: str, key: str) -> Optional[str]:
        with self.lock:
            r = self.db.execute("SELECT value FROM vars WHERE scope=? AND name=? AND key=?", (scope, name, key)).fetchone()
        return r[0] if r else None

    def set(self, scope: str, name: str, key: str, value: str) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO vars VALUES (?,?,?,?)", (scope, name, key, value))

    def delete(self, scope: str, name: str, key: Optional[str] = None) -> int:
        with self.lock, self.db:
            if key is None:
                return self.db.execute("DELETE FROM vars WHERE scope=? AND name=?", (scope, name)).rowcount
            return self.db.execute("DELETE FROM vars WHERE scope=? AND name=? AND key=?", (scope, name, key)).rowcount

    def rows(self, scope: str, name: str, key_prefix: str = "") -> List[Tuple[str, str]]:
        with self.lock:
            return list(self.db.execute(
                "SELECT key, value FROM vars WHERE scope=? AND name=? AND key LIKE ?",
                (scope, name, key_prefix.replace("%", r"\%") + "%")))

    def count(self, scope: Optional[str] = None) -> int:
        with self.lock:
            if scope:
                return self.db.execute("SELECT COUNT(*) FROM vars WHERE scope=?", (scope,)).fetchone()[0]
            return self.db.execute("SELECT COUNT(*) FROM vars").fetchone()[0]

    # -- cooldowns ------------------------------------------------------------------------------------------
    def cooldown_left(self, kind: str, command: str, key: str) -> float:
        with self.lock:
            r = self.db.execute("SELECT until FROM cooldowns WHERE kind=? AND command=? AND key=?",
                                (kind, command, key)).fetchone()
        return max(0.0, r[0] - time.time()) if r else 0.0

    def set_cooldown(self, kind: str, command: str, key: str, seconds: float) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO cooldowns VALUES (?,?,?,?)", (kind, command, key, time.time() + seconds))

    def kv_get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self.lock:
            r = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def kv_set(self, key: str, value: str) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, value))

    def close(self) -> None:
        self.db.close()
