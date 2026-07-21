from __future__ import annotations

from typing import Protocol


class DeviceRecoveryError(RuntimeError):
    """Raised when a device cannot be returned to a safe baseline page."""


class RecoveryDriver(Protocol):
    async def screen_text(self) -> str: ...

    async def wait_for_any(self, labels: tuple[str, ...]) -> str: ...

    async def press_back(self) -> None: ...

    async def tap_description(self, description: str) -> None: ...

    async def tap(self, point: tuple[int, int]) -> None: ...


class DeviceRecoveryManager:
    def __init__(self, driver: RecoveryDriver, *, max_back_steps: int = 5) -> None:
        self.driver = driver
        self.max_back_steps = max_back_steps

    async def recover(self) -> None:
        for _ in range(self.max_back_steps):
            text = await self.driver.screen_text()
            if self._is_safe_baseline(text):
                return
            if "新建作品" in text and "关闭" in text:
                await self.driver.tap((64, 174))
                continue
            if "发布设置" in text and "关闭" in text:
                await self.driver.tap((64, 174))
                continue
            if "确认是否退出编辑" in text and "确定" in text:
                await self.driver.tap_description("确定")
                continue
            if "放弃编辑" in text and "保存草稿" in text:
                await self.driver.tap_description("保存草稿")
                continue
            if ("下一步" in text or "AI工具箱" in text) and "已保存到云端" not in text:
                await self.driver.wait_for_any(("已保存到云端",))
            await self.driver.press_back()
        if self._is_safe_baseline(await self.driver.screen_text()):
            return
        raise DeviceRecoveryError("device did not return to chapter management")

    @staticmethod
    def _is_safe_baseline(text: str) -> bool:
        return "章节管理" in text or ("开始创作" in text and "去创作" in text)
