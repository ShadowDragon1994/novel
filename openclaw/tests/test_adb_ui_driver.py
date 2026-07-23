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
        if args[:2] == ("shell", "cat"):
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
async def test_tap_description_contains_uses_matching_accessibility_node() -> None:
    adb = FakeAdb(
        ['<hierarchy><node text="" content-desc="第2章 化工厂深处\n草稿" bounds="[72,900][648,1016]" /></hierarchy>']
    )
    driver = AdbUiDriver("cloud-1", adb=adb)

    await driver.tap_description_contains("第2章 化工厂深处")

    assert adb.commands[-1] == ("cloud-1", "shell", "input", "tap", "360", "958")


@pytest.mark.asyncio
async def test_tap_description_contains_ignores_spacing_and_colon_variants() -> None:
    adb = FakeAdb(
        ['<hierarchy><node text="" content-desc="第​2​章：化工厂深处\n草稿" bounds="[72,900][648,1016]" /></hierarchy>']
    )
    driver = AdbUiDriver("cloud-1", adb=adb)

    await driver.tap_description_contains("第2章 化工厂深处")

    assert adb.commands[-1] == ("cloud-1", "shell", "input", "tap", "360", "958")


@pytest.mark.asyncio
async def test_tap_description_right_contains_avoids_center_info_icon() -> None:
    adb = FakeAdb(
        ['<hierarchy><node text="" content-desc="内容是否使用AI功能\n请设置" '
         'bounds="[72,522][648,650]" /></hierarchy>']
    )
    driver = AdbUiDriver("cloud-1", adb=adb)

    await driver.tap_description_right_contains("内容是否使用AI功能")

    assert adb.commands[-1] == ("cloud-1", "shell", "input", "tap", "620", "586")


@pytest.mark.asyncio
async def test_replace_text_uses_utf8_base64_keyboard_broadcast() -> None:
    adb = FakeAdb()
    driver = AdbUiDriver("cloud-1", adb=adb)

    await driver.replace_text((410, 325), "化工厂深处")

    encoded = base64.b64encode("化工厂深处".encode()).decode()
    assert (
        "cloud-1",
        "shell",
        "ime",
        "set",
        "com.android.adbkeyboard/.AdbIME",
    ) in adb.commands
    assert ("cloud-1", "shell", "am", "broadcast", "-a", "ADB_CLEAR_TEXT") in adb.commands
    assert (
        "cloud-1",
        "shell",
        "am",
        "broadcast",
        "-a",
        "ADB_INPUT_B64",
        "--es",
        "msg",
        encoded,
    ) in adb.commands


@pytest.mark.asyncio
async def test_replace_numeric_text_clears_existing_value_before_native_adb_input() -> None:
    adb = FakeAdb()
    driver = AdbUiDriver("cloud-1", adb=adb)

    await driver.replace_text((145, 325), "1")

    move_to_end = ("cloud-1", "shell", "input", "keyevent", "KEYCODE_MOVE_END")
    delete = ("cloud-1", "shell", "input", "keyevent", "KEYCODE_DEL")
    enter_value = ("cloud-1", "shell", "input", "text", "1")
    assert move_to_end in adb.commands
    assert adb.commands.count(delete) == 12
    assert enter_value in adb.commands
    assert adb.commands.index(move_to_end) < adb.commands.index(delete) < adb.commands.index(enter_value)
    assert ("cloud-1", "shell", "am", "broadcast", "-a", "ADB_CLEAR_TEXT") not in adb.commands
    assert not any(command[2:4] == ("ime", "set") for command in adb.commands)
