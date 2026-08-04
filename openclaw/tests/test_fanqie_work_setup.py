from __future__ import annotations

import pytest

from device_gateway.fanqie_work_setup import FanqieWorkSetupWorkflow, WorkMetadata


class FakeDriver:
    width = 720
    height = 1280

    def __init__(self, screens: list[str]) -> None:
        self.screens = iter(screens)
        self.current = next(self.screens)
        self.tapped: list[str] = []
        self.replacements: list[tuple[tuple[int, int], str]] = []

    async def screen_text(self) -> str:
        return self.current

    async def wait_for_any(self, labels: tuple[str, ...]) -> str:
        if any(label in self.current for label in labels):
            return self.current
        self.current = next(self.screens)
        return self.current

    async def tap_description_contains(self, description: str) -> None:
        self.tapped.append(description)
        self.current = next(self.screens)

    async def tap_description(self, description: str) -> None:
        self.tapped.append(description)
        self.current = next(self.screens)

    async def replace_text(self, point: tuple[int, int], value: str) -> None:
        self.replacements.append((point, value))

    async def press_back(self) -> None:
        self.current = next(self.screens)


@pytest.mark.asyncio
async def test_ensure_work_opens_existing_target_without_creating_duplicate() -> None:
    driver = FakeDriver(["作品 测试修真小说", "章节管理 测试修真小说"])

    await FanqieWorkSetupWorkflow(driver).ensure(
        WorkMetadata("测试修真小说", "作品简介" * 20, "林玄", "男频", "东方仙侠")
    )

    assert driver.tapped == ["测试修真小说"]
    assert driver.replacements == []


@pytest.mark.asyncio
async def test_ensure_work_accepts_bound_chapter_page_when_display_title_changed() -> None:
    driver = FakeDriver(["章节管理 已发布 第1章 平台中已改名的作品"])

    await FanqieWorkSetupWorkflow(driver).ensure(
        WorkMetadata("飞书里的旧书名", "作品简介" * 20, "林玄")
    )

    assert driver.tapped == []
    assert driver.replacements == []


@pytest.mark.asyncio
async def test_ensure_work_creates_first_work_and_enters_chapter_management() -> None:
    driver = FakeDriver(
        [
            "开始创作 去创作",
            "选择创作类型 去写章节 创建书本",
            "新建作品 创建 作品名称 作品简介 主角名 目标读者 作品标签",
            "主角名 主角一 确定",
            "新建作品 创建 作品名称 作品简介 主角名 目标读者 作品标签",
            "新建作品 创建 作品名称 作品简介 主角名 目标读者 作品标签 男频",
            "作品标签 确认 东方仙侠",
            "作品标签 确认 东方仙侠 已选择",
            "新建作品 创建 作品名称 作品简介 主角名 目标读者 作品标签 东方仙侠",
            "作品 测试修真小说",
            "章节管理 测试修真小说",
        ]
    )

    await FanqieWorkSetupWorkflow(driver).ensure(
        WorkMetadata("测试修真小说", "作品简介" * 20, "林玄", "男频", "东方仙侠")
    )

    assert ((300, 700), "测试修真小说") in driver.replacements
    assert ((300, 950), "作品简介" * 20) in driver.replacements
    assert ((530, 390), "林玄") in driver.replacements
    assert driver.tapped[-1] == "测试修真小说"
