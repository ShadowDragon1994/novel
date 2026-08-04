from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.feishu_client import FeishuClient
from device_gateway.adb_ui_driver import AdbUiDriver
from device_gateway.fanqie_workflow import FanqiePublishWorkflow, PublishChapter, PublishResult

TARGETS = {
    "NOVEL-01-CH-004": "127.0.0.1:59380",
    "NOVEL-02-CH-003": "127.0.0.1:59378",
    "NOVEL-03-CH-003": "127.0.0.1:59381",
    "NOVEL-04-CH-005": "127.0.0.1:59382",
    "NOVEL-05-CH-003": "127.0.0.1:59386",
}


async def revise_one(device_id: str, chapter: PublishChapter) -> PublishResult:
    driver = AdbUiDriver(device_id, pause_seconds=1)
    workflow = FanqiePublishWorkflow(driver)
    platform_title = workflow._platform_title(chapter.title)
    try:
        editor_text = await driver.screen_text()
        chapter_label = f"第{chapter.number}章 {platform_title}"
        if (
            "修改审核中" in editor_text
            and f"第{chapter.number}章" in editor_text.replace("\u200b", "")
        ):
            return PublishResult(chapter_label=chapter_label, status="审核中")
        if "发布设置" in editor_text or (
            "内容是否使用AI功能" in editor_text and "确认发布" in editor_text
        ):
            result = await workflow._continue_submission(editor_text, chapter_label)
            await workflow.recovery.recover()
            return result
        resumed_saved_revision = workflow._is_editor(editor_text) and platform_title in editor_text
        if not resumed_saved_revision:
            await workflow.prepare_for_task()
            await driver.tap_description_contains(f"第{chapter.number}章")
            detail_text = await driver.wait_for_any(("章节的内容：已发布",))
            if "章节的内容：已发布" not in detail_text:
                raise RuntimeError(f"第{chapter.number}章不是已发布状态")
            await driver.tap_description("修改章节")
            editor_text = await driver.wait_for_any(("下一步", "请输入正文"))
            if "审核工作时间" in editor_text:
                editor_text = await workflow._tap("chapter_editor", "dismiss_night_notice")
            await driver.scroll_to_top()
            for action_name, value in (
                ("focus_chapter_number", str(chapter.number)),
                ("focus_title", platform_title),
                ("focus_body", chapter.content.strip()),
            ):
                action = workflow._action("chapter_editor", action_name)
                if action.point is None:
                    raise RuntimeError(f"缺少坐标: chapter_editor.{action_name}")
                await driver.replace_text(action.point, value)
        await driver.wait_for_any(("已保存到云端", "已保存"))
        workflow._validate_saved_content(await driver.screen_text(), chapter.content)
        await driver.tap_description("下一步")
        next_text = await driver.wait_for_any(("检测到您还有错别字未修改，是否确认提交？", "请选择内容检测方式"))
        result = await workflow._continue_submission(
            next_text,
            chapter_label,
        )
        await workflow.recovery.recover()
        return result
    except Exception:
        await workflow.recovery.recover()
        raise


def _fields(record: dict[str, Any]) -> dict[str, Any]:
    return record.get("fields", record)


async def load_chapters(client: FeishuClient, chapter_ids: set[str]) -> list[tuple[str, PublishChapter]]:
    chapter_records = await client.list_records("章节任务表")
    version_records = await client.list_records("正文版本表")
    chapters = {
        str(_fields(record).get("章节ID")): _fields(record)
        for record in chapter_records
        if _fields(record).get("章节ID") in chapter_ids
    }
    final_content = {
        str(_fields(record).get("章节ID")): str(_fields(record).get("版本内容") or "")
        for record in version_records
        if _fields(record).get("章节ID") in chapter_ids and _fields(record).get("是否当前最终版") is True
    }
    missing = chapter_ids - chapters.keys() | chapter_ids - final_content.keys()
    if missing:
        raise RuntimeError(f"缺少章节或最终正文: {', '.join(sorted(missing))}")
    return [
        (
            chapter_id,
            PublishChapter(
                number=int(chapters[chapter_id]["章节号"]),
                title=str(chapters[chapter_id]["章节名"]),
                content=final_content[chapter_id],
            ),
        )
        for chapter_id in sorted(chapter_ids)
    ]


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="修正已发布章节的乱码标题和错误正文")
    parser.add_argument("--chapter-id", choices=sorted(TARGETS), help="只修正一个章节")
    args = parser.parse_args()
    load_dotenv(PROJECT_ROOT / "config" / ".env")
    selected = {args.chapter_id} if args.chapter_id else set(TARGETS)
    async with FeishuClient() as client:
        chapters = await load_chapters(client, selected)
    for chapter_id, chapter in chapters:
        result = await revise_one(TARGETS[chapter_id], chapter)
        print(f"{chapter_id}: {result.status} ({result.chapter_label})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
