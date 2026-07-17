from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class ReadCache:
    def __init__(self, db_path: Path, ttl_seconds: int = 60) -> None:
        self.db_path = db_path
        self.ttl = timedelta(seconds=ttl_seconds)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS read_cache (
                    cache_key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    cached_at TEXT NOT NULL
                )
                """
            )

    def get(self, cache_key: str) -> Any | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload, cached_at FROM read_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        if not row:
            return None
        cached_at = datetime.fromisoformat(row[1])
        if datetime.now() - cached_at > self.ttl:
            self.invalidate(cache_key)
            return None
        return json.loads(row[0])

    def set(self, cache_key: str, payload: Any) -> None:
        with self._connect() as connection:
            connection.execute(
                "REPLACE INTO read_cache(cache_key, payload, cached_at) VALUES (?, ?, ?)",
                (cache_key, json.dumps(payload, ensure_ascii=False), datetime.now().isoformat()),
            )

    def invalidate(self, cache_key: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM read_cache WHERE cache_key = ?", (cache_key,))

    def invalidate_prefix(self, cache_key_prefix: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM read_cache WHERE cache_key LIKE ?", (f"{cache_key_prefix}%",))

