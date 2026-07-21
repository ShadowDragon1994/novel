from __future__ import annotations

import json

import httpx
import pytest

from business.device_controller import DeviceController, DeviceNotConfiguredError


@pytest.mark.asyncio
async def test_publish_fails_when_endpoint_is_not_configured() -> None:
    controller = DeviceController(endpoint="", http_client=httpx.AsyncClient())
    try:
        with pytest.raises(DeviceNotConfiguredError, match="HONGSHOUZHI_ENDPOINT"):
            await controller.publish_chapter("chapter-1", "account-1")
    finally:
        await controller.http_client.aclose()


@pytest.mark.asyncio
async def test_publish_sends_extended_gateway_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"chapter_label": "第1章 第一章", "status": "审核中"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    controller = DeviceController(endpoint="http://gateway", http_client=http_client)
    try:
        result = await controller.publish_chapter(
            "chapter-1",
            "account-1",
            device_id="cloud-1",
            platform="example",
            title="第一章",
            content="正文",
        )
    finally:
        await http_client.aclose()

    assert captured == {
        "chapter_id": "chapter-1",
        "account_id": "account-1",
        "device_id": "cloud-1",
        "platform": "example",
        "title": "第一章",
        "content": "正文",
    }
    assert result == {"chapter_label": "第1章 第一章", "status": "审核中"}
