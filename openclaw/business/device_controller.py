from __future__ import annotations

import os

import httpx


class DeviceNotConfiguredError(RuntimeError):
    """Raised when publishing is attempted without a device gateway."""


class DeviceController:
    def __init__(self, endpoint: str | None = None, http_client: httpx.AsyncClient | None = None) -> None:
        configured_endpoint = os.getenv("HONGSHOUZHI_ENDPOINT") if endpoint is None else endpoint
        self.endpoint = (configured_endpoint or "").rstrip("/")
        self.http_client = http_client or httpx.AsyncClient(timeout=60)
        self._owns_client = http_client is None

    async def publish_chapter(
        self,
        chapter_id: str,
        account_id: str,
        *,
        device_id: str | None = None,
        platform: str | None = None,
        title: str | None = None,
        content: str | None = None,
    ) -> None:
        if not self.endpoint:
            raise DeviceNotConfiguredError(
                "HONGSHOUZHI_ENDPOINT is not configured; publishing was not attempted"
            )
        payload = {"chapter_id": chapter_id, "account_id": account_id}
        payload.update(
            {
                key: value
                for key, value in {
                    "device_id": device_id,
                    "platform": platform,
                    "title": title,
                    "content": content,
                }.items()
                if value is not None
            }
        )
        response = await self.http_client.post(f"{self.endpoint}/publish", json=payload)
        response.raise_for_status()

    async def close(self) -> None:
        if self._owns_client:
            await self.http_client.aclose()
