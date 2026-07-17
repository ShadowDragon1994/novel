from time import monotonic

import pytest

from core.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_allows_request() -> None:
    limiter = RateLimiter(qps=1, capacity=1)
    await limiter.acquire()
    assert limiter.tokens == 0


@pytest.mark.asyncio
async def test_rate_limiter_enforces_delay_after_capacity_is_used() -> None:
    limiter = RateLimiter(qps=20, capacity=1)
    started_at = monotonic()
    await limiter.acquire()
    await limiter.acquire()
    assert monotonic() - started_at >= 0.04
