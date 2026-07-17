import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


class TaskLock:
    def __init__(self, db_path: Path, timeout_minutes: int = 30) -> None:
        self.db_path = db_path
        self.timeout = timedelta(minutes=timeout_minutes)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_lock (
                    chapter_id TEXT PRIMARY KEY,
                    locked_at TEXT NOT NULL,
                    lock_step TEXT NOT NULL,
                    process_pid INTEGER NOT NULL
                )
                """
            )

    def acquire(self, chapter_id: str, lock_step: str, process_pid: int) -> bool:
        cutoff = datetime.now() - self.timeout
        with self._connect() as connection:
            connection.execute("DELETE FROM task_lock WHERE locked_at < ?", (cutoff.isoformat(),))
            cursor = connection.execute(
                "INSERT OR IGNORE INTO task_lock(chapter_id, locked_at, lock_step, process_pid) VALUES (?, ?, ?, ?)",
                (chapter_id, datetime.now().isoformat(), lock_step, process_pid),
            )
            return cursor.rowcount == 1

    def release(self, chapter_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM task_lock WHERE chapter_id = ?", (chapter_id,))

    def release_expired(self) -> None:
        cutoff = datetime.now() - self.timeout
        with self._connect() as connection:
            connection.execute("DELETE FROM task_lock WHERE locked_at < ?", (cutoff.isoformat(),))
