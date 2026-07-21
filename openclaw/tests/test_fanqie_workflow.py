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
    assert driver.descriptions == ["有使用AI"]
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
    assert (632, 1064) not in driver.taps


@pytest.mark.asyncio
async def test_publish_opens_existing_draft_instead_of_creating_duplicate() -> None:
    driver = FakeUiDriver(
        [
            "章节管理 草稿 第2章 化工厂深处",
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

    assert driver.containing_descriptions == ["第2章 化工厂深处"]
    assert (632, 1064) not in driver.taps


@pytest.mark.asyncio
async def test_publish_stops_when_chapter_number_belongs_to_different_title() -> None:
    driver = FakeUiDriver(["章节管理 草稿 第2章 另一个标题"])

    with pytest.raises(WorkflowError, match="chapter number 2 already exists"):
        await FanqiePublishWorkflow(driver).publish(
            PublishChapter(number=2, title="化工厂深处", content="正文" * 1000)
        )

    assert driver.taps == []
