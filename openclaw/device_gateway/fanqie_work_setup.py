from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from device_gateway.fanqie_workflow import WorkflowError


@dataclass(frozen=True)
class WorkMetadata:
    name: str
    introduction: str
    protagonist: str
    audience: str = "男频"
    category: str = "都市脑洞"


class WorkSetupDriver(Protocol):
    async def screen_text(self) -> str: ...

    async def wait_for_any(self, labels: tuple[str, ...]) -> str: ...

    async def tap_description(self, description: str) -> None: ...

    async def tap_description_contains(self, description: str) -> None: ...

    async def replace_text(self, point: tuple[int, int], value: str) -> None: ...

    async def press_back(self) -> None: ...


class FanqieWorkSetupWorkflow:
    def __init__(self, driver: WorkSetupDriver) -> None:
        self.driver = driver

    async def ensure(self, work: WorkMetadata) -> None:
        self._validate(work)
        text = await self.driver.screen_text()
        # Each configured cloud device is bound to exactly one account/work.  Once
        # Fanqie is already on that work's chapter-management page, creating or
        # searching for a title is both unnecessary and dangerous (the Feishu
        # display title can lag behind a title changed in Fanqie).
        if "章节管理" in text:
            return
        if "下一步" in text and "关闭" in text:
            await self.driver.press_back()
            text = await self.driver.screen_text()
        if work.name in text:
            await self.driver.tap_description_contains(work.name)
            await self.driver.wait_for_any(("章节管理",))
            return
        if "开始创作" not in text or "去创作" not in text:
            raise WorkflowError(f"cannot ensure work from current Fanqie page: {text[:200]!r}")

        await self.driver.tap_description_contains("去创作")
        await self.driver.wait_for_any(("选择创作类型",))
        await self.driver.tap_description_contains("创建书本")
        await self.driver.wait_for_any(("新建作品", "作品名称"))

        await self.driver.replace_text((300, 700), work.name)
        await self.driver.replace_text((300, 950), work.introduction)
        await self.driver.tap_description_contains("请输入主角名")
        await self.driver.wait_for_any(("主角一", "主角名"))
        await self.driver.replace_text((530, 390), work.protagonist)
        await self.driver.tap_description("确定")
        await self.driver.wait_for_any(("目标读者",))
        await self.driver.tap_description(work.audience)
        await self.driver.tap_description_contains("作品标签")
        await self.driver.wait_for_any(("作品标签", "主分类"))
        await self.driver.tap_description(work.category)
        await self.driver.tap_description("确认")
        await self.driver.wait_for_any(("新建作品", "创建"))
        await self.driver.tap_description("创建")
        await self.driver.wait_for_any((work.name,))
        await self.driver.tap_description_contains(work.name)
        await self.driver.wait_for_any(("章节管理",))

    @staticmethod
    def _validate(work: WorkMetadata) -> None:
        if not 1 <= len(work.name.strip()) <= 15:
            raise WorkflowError("work name must contain 1-15 characters")
        if len(work.introduction.strip()) < 50:
            raise WorkflowError("work introduction must contain at least 50 characters")
        if not work.protagonist.strip():
            raise WorkflowError("work protagonist is required")
