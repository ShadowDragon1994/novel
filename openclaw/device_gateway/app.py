from __future__ import annotations

import os
from typing import Protocol

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.config import CONFIG_DIR
from device_gateway.adb import AdbClient, AdbError


class AdbOperations(Protocol):
    async def health(self) -> dict[str, str | bool]: ...

    async def device_state(self, device_id: str) -> str: ...


class PublishRequest(BaseModel):
    chapter_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    device_id: str | None = None
    platform: str | None = None
    title: str | None = None
    content: str | None = None


def create_app(*, adb: AdbOperations | None = None, default_device_id: str | None = None) -> FastAPI:
    app = FastAPI(title="OpenClaw Device Gateway", version="0.1.0")
    adb_client = adb or AdbClient()

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
    async def publish(request: PublishRequest) -> None:
        device_id = request.device_id or default_device_id
        if not device_id:
            raise HTTPException(status_code=503, detail="device_id is required for ADB publishing")
        try:
            state = await adb_client.device_state(device_id)
        except AdbError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if state != "device":
            raise HTTPException(status_code=503, detail=f"device is not connected: {state}")
        raise HTTPException(status_code=503, detail="publishing workflow is not configured")

    return app


load_dotenv(CONFIG_DIR / ".env")
app = create_app(default_device_id=os.getenv("HONGSHOUZHI_DEVICE_ID"))
