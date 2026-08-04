from __future__ import annotations

import argparse
import asyncio
import json
import os
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

import httpx
import uvicorn

from business.production_scanner import ProductionScanner
from business.publish_scanner import PublishScanner
from core.logger import configure_logging, get_logger
from main import create_scheduler

configure_logging()
logger = get_logger(__name__)


class Scanner(Protocol):
    async def run_once(self) -> list[str]: ...

    async def close(self) -> None: ...


async def run_scan_cycle(
    *,
    production_scanner: Scanner | None = None,
    publish_scanner: Scanner | None = None,
) -> dict[str, list[str]]:
    production = production_scanner or ProductionScanner()
    publisher = publish_scanner or PublishScanner()
    try:
        produced = await production.run_once()
        published = await publisher.run_once()
        return {"produced": produced, "published": published}
    finally:
        await production.close()
        await publisher.close()


class GatewayRuntime(AbstractAsyncContextManager["GatewayRuntime"]):
    def __init__(self, host: str = "127.0.0.1", port: int = 8080) -> None:
        self.host = host
        self.port = port
        self.server = uvicorn.Server(
            uvicorn.Config(
                "device_gateway.app:app",
                host=host,
                port=port,
                log_level="info",
            )
        )
        self.task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> GatewayRuntime:
        os.environ.setdefault("HONGSHOUZHI_ENDPOINT", f"http://{self.host}:{self.port}")
        self.task = asyncio.create_task(self.server.serve())
        await self._wait_until_ready()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        self.server.should_exit = True
        if self.task:
            await self.task

    async def _wait_until_ready(self) -> None:
        deadline = asyncio.get_running_loop().time() + 45
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            while asyncio.get_running_loop().time() < deadline:
                if self.task and self.task.done():
                    await self.task
                try:
                    response = await client.get(f"http://{self.host}:{self.port}/health")
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.5)
        raise RuntimeError("device gateway did not become healthy within 45 seconds")


async def run_once() -> dict[str, list[str]]:
    async with GatewayRuntime():
        return await run_scan_cycle()


async def run_continuous() -> None:
    async with GatewayRuntime():
        initial = await run_scan_cycle()
        logger.info("Initial closed-loop cycle complete: {}", initial)
        scheduler = create_scheduler()
        scheduler.start()
        logger.info("Closed-loop scheduler started")
        try:
            await asyncio.Event().wait()
        finally:
            scheduler.shutdown(wait=False)
            for resource in getattr(scheduler, "openclaw_resources", []):
                close = getattr(resource, "close", None)
                if close:
                    result = close()
                    if asyncio.iscoroutine(result):
                        await result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the OpenClaw closed-loop service")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="run one production and publish cycle")
    mode.add_argument("--continuous", action="store_true", help="run continuously on configured intervals")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.continuous:
            asyncio.run(run_continuous())
        else:
            result = asyncio.run(run_once())
            print(json.dumps(result, ensure_ascii=False))
    except KeyboardInterrupt:
        logger.info("Closed-loop service stopped")


if __name__ == "__main__":
    main()
