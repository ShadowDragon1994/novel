from __future__ import annotations

import pytest

from device_gateway.fanqie_inspiration_workflow import FanqieInspirationWorkflow


class FakeInspirationDriver:
    width = 720
    height = 1280
    wait_timeout_seconds = 1
    pause_seconds = 0

    def __init__(self, screens: list[str]) -> None:
        self.screens = screens
        self.index = 0
        self.taps: list[tuple[int, int]] = []
        self.descriptions: list[str] = []
        self.cold_started = False
        self.back_presses = 0

    async def cold_start_app(self) -> None:
        self.cold_started = True

    async def screen_text(self) -> str:
        return self.screens[min(self.index, len(self.screens) - 1)]

    async def wait_for_any(self, labels: tuple[str, ...]) -> str:
        self.index = min(self.index + 1, len(self.screens) - 1)
        text = await self.screen_text()
        assert any(label in text for label in labels)
        return text

    async def tap(self, point: tuple[int, int]) -> None:
        self.taps.append(point)

    async def tap_description_contains(self, description: str) -> None:
        self.descriptions.append(description)
        if len(description) > 2:
            self.index = min(self.index + 1, len(self.screens) - 1)

    async def press_back(self) -> None:
        self.back_presses += 1


@pytest.mark.asyncio
async def test_open_book_inspiration_from_my_page_uses_semantic_tool_entry() -> None:
    driver = FakeInspirationDriver(
        [
            "消息 作品 活动 数据 我的",
            "打卡日历 常用工具 开书灵感 组队码字 推荐素材 我的",
            "书荒热词 原创作品榜 主编力签 热门故事 脑洞榜 01 游戏 02 全民转职",
        ]
    )

    text = await FanqieInspirationWorkflow(driver, device_id="dev").open_book_inspiration()

    assert "书荒热词" in text
    assert driver.cold_started is True
    assert "我的" in driver.descriptions
    assert "开书灵感" in driver.descriptions


@pytest.mark.asyncio
async def test_collect_returns_snapshot_pages() -> None:
    driver = FakeInspirationDriver(
        [
            "常用工具 开书灵感 我的",
            "书荒热词 原创作品榜 01 游戏 02 系统",
            "书荒热词 原创作品榜 01 游戏 02 系统 03 末世 04 重生",
        ]
    )

    snapshot = await FanqieInspirationWorkflow(driver, device_id="dev").collect(max_scrolls=1)

    assert snapshot.device_id == "dev"
    assert snapshot.pages
    assert "书荒热词" in snapshot.pages[0].text
