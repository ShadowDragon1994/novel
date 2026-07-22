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
        chapter_number: int | None = None,
        title: str | None = None,
        content: str | None = None,
        work_name: str | None = None,
        work_introduction: str | None = None,
        work_protagonist: str | None = None,
        work_audience: str | None = None,
        work_category: str | None = None,
    ) -> dict[str, str]:
        if not self.endpoint:
            raise DeviceNotConfiguredError(
                "HONGSHOUZHI_ENDPOINT is not configured; publishing was not attempted"
            )
        payload: dict[str, str | int] = {"chapter_id": chapter_id, "account_id": account_id}
        payload.update(
            {
                key: value
                for key, value in {
                    "device_id": device_id,
                    "platform": platform,
                    "chapter_number": chapter_number,
                    "title": title,
                    "content": content,
                    "work_name": work_name,
                    "work_introduction": work_introduction,
                    "work_protagonist": work_protagonist,
                    "work_audience": work_audience,
                    "work_category": work_category,
                }.items()
                if value is not None
            }
        )
        response = await self.http_client.post(f"{self.endpoint}/publish", json=payload)
        response.raise_for_status()
        result = response.json()
        return {"chapter_label": str(result["chapter_label"]), "status": str(result["status"])}

    async def close(self) -> None:
        if self._owns_client:
            await self.http_client.aclose()
