from __future__ import annotations

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
