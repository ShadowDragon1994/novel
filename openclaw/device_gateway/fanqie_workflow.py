from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from device_gateway.ui_coordinates import CoordinateProfile, ResolvedAction


class WorkflowError(RuntimeError):
    """Raised when the live UI does not match the expected publishing state."""


@dataclass(frozen=True)
class PublishChapter:
    number: int
    title: str
    content: str


@dataclass(frozen=True)
class PublishResult:
    chapter_label: str
    status: str


class UiDriver(Protocol):
    width: int
    height: int

    async def screen_text(self) -> str: ...

    async def wait_for_any(self, labels: tuple[str, ...]) -> str: ...

    async def tap(self, point: tuple[int, int]) -> None: ...

    async def replace_text(self, point: tuple[int, int], value: str) -> None: ...

    async def tap_description(self, description: str) -> None: ...


class FanqiePublishWorkflow:
    def __init__(self, driver: UiDriver, profile: CoordinateProfile | None = None) -> None:
        self.driver = driver
        self.profile = profile or CoordinateProfile.load_default()

    def _action(self, state: str, action: str) -> ResolvedAction:
        return self.profile.resolve(state, action, width=self.driver.width, height=self.driver.height)

    async def _tap(self, state: str, action: str) -> str:
        resolved = self._action(state, action)
        if resolved.point is None:
            raise WorkflowError(f"action {state}.{action} has no coordinate")
        await self.driver.tap(resolved.point)
        text = await self.driver.screen_text()
        if resolved.verify_any and not any(label in text for label in resolved.verify_any):
            raise WorkflowError(f"unexpected UI after {state}.{action}: expected {resolved.verify_any!r}")
        return text

    async def publish(self, chapter: PublishChapter) -> PublishResult:
        if chapter.number < 1 or not chapter.title.strip() or not chapter.content.strip():
            raise WorkflowError("chapter number, title and content are required")
        if "章节管理" not in await self.driver.screen_text():
            raise WorkflowError("workflow must start from chapter management")

        editor_text = await self._tap("chapter_list", "start_new_chapter")
        if "审核工作时间" in editor_text:
            await self._tap("chapter_editor", "dismiss_night_notice")

        for action_name, value in (
            ("focus_chapter_number", str(chapter.number)),
            ("focus_title", chapter.title.strip()),
            ("focus_body", chapter.content.strip()),
        ):
            action = self._action("chapter_editor", action_name)
            if action.point is None:
                raise WorkflowError(f"action chapter_editor.{action_name} has no coordinate")
            await self.driver.replace_text(action.point, value)

        saved_text = await self.driver.wait_for_any(("已保存到云端",))
        if "已保存到云端" not in saved_text:
            raise WorkflowError("chapter content was not saved to cloud")

        await self._tap("chapter_editor", "next")
        await self._tap("typo_confirmation", "confirm")
        await self._tap("content_detection", "basic_check")
        await self._tap("publish_settings", "select_ai_usage")

        ai_action = self._action("ai_declaration", "used_ai")
        if not ai_action.selector_description:
            raise WorkflowError("AI declaration selector is not configured")
        await self.driver.tap_description(ai_action.selector_description)
        ai_text = await self.driver.screen_text()
        if "内容是否使用AI功能" not in ai_text or "是" not in ai_text:
            raise WorkflowError("AI usage declaration was not saved")

        await self._tap("publish_settings", "confirm_publish")
        terminal_text = await self._tap("final_submission_confirmation", "confirm")
        chapter_label = f"第{chapter.number}章 {chapter.title.strip()}"
        if chapter_label not in terminal_text or "审核中" not in terminal_text:
            raise WorkflowError(f"submitted chapter was not found: {chapter_label}")
        return PublishResult(chapter_label=chapter_label, status="审核中")
