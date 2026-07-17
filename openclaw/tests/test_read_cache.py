from datetime import datetime, timedelta
from pathlib import Path

from core.read_cache import ReadCache


def test_read_cache_returns_value_before_ttl(tmp_path: Path) -> None:
    cache = ReadCache(tmp_path / "openclaw.sqlite", ttl_seconds=60)
    cache.set("key-1", {"hello": "world"})
    assert cache.get("key-1") == {"hello": "world"}


def test_read_cache_expires_old_value(tmp_path: Path) -> None:
    cache = ReadCache(tmp_path / "openclaw.sqlite", ttl_seconds=60)
    cache.set("key-1", {"hello": "world"})
    with cache._connect() as connection:
        connection.execute(
            "UPDATE read_cache SET cached_at = ? WHERE cache_key = ?",
            ((datetime.now() - timedelta(minutes=2)).isoformat(), "key-1"),
        )
    assert cache.get("key-1") is None


def test_read_cache_invalidate_removes_value(tmp_path: Path) -> None:
    cache = ReadCache(tmp_path / "openclaw.sqlite", ttl_seconds=60)
    cache.set("key-1", {"hello": "world"})
    cache.invalidate("key-1")
    assert cache.get("key-1") is None


def test_read_cache_invalidate_prefix_removes_matching_values(tmp_path: Path) -> None:
    cache = ReadCache(tmp_path / "openclaw.sqlite", ttl_seconds=60)
    cache.set("table:a", 1)
    cache.set("table:b", 2)
    cache.set("other:c", 3)
    cache.invalidate_prefix("table:")
    assert cache.get("table:a") is None
    assert cache.get("table:b") is None
    assert cache.get("other:c") == 3


def test_read_cache_missing_key_returns_none(tmp_path: Path) -> None:
    cache = ReadCache(tmp_path / "openclaw.sqlite", ttl_seconds=60)
    assert cache.get("missing") is None
