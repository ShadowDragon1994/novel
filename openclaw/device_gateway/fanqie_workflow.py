from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from device_gateway.device_recovery import DeviceRecoveryError, DeviceRecoveryManager
from device_gateway.ui_coordinates import CoordinateProfile, ResolvedAction, normalize_semantic_text


class WorkflowError(RuntimeError):
    """Raised when the live UI does not match the expected publishing state."""


class DeviceQuarantinedError(WorkflowError):
    """Raised when publishing fails and the device cannot be safely reset."""


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

    async def tap_description_contains(self, description: str) -> None: ...

    async def press_back(self) -> None: ...

    async def scroll_to_top(self) -> None: ...


class FanqiePublishWorkflow:
    def __init__(self, driver: UiDriver, profile: CoordinateProfile | None = None) -> None:
        self.driver = driver
        self.profile = profile or CoordinateProfile.load_default()
        self.recovery = DeviceRecoveryManager(driver)

    async def recover_device(self) -> None:
        await self.recovery.recover()

    def _action(self, state: str, action: str) -> ResolvedAction:
        return self.profile.resolve(state, action, width=self.driver.width, height=self.driver.height)

    async def _tap(self, state: str, action: str) -> str:
        resolved = self._action(state, action)
        if resolved.point is None:
            raise WorkflowError(f"action {state}.{action} has no coordinate")
        await self.driver.tap(resolved.point)
        if not resolved.verify_any:
            return await self.driver.screen_text()
        return await self.driver.wait_for_any(resolved.verify_any)

    async def publish(self, chapter: PublishChapter) -> PublishResult:
        if chapter.number < 1 or not chapter.title.strip() or not chapter.content.strip():
            raise WorkflowError("chapter number, title and content are required")
        platform_title = self._platform_title(chapter.title)
        chapter_label = f"第{chapter.number}章 {platform_title}"
        initial_text = await self.driver.screen_text()
        existing_status = self._existing_status(initial_text, chapter_label)
        if "章节管理" in initial_text and existing_status:
            return PublishResult(chapter_label=chapter_label, status=existing_status)
        if "章节管理" in initial_text and "草稿箱" in initial_text:
            draft_text = initial_text
            if "编辑" not in draft_text or "删除" not in draft_text:
                await self.driver.tap_description_contains("草稿箱")
                draft_text = await self.driver.screen_text()
            normalized_draft = normalize_semantic_text(draft_text)
            chapter_number_label = f"第{chapter.number}章"
            if chapter_number_label in normalized_draft and normalize_semantic_text(
                platform_title
            ) in normalized_draft:
                await self.driver.tap_description_contains(platform_title)
                initial_text = await self.driver.screen_text()
            elif chapter_number_label in normalized_draft:
                raise WorkflowError(
                    f"chapter number {chapter.number} already exists with a different title"
                )
            else:
                await self.driver.tap_description_contains("章节管理")
                initial_text = await self.driver.screen_text()
        normalized_initial = normalize_semantic_text(initial_text)
        normalized_label = normalize_semantic_text(chapter_label)
        if "章节管理" in initial_text and normalized_label in normalized_initial and "草稿" in initial_text:
            await self.driver.tap_description_contains(chapter_label)
            initial_text = await self.driver.screen_text()
        elif "章节管理" in initial_text and f"第{chapter.number}章" in normalized_initial:
            raise WorkflowError(
                f"chapter number {chapter.number} already exists with a different title"
            )

        try:
            if "章节管理" in initial_text:
                editor_text = await self._tap("chapter_list", "start_new_chapter")
            elif self._is_editor(initial_text):
                editor_text = initial_text
            else:
                result = await self._continue_submission(initial_text, chapter_label)
                await self.recovery.recover()
                return result

            if "审核工作时间" in editor_text:
                editor_text = await self._tap("chapter_editor", "dismiss_night_notice")
            await self.driver.scroll_to_top()
            for action_name, value in (
                ("focus_chapter_number", str(chapter.number)),
                ("focus_title", platform_title),
                ("focus_body", chapter.content.strip()),
            ):
                action = self._action("chapter_editor", action_name)
                if action.point is None:
                    raise WorkflowError(f"action chapter_editor.{action_name} has no coordinate")
                await self.driver.replace_text(action.point, value)

            await self.driver.wait_for_any(("已保存到云端",))
            verification_text = await self.driver.screen_text()
            self._validate_saved_content(verification_text, chapter.content)
            next_text = await self._tap("chapter_editor", "next")
            result = await self._continue_submission(next_text, chapter_label)
        except Exception as publish_error:
            try:
                await self.recovery.recover()
            except DeviceRecoveryError as recovery_error:
                raise DeviceQuarantinedError(
                    "publishing failed "
                    f"({publish_error}) and device recovery failed: {recovery_error}"
                ) from recovery_error
            raise
        await self.recovery.recover()
        return result

    async def _continue_submission(self, text: str, chapter_label: str) -> PublishResult:
        for _ in range(8):
            status = self._existing_status(text, chapter_label)
            if status:
                return PublishResult(chapter_label=chapter_label, status=status)
            if "审核中" in text or "已发布" in text:
                raise WorkflowError(f"submitted chapter was not found: {chapter_label}")
            if "检测到您还有错别字未修改" in text:
                text = await self._tap("typo_confirmation", "confirm")
            elif "请选择内容检测方式" in text:
                text = await self._tap("content_detection", "basic_check")
            elif "有使用AI" in text and "未使用AI" in text:
                action = self._action("ai_declaration", "used_ai")
                if not action.selector_description:
                    raise WorkflowError("AI declaration selector is not configured")
                await self.driver.tap_description(action.selector_description)
                text = await self.driver.screen_text()
            elif "发布设置" in text and "确认发布" in text:
                if re.search(r"内容是否使用AI功能\s*是(?:\s|$)", text):
                    text = await self._tap("publish_settings", "confirm_publish")
                else:
                    text = await self._tap("publish_settings", "select_ai_usage")
            elif "确定要提交章节" in text:
                text = await self._tap("final_submission_confirmation", "confirm")
            else:
                raise WorkflowError(f"unsupported Fanqie page state: {text[:200]!r}")
        raise WorkflowError("Fanqie submission exceeded the maximum state transitions")

    @staticmethod
    def _is_editor(text: str) -> bool:
        return "下一步" in text and ("AI工具箱" in text or "已保存到云端" in text or "请输入正文" in text)

    @staticmethod
    def _existing_status(text: str, chapter_label: str) -> str | None:
        if "草稿箱" in text and "编辑" in text and "删除" in text:
            return None
        normalized_text = normalize_semantic_text(text)
        normalized_label = normalize_semantic_text(chapter_label)
        label_index = normalized_text.find(normalized_label)
        if label_index < 0:
            return None
        prefix = normalized_text[:label_index]
        candidates = (
            (prefix.rfind("审核中"), "审核中"),
            (prefix.rfind("已发布"), "已发布"),
        )
        status_index, status = max(candidates, key=lambda item: item[0])
        return status if status_index >= 0 else None

    @staticmethod
    def _platform_title(title: str) -> str:
        stripped = title.strip()
        without_prefix = re.sub(r"^第[^章]{1,12}章[\s:：-]*", "", stripped)
        return without_prefix or stripped

    @staticmethod
    def _validate_saved_content(screen_text: str, content: str) -> None:
        word_counts = [int(value) for value in re.findall(r"(\d+)字", screen_text)]
        if not word_counts:
            raise WorkflowError("saved chapter word count is unavailable")
        expected_length = len("".join(content.split()))
        observed = max(word_counts)
        if observed < max(100, expected_length // 2) or observed > expected_length * 7 // 4:
            raise WorkflowError(
                f"saved chapter word count is outside the expected range: {observed}"
            )
