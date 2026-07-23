from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Callable, Protocol

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.config import CONFIG_DIR, load_settings
from device_gateway.adb import AdbClient, AdbError
from device_gateway.adb_ui_driver import AdbUiDriver
from device_gateway.device_recovery import DeviceRecoveryError
from device_gateway.fanqie_work_setup import WorkMetadata
from device_gateway.fanqie_workflow import (
    DeviceQuarantinedError,
    FanqiePublishWorkflow,
    PublishChapter,
    PublishResult,
    WorkflowError,
)


class AdbOperations(Protocol):
    async def health(self) -> dict[str, str | bool]: ...

    async def device_state(self, device_id: str) -> str: ...

    async def connect_device(self, device_id: str) -> str: ...


class ChapterPublisher(Protocol):
    async def ensure_work(self, work: WorkMetadata) -> None: ...

    async def publish(self, chapter: PublishChapter) -> PublishResult: ...

    async def recover_device(self) -> None: ...


class PublishRequest(BaseModel):
    chapter_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    device_id: str | None = None
    platform: str | None = None
    chapter_number: int | None = Field(default=None, ge=1)
    title: str | None = None
    content: str | None = None
    work_name: str | None = None
    work_introduction: str | None = None
    work_protagonist: str | None = None
    work_audience: str = "男频"
    work_category: str = "都市脑洞"


def create_app(
    *,
    adb: AdbOperations | None = None,
    default_device_id: str | None = None,
    configured_device_ids: tuple[str, ...] = (),
    workflow_factory: Callable[[str], ChapterPublisher] | None = None,
) -> FastAPI:
    adb_client = adb or AdbClient()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        results = await asyncio.gather(
            *(adb_client.connect_device(device_id) for device_id in configured_device_ids),
            return_exceptions=True,
        )
        app.state.adb_connections = {
            device_id: str(result)
            for device_id, result in zip(configured_device_ids, results, strict=True)
        }
        yield

    app = FastAPI(title="OpenClaw Device Gateway", version="0.1.0", lifespan=lifespan)
    device_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
    quarantined_devices: set[str] = set()

    @app.get("/health")
    async def health() -> dict[str, object]:
        adb_health = await adb_client.health()
        return {"status": "ok" if adb_health.get("available") else "degraded", "adb": adb_health}

    @app.get("/devices/{device_id}")
    async def device(device_id: str) -> dict[str, object]:
        try:
            state = await adb_client.device_state(device_id)
        except AdbError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"device_id": device_id, "state": state, "connected": state == "device"}

    @app.post("/publish")
    async def publish(request: PublishRequest) -> dict[str, str]:
        device_id = request.device_id or default_device_id
        if not device_id:
            raise HTTPException(status_code=503, detail="device_id is required for ADB publishing")
        try:
            state = await adb_client.device_state(device_id)
        except AdbError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if state != "device":
            raise HTTPException(status_code=503, detail=f"device is not connected: {state}")
        if device_id in quarantined_devices:
            raise HTTPException(status_code=503, detail="device is quarantined and requires recovery")
        if workflow_factory is None:
            raise HTTPException(status_code=503, detail="publishing workflow is not configured")
        if request.chapter_number is None or not request.title or not request.content:
            raise HTTPException(status_code=422, detail="chapter_number, title and content are required")
        try:
            async with device_locks[device_id]:
                if device_id in quarantined_devices:
                    raise HTTPException(
                        status_code=503, detail="device is quarantined and requires recovery"
                    )
                workflow = workflow_factory(device_id)
                if request.work_name:
                    if not request.work_introduction or not request.work_protagonist:
                        raise HTTPException(
                            status_code=422,
                            detail="work_introduction and work_protagonist are required with work_name",
                        )
                    await workflow.ensure_work(
                        WorkMetadata(
                            name=request.work_name,
                            introduction=request.work_introduction,
                            protagonist=request.work_protagonist,
                            audience=request.work_audience,
                            category=request.work_category,
                        )
                    )
                result = await workflow.publish(
                    PublishChapter(
                        number=request.chapter_number,
                        title=request.title,
                        content=request.content,
                    )
                )
        except DeviceQuarantinedError as exc:
            quarantined_devices.add(device_id)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except WorkflowError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"chapter_label": result.chapter_label, "status": result.status}

    @app.post("/devices/{device_id}/recover")
    async def recover_device(device_id: str) -> dict[str, str]:
        try:
            state = await adb_client.device_state(device_id)
        except AdbError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if state != "device":
            raise HTTPException(status_code=503, detail=f"device is not connected: {state}")
        if workflow_factory is None:
            raise HTTPException(status_code=503, detail="publishing workflow is not configured")
        try:
            async with device_locks[device_id]:
                await workflow_factory(device_id).recover_device()
        except (WorkflowError, DeviceRecoveryError) as exc:
            quarantined_devices.add(device_id)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        quarantined_devices.discard(device_id)
        return {"device_id": device_id, "state": "ready"}

    return app


load_dotenv(CONFIG_DIR / ".env")
configured_devices = tuple(
    str(item["device_id"])
    for item in load_settings().raw.get("adb", {}).get("devices", [])
    if item.get("device_id")
)
app = create_app(
    default_device_id=os.getenv("HONGSHOUZHI_DEVICE_ID"),
    configured_device_ids=configured_devices,
    workflow_factory=lambda device_id: FanqiePublishWorkflow(
        AdbUiDriver(device_id, pause_seconds=1)
    ),
)
