from __future__ import annotations

import pytest

from device_gateway.fanqie_workflow import FanqiePublishWorkflow, PublishChapter, WorkflowError


class FakeUiDriver:
    width = 720
    height = 1280

    def __init__(self, screens: list[str]) -> None:
        self.screens = iter(screens)
        self.current = next(self.screens)
        self.taps: list[tuple[int, int]] = []
        self.replacements: list[tuple[tuple[int, int], str]] = []
        self.descriptions: list[str] = []
        self.containing_descriptions: list[str] = []
        self.right_containing_descriptions: list[str] = []
        self.back_presses = 0
        self.scrolled_to_top = 0

    async def screen_text(self) -> str:
        return self.current

    async def wait_for_any(self, labels: tuple[str, ...]) -> str:
        if any(label in self.current for label in labels):
            return self.current
        self.current = next(self.screens)
        return self.current

    async def tap(self, point: tuple[int, int]) -> None:
        self.taps.append(point)
        self.current = next(self.screens)

    async def replace_text(self, point: tuple[int, int], value: str) -> None:
        self.replacements.append((point, value))

    async def tap_description(self, description: str) -> None:
        self.descriptions.append(description)
        self.current = next(self.screens)

    async def tap_description_contains(self, description: str) -> None:
        self.containing_descriptions.append(description)
        self.current = next(self.screens)

    async def tap_description_right_contains(self, description: str) -> None:
        self.right_containing_descriptions.append(description)
        self.current = next(self.screens)

    async def press_back(self) -> None:
        self.back_presses += 1
        self.current = next(self.screens)

    async def scroll_to_top(self) -> None:
        self.scrolled_to_top += 1


@pytest.mark.asyncio
async def test_publish_reaches_exact_chapter_review_state() -> None:
    driver = FakeUiDriver(
        [
            "章节管理",
            "审核工作时间是7:00-24:00 请输入正文 下一步",
            "请输入正文 下一步",
            "第 2 章 化工厂深处 正文正文正文正文正文正文 已保存到云端 3200字 下一步",
            "检测到您还有错别字未修改，是否确认提交？",
            "请选择内容检测方式",
            "发布设置 确认发布 内容是否使用AI功能 请设置",
            "内容是否使用AI功能 有使用AI 未使用AI",
            "发布设置 确认发布 内容是否使用AI功能 是",
            "确定要提交章节？",
            "章节管理 审核中 第2章 化工厂深处",
        ]
    )
    workflow = FanqiePublishWorkflow(driver)

    result = await workflow.publish(PublishChapter(number=2, title="化工厂深处", content="正文" * 1000))

    assert result.status == "审核中"
    assert result.chapter_label == "第2章 化工厂深处"
    assert ((145, 325), "2") in driver.replacements
    assert ((410, 325), "化工厂深处") in driver.replacements
    assert driver.descriptions == ["下一步", "有使用AI"]
    assert driver.back_presses == 0
    assert driver.scrolled_to_top == 1


@pytest.mark.asyncio
async def test_publish_rejects_wrong_terminal_chapter() -> None:
    driver = FakeUiDriver(
        [
            "章节管理",
            "请输入正文 下一步",
            "第 2 章 化工厂深处 正文正文正文正文正文正文 已保存到云端 3200字 下一步",
            "检测到您还有错别字未修改，是否确认提交？",
            "请选择内容检测方式",
            "发布设置 确认发布 内容是否使用AI功能 请设置",
            "内容是否使用AI功能 有使用AI 未使用AI",
            "发布设置 确认发布 内容是否使用AI功能 是",
            "确定要提交章节？",
            "章节管理 审核中 第1章 灵气复苏",
        ]
    )
    workflow = FanqiePublishWorkflow(driver)

    with pytest.raises(WorkflowError, match="第2章 化工厂深处"):
        await workflow.publish(PublishChapter(number=2, title="化工厂深处", content="正文" * 1000))


@pytest.mark.asyncio
async def test_publish_reconciles_existing_submitted_chapter_without_creating_duplicate() -> None:
    driver = FakeUiDriver(["章节管理 审核中 第2章 化工厂深处"])
    workflow = FanqiePublishWorkflow(driver)

    result = await workflow.publish(PublishChapter(number=2, title="化工厂深处", content="正文" * 1000))

    assert result.status == "审核中"
    assert driver.taps == []
    assert driver.replacements == []


@pytest.mark.asyncio
async def test_publish_uses_status_associated_with_target_chapter() -> None:
    driver = FakeUiDriver(
        ["章节管理 审核中 第2章 化工厂深处 已发布 第1章 灵气复苏"]
    )

    result = await FanqiePublishWorkflow(driver).publish(
        PublishChapter(number=2, title="化工厂深处", content="正文" * 1000)
    )

    assert result.status == "审核中"


@pytest.mark.asyncio
async def test_publish_strips_redundant_chapter_prefix_from_platform_title() -> None:
    driver = FakeUiDriver(["章节管理 审核中 第2章 化工厂深处"])

    result = await FanqiePublishWorkflow(driver).publish(
        PublishChapter(number=2, title="第二章：化工厂深处", content="正文" * 1000)
    )

    assert result.chapter_label == "第2章 化工厂深处"


@pytest.mark.asyncio
async def test_publish_resumes_cloud_saved_editor_and_returns_to_chapter_list() -> None:
    driver = FakeUiDriver(
        [
            "第 2 章 化工厂深处 正文正文正文正文正文正文 已保存到云端 3050字 下一步 AI工具箱",
            "检测到您还有错别字未修改，是否确认提交？",
            "请选择内容检测方式",
            "发布设置 确认发布 内容是否使用AI功能 请设置",
            "内容是否使用AI功能 有使用AI 未使用AI",
            "发布设置 确认发布 内容是否使用AI功能 是",
            "确定要提交章节？",
            "章节管理 审核中 第2章 化工厂深处",
        ]
    )
    workflow = FanqiePublishWorkflow(driver)

    result = await workflow.publish(PublishChapter(number=2, title="化工厂深处", content="正文" * 1000))

    assert result.status == "审核中"
    assert driver.scrolled_to_top == 1
    assert ((145, 325), "2") in driver.replacements
    assert driver.descriptions[0] == "下一步"
    assert (632, 1064) not in driver.taps


@pytest.mark.asyncio
async def test_publish_opens_existing_draft_instead_of_creating_duplicate() -> None:
    driver = FakeUiDriver(
        [
            "章节管理 草稿箱 审核中 第2章 化工厂深处 编辑 删除",
            "第 2 章 化工厂深处 正文正文正文正文正文正文 已保存到云端 3050字 下一步 AI工具箱",
            "检测到您还有错别字未修改，是否确认提交？",
            "请选择内容检测方式",
            "发布设置 确认发布 内容是否使用AI功能 请设置",
            "内容是否使用AI功能 有使用AI 未使用AI",
            "发布设置 确认发布 内容是否使用AI功能 是",
            "确定要提交章节？",
            "章节管理 审核中 第2章 化工厂深处",
        ]
    )

    await FanqiePublishWorkflow(driver).publish(
        PublishChapter(number=2, title="化工厂深处", content="正文" * 1000)
    )

    assert driver.containing_descriptions == ["化工厂深处"]
    assert (632, 1064) not in driver.taps


@pytest.mark.asyncio
async def test_publish_checks_draft_tab_and_opens_matching_draft() -> None:
    driver = FakeUiDriver(
        [
            "章节管理 草稿箱",
            "草稿箱 第2章 第二章：化工厂深处 3050字 编辑 删除",
            "请输入正文 下一步 AI工具箱",
            "第 2 章 化工厂深处 正文正文正文正文正文正文 已保存到云端 3050字 下一步 AI工具箱",
            "检测到您还有错别字未修改，是否确认提交？",
            "请选择内容检测方式",
            "发布设置 确认发布 内容是否使用AI功能 请设置",
            "内容是否使用AI功能 有使用AI 未使用AI",
            "发布设置 确认发布 内容是否使用AI功能 是",
            "确定要提交章节？",
            "章节管理 审核中 第2章 化工厂深处",
        ]
    )

    await FanqiePublishWorkflow(driver).publish(
        PublishChapter(number=2, title="第二章：化工厂深处", content="正文" * 1000)
    )

    assert driver.containing_descriptions[:2] == ["草稿箱", "化工厂深处"]
    assert (632, 1064) not in driver.taps


@pytest.mark.asyncio
async def test_publish_resumes_matching_draft_with_missing_chapter_number() -> None:
    driver = FakeUiDriver(
        [
            "章节管理 草稿箱",
            "草稿箱 第 章 守夜人觉醒 2932字 编辑 删除",
            "请输入正文 下一步 AI工具箱",
            "第 1 章 守夜人觉醒 正文正文正文正文正文正文 已保存到云端 2932字 下一步 AI工具箱",
            "请选择内容检测方式",
            "发布设置 确认发布 内容是否使用AI功能 请设置",
            "内容是否使用AI功能 有使用AI 未使用AI",
            "发布设置 确认发布 内容是否使用AI功能 是",
            "确定要提交章节？",
            "章节管理 审核中 第1章 守夜人觉醒",
        ]
    )

    result = await FanqiePublishWorkflow(driver).publish(
        PublishChapter(number=1, title="第一章：守夜人觉醒", content="正文" * 1000)
    )

    assert result.status == "审核中"
    assert driver.containing_descriptions[:2] == ["草稿箱", "守夜人觉醒"]
    assert (632, 1064) not in driver.taps


@pytest.mark.asyncio
async def test_publish_stops_when_chapter_number_belongs_to_different_title() -> None:
    driver = FakeUiDriver(["章节管理 草稿 第2章 另一个标题"])

    with pytest.raises(WorkflowError, match="chapter number 2 already exists"):
        await FanqiePublishWorkflow(driver).publish(
            PublishChapter(number=2, title="化工厂深处", content="正文" * 1000)
        )

    assert driver.taps == []


def test_saved_content_validation_rejects_truncated_body() -> None:
    with pytest.raises(WorkflowError, match="word count"):
        FanqiePublishWorkflow._validate_saved_content("已保存到云端 20字", "正文" * 1000)


@pytest.mark.asyncio
async def test_publish_allows_content_detection_without_typo_confirmation() -> None:
    driver = FakeUiDriver(
        [
            "第 2 章 化工厂深处 正文正文正文正文正文正文 已保存到云端 3050字 下一步 AI工具箱",
            "请选择内容检测方式",
            "发布设置 确认发布 内容是否使用AI功能 请设置",
            "内容是否使用AI功能 有使用AI 未使用AI",
            "发布设置 确认发布 内容是否使用AI功能 是",
            "确定要提交章节？",
            "章节管理 审核中 第2章 化工厂深处",
        ]
    )

    result = await FanqiePublishWorkflow(driver).publish(
        PublishChapter(number=2, title="化工厂深处", content="正文" * 1000)
    )

    assert result.status == "审核中"
    assert (190, 1144) in driver.taps
    assert driver.right_containing_descriptions == ["内容是否使用AI功能"]


@pytest.mark.asyncio
async def test_publish_allows_direct_submission_without_final_confirmation() -> None:
    driver = FakeUiDriver(
        [
            "发布设置 确认发布 内容是否使用AI功能 是",
            "章节管理 审核中 第2章 化工厂深处",
        ]
    )

    result = await FanqiePublishWorkflow(driver).publish(
        PublishChapter(number=2, title="化工厂深处", content="正文" * 1000)
    )

    assert result.status == "审核中"
    assert (508, 840) not in driver.taps


@pytest.mark.asyncio
async def test_publish_waits_for_target_after_submission_success_returns_to_draft_tab() -> None:
    driver = FakeUiDriver(
        [
            "提交成功，审核通过后发放 暂无草稿 章节管理 草稿箱",
            "章节管理 审核中 第1章 传承戒指",
        ]
    )

    result = await FanqiePublishWorkflow(driver).publish(
        PublishChapter(number=1, title="第一章：传承戒指", content="正文" * 1000)
    )

    assert result.status == "审核中"
    assert driver.containing_descriptions == ["章节管理"]


@pytest.mark.asyncio
async def test_publish_handles_submission_success_during_active_transition() -> None:
    driver = FakeUiDriver(
        [
            "发布设置 确认发布 内容是否使用AI功能 是",
            "提交成功，审核通过后发放 暂无草稿 章节管理 草稿箱",
            "章节管理 审核中 第1章 重生归来",
        ]
    )

    result = await FanqiePublishWorkflow(driver).publish(
        PublishChapter(number=1, title="第一章：重生归来", content="正文" * 1000)
    )

    assert result.status == "审核中"
    assert driver.containing_descriptions == ["章节管理"]
