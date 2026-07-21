from __future__ import annotations

import pytest

from device_gateway.device_recovery import DeviceRecoveryError, DeviceRecoveryManager


class FakeRecoveryDriver:
    def __init__(self, screens: list[str]) -> None:
        self.screens = iter(screens)
        self.current = next(self.screens)
        self.back_presses = 0

    async def screen_text(self) -> str:
        return self.current

    async def wait_for_any(self, labels: tuple[str, ...]) -> str:
        return self.current

    async def press_back(self) -> None:
        self.back_presses += 1
        self.current = next(self.screens)


@pytest.mark.asyncio
async def test_recovery_returns_saved_editor_to_chapter_management() -> None:
    driver = FakeRecoveryDriver(["已保存到云端 3050字 下一步", "章节管理"])

    await DeviceRecoveryManager(driver).recover()

    assert driver.back_presses == 1


@pytest.mark.asyncio
async def test_recovery_quarantines_device_when_baseline_cannot_be_reached() -> None:
    driver = FakeRecoveryDriver(["未知页面", "未知页面", "未知页面"])

    with pytest.raises(DeviceRecoveryError, match="chapter management"):
        await DeviceRecoveryManager(driver, max_back_steps=2).recover()
