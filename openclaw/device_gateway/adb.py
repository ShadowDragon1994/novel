from __future__ import annotations

import asyncio
import os
import re

DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


class AdbError(RuntimeError):
    """Raised when an ADB command cannot be completed."""


class AdbClient:
    def __init__(self, executable: str | None = None, timeout_seconds: float = 15) -> None:
        self.executable = executable or os.getenv("ADB_PATH") or "adb"
        self.timeout_seconds = timeout_seconds

    async def health(self) -> dict[str, str | bool]:
        try:
            output = await self._run("version")
        except (AdbError, FileNotFoundError) as exc:
            return {"available": False, "error": str(exc)}
        first_line = output.splitlines()[0] if output else "unknown"
        return {"available": True, "version": first_line}

    async def start_server(self) -> str:
        return await self._run("start-server")

    async def device_state(self, device_id: str) -> str:
        if not DEVICE_ID_PATTERN.fullmatch(device_id):
            raise AdbError("invalid device_id")
        return (await self._run("-s", device_id, "get-state")).strip()

    async def connect_device(self, device_id: str) -> str:
        if not DEVICE_ID_PATTERN.fullmatch(device_id):
            raise AdbError("invalid device_id")
        return await self._run("connect", device_id)

    async def run_device(self, device_id: str, *args: str) -> str:
        if not DEVICE_ID_PATTERN.fullmatch(device_id):
            raise AdbError("invalid device_id")
        try:
            return await self._run("-s", device_id, *args)
        except AdbError as exc:
            if not self._is_disconnected_error(exc):
                raise
        await self._run("connect", device_id)
        return await self._run("-s", device_id, *args)

    @staticmethod
    def _is_disconnected_error(exc: AdbError) -> bool:
        detail = str(exc).lower()
        return any(marker in detail for marker in ("error: closed", "device offline", "not found"))

    async def _run(self, *args: str) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                self.executable,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise AdbError(f"ADB executable not found: {self.executable}") from None
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_seconds)
        except TimeoutError:
            process.kill()
            await process.communicate()
            raise AdbError(f"ADB command timed out after {self.timeout_seconds:g}s") from None
        if process.returncode != 0:
            detail = stderr.decode(errors="replace").strip() or "unknown ADB error"
            raise AdbError(detail)
        return stdout.decode(errors="replace").strip()
