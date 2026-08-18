from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from device_gateway.fanqie_workflow import WorkflowError
from device_gateway.ui_coordinates import normalize_semantic_text


class InspirationDriver(Protocol):
    width: int
    height: int

    async def cold_start_app(self) -> None: ...

    async def screen_text(self) -> str: ...

    async def wait_for_any(self, labels: tuple[str, ...]) -> str: ...

    async def tap(self, point: tuple[int, int]) -> None: ...

    async def tap_description_contains(self, description: str) -> None: ...

    async def press_back(self) -> None: ...


@dataclass(frozen=True)
class InspirationPage:
    name: str
    text: str
    collected_at: str
    scroll_index: int = 0


@dataclass(frozen=True)
class InspirationSnapshot:
    device_id: str
    collected_at: str
    pages: list[InspirationPage] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def write_json(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


class FanqieInspirationWorkflow:
    """Navigate Fanqie Writer Assistant to 我的 → 常用工具 → 开书灵感 and collect text."""

    # 720x1280 reference coordinates from the supplied screenshot.
    MY_TAB_RATIO = (0.867, 0.956)
    BOOK_INSPIRATION_RATIO = (0.169, 0.645)
    COMMON_TOOLS_MORE_RATIO = (0.70, 0.315)

    def __init__(self, driver: InspirationDriver, *, device_id: str = "") -> None:
        self.driver = driver
        self.device_id = device_id

    async def collect(self, *, max_scrolls: int = 3) -> InspirationSnapshot:
        await self.open_book_inspiration()
        pages = [await self._capture_page("开书灵感", 0)]
        for index in range(1, max_scrolls + 1):
            await self._scroll_down()
            text = await self.driver.screen_text()
            if normalize_semantic_text(text) == normalize_semantic_text(pages[-1].text):
                break
            pages.append(InspirationPage("开书灵感", text, datetime.now().isoformat(), index))
        return InspirationSnapshot(self.device_id, datetime.now().isoformat(), pages)

    async def open_book_inspiration(self) -> str:
        await self.open_my_page()
        text = await self.driver.screen_text()
        if "开书灵感" not in text and "常用工具" in text:
            try:
                await self.driver.tap_description_contains("常用工具")
                text = await self.driver.wait_for_any(("开书灵感", "推荐素材", "组队码字"))
            except WorkflowError:
                await self.driver.tap(self._point(self.COMMON_TOOLS_MORE_RATIO))
                text = await self.driver.wait_for_any(("开书灵感", "推荐素材", "组队码字"))
        labels = ("书荒热词", "原创作品榜", "主编力签", "热门故事", "脑洞榜", "传统榜")
        # Prefer the Flutter semantics because the tool card can shift when the
        # tools carousel changes. The coordinate is only a fallback for semantic
        # dump failures on some cloud phones.
        try:
            await self.driver.tap_description_contains("开书灵感")
            return await self._wait_for_inspiration_list(labels)
        except WorkflowError:
            await self.open_my_page()
            await self.driver.tap(self._point(self.BOOK_INSPIRATION_RATIO))
            return await self._wait_for_inspiration_list(labels)

    async def _wait_for_inspiration_list(self, labels: tuple[str, ...]) -> str:
        deadline = asyncio.get_running_loop().time() + getattr(self.driver, "wait_timeout_seconds", 30)
        latest = ""
        while asyncio.get_running_loop().time() < deadline:
            latest = await self.driver.screen_text()
            if any(label in latest for label in labels) and self._has_rank_items(latest):
                return latest
            if self._is_article_or_classroom_page(latest):
                await self.driver.press_back()
                await asyncio.sleep(1.0)
                continue
            await asyncio.sleep(max(getattr(self.driver, "pause_seconds", 0.5), 0.5))
        raise WorkflowError(f"cannot open Fanqie inspiration list: {latest[:200]!r}")

    @staticmethod
    def _is_article_or_classroom_page(text: str) -> bool:
        return any(marker in text for marker in ("???", "??", "????", "??????", "????", "????"))

    @staticmethod
    def _has_rank_items(text: str) -> bool:
        return re.search(r"(?<!\d)0[1-5](?!\d)", text) is not None

    async def open_my_page(self) -> str:
        await self.driver.cold_start_app()
        text = await self._return_to_bottom_nav(await self.driver.screen_text())
        if self._is_my_page(text):
            return text
        for _ in range(6):
            # Prefer a fixed bottom-tab tap after the page has been reset to a
            # top-level page. This avoids content-desc ambiguity on restored
            # secondary pages such as ?催更?.
            await self.driver.tap(self._point(self.MY_TAB_RATIO))
            await asyncio.sleep(0.8)
            text = await self.driver.screen_text()
            if self._is_my_page(text):
                return text
            try:
                await self.driver.tap_description_contains("我的")
                text = await self.driver.wait_for_any(("常用工具", "打卡日历", "本周任务", "开书灵感", "我的"))
            except WorkflowError:
                text = await self._return_to_bottom_nav(await self.driver.screen_text())
                continue
            if self._is_my_page(text):
                return text
        raise WorkflowError(f"cannot open Fanqie 我的 page: {text[:200]!r}")

    async def _return_to_bottom_nav(self, text: str) -> str:
        """Leave restored secondary pages and arrive at any top-level tab.

        Fanqie often cold-starts into the last opened secondary page. The
        historical ?催更? page responds reliably to the top-left back icon,
        while some pages only respond to Android BACK. Try both and verify by
        reading the hierarchy after every action instead of trusting a wait.
        """
        if self._has_bottom_nav(text) or self._is_my_page(text):
            return text
        for _ in range(7):
            try:
                await self.driver.press_back()
            except AttributeError:
                pass
            await asyncio.sleep(0.8)
            text = await self.driver.screen_text()
            if self._has_bottom_nav(text) or self._is_my_page(text):
                return text
            await self.driver.tap((56, 96))
            await asyncio.sleep(0.8)
            text = await self.driver.screen_text()
            if self._has_bottom_nav(text) or self._is_my_page(text):
                return text
        return text

    async def _capture_page(self, name: str, scroll_index: int) -> InspirationPage:
        return InspirationPage(name, await self.driver.screen_text(), datetime.now().isoformat(), scroll_index)

    async def _scroll_down(self) -> None:
        adb = getattr(self.driver, "adb", None)
        device_id = getattr(self.driver, "device_id", self.device_id)
        if adb and device_id:
            await adb.run_device(
                device_id,
                "shell",
                "input",
                "touchscreen",
                "swipe",
                "360",
                "1050",
                "360",
                "360",
                "450",
            )
            await asyncio.sleep(getattr(self.driver, "pause_seconds", 0.5) or 0.5)
            return
        await asyncio.sleep(0)

    def _point(self, ratio: tuple[float, float]) -> tuple[int, int]:
        return int(self.driver.width * ratio[0]), int(self.driver.height * ratio[1])

    @staticmethod
    def _is_my_page(text: str) -> bool:
        normalized = normalize_semantic_text(text)
        return ("常用工具" in normalized and "打卡日历" in normalized) or "开书灵感" in normalized

    @staticmethod
    def _has_bottom_nav(text: str) -> bool:
        normalized = normalize_semantic_text(text)
        return all(label in normalized for label in ("消息", "作品")) and "我的" in normalized
