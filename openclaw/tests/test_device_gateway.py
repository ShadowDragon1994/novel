from __future__ import annotations

import httpx
import pytest

from device_gateway.app import create_app


class FakeAdb:
    async def health(self) -> dict[str, str | bool]:
        return {"available": True, "version": "Android Debug Bridge version 1.0.41"}

    async def device_state(self, device_id: str) -> str:
        return "device" if device_id == "cloud-1" else "offline"


@pytest.mark.asyncio
async def test_health_reports_adb_availability() -> None:
    transport = httpx.ASGITransport(app=create_app(adb=FakeAdb()))
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "adb": {"available": True, "version": "Android Debug Bridge version 1.0.41"},
    }


@pytest.mark.asyncio
async def test_device_endpoint_reports_connection_state() -> None:
    transport = httpx.ASGITransport(app=create_app(adb=FakeAdb()))
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.get("/devices/cloud-1")

    assert response.status_code == 200
    assert response.json() == {"device_id": "cloud-1", "state": "device", "connected": True}


@pytest.mark.asyncio
async def test_publish_fails_until_platform_workflow_is_configured() -> None:
    transport = httpx.ASGITransport(app=create_app(adb=FakeAdb()))
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.post(
            "/publish",
            json={
                "chapter_id": "chapter-1",
                "account_id": "account-1",
                "device_id": "cloud-1",
                "platform": "example",
                "title": "第一章",
                "content": "正文",
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "publishing workflow is not configured"
