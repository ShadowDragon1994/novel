from __future__ import annotations

import asyncio
import base64
import re
import xml.etree.ElementTree as ET
from typing import Protocol

from device_gateway.adb import AdbClient, AdbError
from device_gateway.fanqie_workflow import WorkflowError

BOUNDS_PATTERN = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
ADB_KEYBOARD = "com.github.uiautomator/.AdbKeyboard"
UI_DUMP_PATH = "/sdcard/openclaw_ui.xml"


class DeviceCommands(Protocol):
    async def run_device(self, device_id: str, *args: str) -> str: ...


class AdbUiDriver:
    width = 720
    height = 1280

    def __init__(
        self,
        device_id: str,
        *,
        adb: DeviceCommands | None = None,
        pause_seconds: float = 0,
        wait_timeout_seconds: float = 20,
    ) -> None:
        self.device_id = device_id
        self.adb = adb or AdbClient()
        self.pause_seconds = pause_seconds
        self.wait_timeout_seconds = wait_timeout_seconds

    async def _pause(self) -> None:
        if self.pause_seconds:
            await asyncio.sleep(self.pause_seconds)

    async def _hierarchy(self) -> ET.Element:
        await self.adb.run_device(self.device_id, "shell", "uiautomator", "dump", UI_DUMP_PATH)
        output = await self.adb.run_device(self.device_id, "shell", "cat", UI_DUMP_PATH)
        start = output.find("<")
        end = output.rfind("</hierarchy>")
        if start < 0 or end < 0:
            raise WorkflowError("Android UI hierarchy is unavailable")
        try:
            return ET.fromstring(output[start : end + len("</hierarchy>")])
        except ET.ParseError as exc:
            raise WorkflowError("Android UI hierarchy is invalid") from exc

    async def screen_text(self) -> str:
        root = await self._hierarchy()
        values: list[str] = []
        for node in root.iter("node"):
            for key in ("text", "content-desc"):
                value = node.attrib.get(key, "").strip()
                if value and value not in values:
                    values.append(value)
        return "\n".join(values)

    async def wait_for_any(self, labels: tuple[str, ...]) -> str:
        deadline = asyncio.get_running_loop().time() + self.wait_timeout_seconds
        latest = ""
        while asyncio.get_running_loop().time() < deadline:
            latest = await self.screen_text()
            if any(label in latest for label in labels):
                return latest
            await asyncio.sleep(max(self.pause_seconds, 0.25))
        raise WorkflowError(f"timed out waiting for UI labels: {labels!r}; latest={latest[:200]!r}")

    async def tap(self, point: tuple[int, int]) -> None:
        await self.adb.run_device(
            self.device_id, "shell", "input", "tap", str(point[0]), str(point[1])
        )
        await self._pause()

    async def replace_text(self, point: tuple[int, int], value: str) -> None:
        await self.tap(point)
        try:
            await self.adb.run_device(self.device_id, "shell", "ime", "enable", ADB_KEYBOARD)
            await self.adb.run_device(self.device_id, "shell", "ime", "set", ADB_KEYBOARD)
            await self.adb.run_device(
                self.device_id, "shell", "am", "broadcast", "-a", "ADB_KEYBOARD_CLEAR_TEXT"
            )
            encoded = base64.b64encode(value.encode()).decode()
            await self.adb.run_device(
                self.device_id,
                "shell",
                "am",
                "broadcast",
                "-a",
                "ADB_KEYBOARD_INPUT_TEXT",
                "--es",
                "text",
                encoded,
            )
            await self.adb.run_device(
                self.device_id, "shell", "am", "broadcast", "-a", "ADB_KEYBOARD_HIDE"
            )
        except AdbError as exc:
            raise WorkflowError(f"failed to enter text through ADB keyboard: {exc}") from exc
        await self._pause()

    async def tap_description(self, description: str) -> None:
        await self._tap_description(description, exact=True)

    async def tap_description_contains(self, description: str) -> None:
        await self._tap_description(description, exact=False)

    async def _tap_description(self, description: str, *, exact: bool) -> None:
        root = await self._hierarchy()
        for node in root.iter("node"):
            actual = node.attrib.get("content-desc", "")
            if (exact and actual != description) or (not exact and description not in actual):
                continue
            match = BOUNDS_PATTERN.fullmatch(node.attrib.get("bounds", ""))
            if not match:
                break
            left, top, right, bottom = (int(value) for value in match.groups())
            await self.tap(((left + right) // 2, (top + bottom) // 2))
            return
        raise WorkflowError(f"UI description was not found: {description}")

    async def press_back(self) -> None:
        await self.adb.run_device(self.device_id, "shell", "input", "keyevent", "BACK")
        await self._pause()

    async def scroll_to_top(self) -> None:
        for _ in range(12):
            await self.adb.run_device(
                self.device_id,
                "shell",
                "input",
                "touchscreen",
                "swipe",
                "360",
                "400",
                "360",
                "1150",
                "250",
            )
        await self._pause()
