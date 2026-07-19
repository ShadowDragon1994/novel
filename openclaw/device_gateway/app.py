from __future__ import annotations

from typing import Protocol

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from device_gateway.adb import AdbClient, AdbError


class AdbOperations(Protocol):
    async def health(self) -> dict[str, str | bool]: ...

    async def device_state(self, device_id: str) -> str: ...


class PublishRequest(BaseModel):
    chapter_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)


def create_app(*, adb: AdbOperations | None = None) -> FastAPI:
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
        try:
            state = await adb_client.device_state(request.device_id)
        except AdbError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if state != "device":
            raise HTTPException(status_code=503, detail=f"device is not connected: {state}")
        raise HTTPException(status_code=503, detail="publishing workflow is not configured")

    return app


app = create_app()
