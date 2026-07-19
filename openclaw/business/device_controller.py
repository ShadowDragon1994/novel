from __future__ import annotations

import os

import httpx


class DeviceNotConfiguredError(RuntimeError):
    """Raised when publishing is attempted without a device gateway."""


class DeviceController:
    def __init__(self, endpoint: str | None = None, http_client: httpx.AsyncClient | None = None) -> None:
        self.endpoint = (endpoint or os.getenv("HONGSHOUZHI_ENDPOINT") or "").rstrip("/")
        self.http_client = http_client or httpx.AsyncClient(timeout=60)
        self._owns_client = http_client is None

    async def publish_chapter(self, chapter_id: str, account_id: str) -> None:
        if not self.endpoint:
            raise DeviceNotConfiguredError(
                "HONGSHOUZHI_ENDPOINT is not configured; publishing was not attempted"
            )
        response = await self.http_client.post(
            f"{self.endpoint}/publish",
            json={"chapter_id": chapter_id, "account_id": account_id},
        )
        response.raise_for_status()

    async def close(self) -> None:
        if self._owns_client:
            await self.http_client.aclose()
