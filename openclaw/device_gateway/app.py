from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from typing import Callable, Protocol

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.config import CONFIG_DIR
from device_gateway.adb import AdbClient, AdbError
from device_gateway.adb_ui_driver import AdbUiDriver
from device_gateway.device_recovery import DeviceRecoveryError
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


class ChapterPublisher(Protocol):
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


def create_app(
    *,
    adb: AdbOperations | None = None,
    default_device_id: str | None = None,
    workflow_factory: Callable[[str], ChapterPublisher] | None = None,
) -> FastAPI:
    app = FastAPI(title="OpenClaw Device Gateway", version="0.1.0")
    adb_client = adb or AdbClient()
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
                result = await workflow_factory(device_id).publish(
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
app = create_app(
    default_device_id=os.getenv("HONGSHOUZHI_DEVICE_ID"),
    workflow_factory=lambda device_id: FanqiePublishWorkflow(
        AdbUiDriver(device_id, pause_seconds=1)
    ),
)
