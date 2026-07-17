import asyncio
from time import monotonic


class RateLimiter:
    def __init__(self, qps: float, capacity: int) -> None:
        self.qps = qps
        self.capacity = capacity
        self.tokens = float(capacity)
        self.updated_at = monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = monotonic()
                elapsed = now - self.updated_at
                self.tokens = min(self.capacity, self.tokens + elapsed * self.qps)
                self.updated_at = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                sleep_seconds = (1 - self.tokens) / self.qps
            await asyncio.sleep(sleep_seconds)
