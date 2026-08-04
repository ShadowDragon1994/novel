from __future__ import annotations

import pytest

from closed_loop import run_scan_cycle


class FakeScanner:
    def __init__(self, name: str, events: list[str], result: list[str]) -> None:
        self.name = name
        self.events = events
        self.result = result
        self.closed = False

    async def run_once(self) -> list[str]:
        self.events.append(self.name)
        return self.result

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_scan_cycle_runs_production_before_publish_and_closes_resources() -> None:
    events: list[str] = []
    production = FakeScanner("production", events, ["chapter-produced"])
    publisher = FakeScanner("publish", events, ["chapter-published"])

    result = await run_scan_cycle(production_scanner=production, publish_scanner=publisher)

    assert result == {
        "produced": ["chapter-produced"],
        "published": ["chapter-published"],
    }
    assert events == ["production", "publish"]
    assert production.closed is True
    assert publisher.closed is True


@pytest.mark.asyncio
async def test_scan_cycle_closes_resources_when_publish_fails() -> None:
    events: list[str] = []
    production = FakeScanner("production", events, [])

    class FailingPublisher(FakeScanner):
        async def run_once(self) -> list[str]:
            self.events.append(self.name)
            raise RuntimeError("publish failed")

    publisher = FailingPublisher("publish", events, [])

    with pytest.raises(RuntimeError, match="publish failed"):
        await run_scan_cycle(production_scanner=production, publish_scanner=publisher)

    assert production.closed is True
    assert publisher.closed is True
