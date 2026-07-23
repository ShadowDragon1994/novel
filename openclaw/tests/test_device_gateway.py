from __future__ import annotations

import asyncio

import httpx
import pytest

from device_gateway.app import create_app
from device_gateway.fanqie_workflow import DeviceQuarantinedError, PublishResult


class FakeAdb:
    def __init__(self) -> None:
        self.connected_devices: list[str] = []

    async def health(self) -> dict[str, str | bool]:
        return {"available": True, "version": "Android Debug Bridge version 1.0.41"}

    async def device_state(self, device_id: str) -> str:
        return "device" if device_id == "cloud-1" else "offline"

    async def connect_device(self, device_id: str) -> str:
        self.connected_devices.append(device_id)
        return f"connected to {device_id}"


class FakePublisher:
    def __init__(self) -> None:
        self.requests = []
        self.works = []

    async def ensure_work(self, work):
        self.works.append(work)

    async def publish(self, chapter):
        self.requests.append(chapter)
        return PublishResult(chapter_label=f"第{chapter.number}章 {chapter.title}", status="审核中")


class SerialPublisher(FakePublisher):
    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.max_active = 0

    async def publish(self, chapter):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        result = await super().publish(chapter)
        self.active -= 1
        return result


class QuarantiningPublisher(FakePublisher):
    def __init__(self) -> None:
        super().__init__()
        self.recovered = False

    async def publish(self, chapter):
        self.requests.append(chapter)
        raise DeviceQuarantinedError("device recovery failed")

    async def recover_device(self) -> None:
        self.recovered = True


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
async def test_gateway_connects_configured_adb_devices_on_startup() -> None:
    adb = FakeAdb()
    app = create_app(
        adb=adb,
        configured_device_ids=("127.0.0.1:49303", "127.0.0.1:49304"),
    )

    async with app.router.lifespan_context(app):
        pass

    assert adb.connected_devices == ["127.0.0.1:49303", "127.0.0.1:49304"]


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


@pytest.mark.asyncio
async def test_publish_accepts_existing_contract_but_requires_device_id() -> None:
    transport = httpx.ASGITransport(app=create_app(adb=FakeAdb()))
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.post(
            "/publish",
            json={"chapter_id": "chapter-1", "account_id": "account-1"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "device_id is required for ADB publishing"


@pytest.mark.asyncio
async def test_publish_uses_configured_default_device_id() -> None:
    transport = httpx.ASGITransport(app=create_app(adb=FakeAdb(), default_device_id="cloud-1"))
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.post(
            "/publish",
            json={"chapter_id": "chapter-1", "account_id": "account-1"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "publishing workflow is not configured"


@pytest.mark.asyncio
async def test_publish_runs_configured_workflow_and_returns_verified_result() -> None:
    publisher = FakePublisher()
    transport = httpx.ASGITransport(
        app=create_app(adb=FakeAdb(), workflow_factory=lambda _device_id: publisher)
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.post(
            "/publish",
            json={
                "chapter_id": "chapter-2",
                "account_id": "account-1",
                "device_id": "cloud-1",
                "chapter_number": 2,
                "title": "化工厂深处",
                "content": "正文" * 1000,
            },
        )

    assert response.status_code == 200
    assert response.json() == {"chapter_label": "第2章 化工厂深处", "status": "审核中"}
    assert publisher.requests[0].number == 2


@pytest.mark.asyncio
async def test_publish_ensures_first_work_before_publishing_chapter() -> None:
    publisher = FakePublisher()
    transport = httpx.ASGITransport(
        app=create_app(adb=FakeAdb(), workflow_factory=lambda _device_id: publisher)
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.post(
            "/publish",
            json={
                "chapter_id": "chapter-1",
                "account_id": "account-1",
                "device_id": "cloud-1",
                "chapter_number": 1,
                "title": "传承戒指",
                "content": "正文" * 1000,
                "work_name": "测试修真小说",
                "work_introduction": "作品简介" * 20,
                "work_protagonist": "林玄",
                "work_audience": "男频",
                "work_category": "东方仙侠",
            },
        )

    assert response.status_code == 200
    assert publisher.works[0].name == "测试修真小说"
    assert publisher.requests[0].number == 1


@pytest.mark.asyncio
async def test_publish_serializes_requests_for_one_device() -> None:
    publisher = SerialPublisher()
    app = create_app(adb=FakeAdb(), workflow_factory=lambda _device_id: publisher)
    payload = {
        "chapter_id": "chapter-2",
        "account_id": "account-1",
        "device_id": "cloud-1",
        "chapter_number": 2,
        "title": "化工厂深处",
        "content": "正文" * 1000,
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        responses = await asyncio.gather(client.post("/publish", json=payload), client.post("/publish", json=payload))

    assert [response.status_code for response in responses] == [200, 200]
    assert publisher.max_active == 1


@pytest.mark.asyncio
async def test_publish_quarantines_device_after_failed_recovery() -> None:
    publisher = QuarantiningPublisher()
    app = create_app(adb=FakeAdb(), workflow_factory=lambda _device_id: publisher)
    payload = {
        "chapter_id": "chapter-2",
        "account_id": "account-1",
        "device_id": "cloud-1",
        "chapter_number": 2,
        "title": "化工厂深处",
        "content": "正文" * 1000,
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        first = await client.post("/publish", json=payload)
        second = await client.post("/publish", json=payload)

    assert first.status_code == 503
    assert second.json()["detail"] == "device is quarantined and requires recovery"
    assert len(publisher.requests) == 1


@pytest.mark.asyncio
async def test_recover_endpoint_clears_device_quarantine_after_verified_reset() -> None:
    publisher = QuarantiningPublisher()
    app = create_app(adb=FakeAdb(), workflow_factory=lambda _device_id: publisher)
    payload = {
        "chapter_id": "chapter-2",
        "account_id": "account-1",
        "device_id": "cloud-1",
        "chapter_number": 2,
        "title": "化工厂深处",
        "content": "正文" * 1000,
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        await client.post("/publish", json=payload)
        recovered = await client.post("/devices/cloud-1/recover")

    assert recovered.status_code == 200
    assert recovered.json() == {"device_id": "cloud-1", "state": "ready"}
    assert publisher.recovered is True
