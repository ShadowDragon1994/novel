from __future__ import annotations

import base64

import pytest

from device_gateway.adb_ui_driver import AdbUiDriver


class FakeAdb:
    def __init__(self, outputs: list[str] | None = None) -> None:
        self.outputs = iter(outputs or [])
        self.commands: list[tuple[str, ...]] = []

    async def run_device(self, device_id: str, *args: str) -> str:
        self.commands.append((device_id, *args))
        if args[:3] == ("shell", "uiautomator", "dump"):
            return next(self.outputs)
        return ""


@pytest.mark.asyncio
async def test_screen_text_extracts_text_and_descriptions() -> None:
    adb = FakeAdb(
        [
            '<?xml version="1.0"?><hierarchy><node text="第2章" content-desc="审核中" '
            'bounds="[0,0][100,100]" /></hierarchy>'
        ]
    )
    driver = AdbUiDriver("cloud-1", adb=adb)

    assert await driver.screen_text() == "第2章\n审核中"


@pytest.mark.asyncio
async def test_tap_description_uses_accessibility_bounds_center() -> None:
    adb = FakeAdb(
        ['<hierarchy><node text="" content-desc="有使用AI" bounds="[72,900][648,1016]" /></hierarchy>']
    )
    driver = AdbUiDriver("cloud-1", adb=adb)

    await driver.tap_description("有使用AI")

    assert adb.commands[-1] == ("cloud-1", "shell", "input", "tap", "360", "958")


@pytest.mark.asyncio
async def test_replace_text_uses_utf8_base64_keyboard_broadcast() -> None:
    adb = FakeAdb()
    driver = AdbUiDriver("cloud-1", adb=adb)

    await driver.replace_text((410, 325), "化工厂深处")

    encoded = base64.b64encode("化工厂深处".encode()).decode()
    assert ("cloud-1", "shell", "am", "broadcast", "-a", "ADB_KEYBOARD_CLEAR_TEXT") in adb.commands
    assert (
        "cloud-1",
        "shell",
        "am",
        "broadcast",
        "-a",
        "ADB_KEYBOARD_INPUT_TEXT",
        "--es",
        "text",
        encoded,
    ) in adb.commands
