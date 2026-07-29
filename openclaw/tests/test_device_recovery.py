from __future__ import annotations

import pytest

from device_gateway.device_recovery import DeviceRecoveryError, DeviceRecoveryManager


class FakeRecoveryDriver:
    def __init__(self, screens: list[str]) -> None:
        self.screens = iter(screens)
        self.current = next(self.screens)
        self.back_presses = 0
        self.descriptions: list[str] = []
        self.taps: list[tuple[int, int]] = []

    async def screen_text(self) -> str:
        return self.current

    async def wait_for_any(self, labels: tuple[str, ...]) -> str:
        return self.current

    async def press_back(self) -> None:
        self.back_presses += 1
        self.current = next(self.screens)

    async def tap_description(self, description: str) -> None:
        self.descriptions.append(description)
        self.current = next(self.screens)

    async def tap(self, point: tuple[int, int]) -> None:
        self.taps.append(point)
        self.current = next(self.screens)


@pytest.mark.asyncio
async def test_recovery_returns_saved_editor_to_chapter_management() -> None:
    driver = FakeRecoveryDriver(["已保存到云端 3050字 下一步", "章节管理"])

    await DeviceRecoveryManager(driver).recover()

    assert driver.back_presses == 1


@pytest.mark.asyncio
async def test_recovery_accepts_short_saved_label_from_revision_editor() -> None:
    driver = FakeRecoveryDriver(["已保存 3050字 下一步", "章节管理"])

    await DeviceRecoveryManager(driver).recover()

    assert driver.back_presses == 1


@pytest.mark.asyncio
async def test_recovery_accepts_zero_width_characters_in_chapter_management() -> None:
    driver = FakeRecoveryDriver(["章\u200b节\u200b管\u200b理 草稿箱"])

    await DeviceRecoveryManager(driver).recover()

    assert driver.back_presses == 0


@pytest.mark.asyncio
async def test_recovery_quarantines_device_when_baseline_cannot_be_reached() -> None:
    driver = FakeRecoveryDriver(["未知页面", "未知页面", "未知页面"])

    with pytest.raises(DeviceRecoveryError, match="chapter management"):
        await DeviceRecoveryManager(driver, max_back_steps=2).recover()


@pytest.mark.asyncio
async def test_recovery_confirms_exit_from_cloud_saved_editor() -> None:
    driver = FakeRecoveryDriver(
        [
            "已保存到云端 3050字 下一步",
            "确认是否退出编辑？ 取消 确定",
            "放弃编辑 保存草稿 取消",
            "章节管理",
        ]
    )

    await DeviceRecoveryManager(driver).recover()

    assert driver.descriptions == ["确定", "保存草稿"]


@pytest.mark.asyncio
async def test_recovery_closes_publish_settings_before_saving_draft() -> None:
    driver = FakeRecoveryDriver(
        [
            "发布设置 内容是否使用AI功能 请设置 确认发布 关闭",
            "已保存到云端 3050字 下一步",
            "确认是否退出编辑？ 取消 确定",
            "放弃编辑 保存草稿 取消",
            "章节管理",
        ]
    )

    await DeviceRecoveryManager(driver).recover()

    assert driver.taps == [(64, 174)]
    assert driver.descriptions == ["确定", "保存草稿"]


@pytest.mark.asyncio
async def test_recovery_closes_new_work_form_to_safe_creation_page() -> None:
    driver = FakeRecoveryDriver(
        [
            "新建作品 创建 作品名称 作品简介 关闭",
            "开始创作 开始你的创作之旅 去创作",
        ]
    )

    await DeviceRecoveryManager(driver).recover()

    assert driver.taps == [(64, 174)]
    assert driver.back_presses == 0
