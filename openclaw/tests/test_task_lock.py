from datetime import datetime, timedelta
from pathlib import Path

from core.task_lock import TaskLock


def test_task_lock_acquire_and_release(tmp_path: Path) -> None:
    lock = TaskLock(tmp_path / "openclaw.sqlite")
    assert lock.acquire("chapter-1", "outline", 1)
    assert not lock.acquire("chapter-1", "outline", 1)
    lock.release("chapter-1")
    assert lock.acquire("chapter-1", "outline", 1)


def test_task_lock_releases_expired_lock_on_acquire(tmp_path: Path) -> None:
    lock = TaskLock(tmp_path / "openclaw.sqlite", timeout_minutes=30)
    assert lock.acquire("chapter-1", "outline", 1)
    with lock._connect() as connection:
        connection.execute(
            "UPDATE task_lock SET locked_at = ? WHERE chapter_id = ?",
            ((datetime.now() - timedelta(minutes=31)).isoformat(), "chapter-1"),
        )
    assert lock.acquire("chapter-1", "draft", 2)


def test_task_lock_allows_different_chapters(tmp_path: Path) -> None:
    lock = TaskLock(tmp_path / "openclaw.sqlite")
    assert lock.acquire("chapter-1", "outline", 1)
    assert lock.acquire("chapter-2", "outline", 1)
