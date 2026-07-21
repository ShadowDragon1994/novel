from __future__ import annotations

import argparse
import asyncio

from business.publish_scanner import PublishScanner
from core.feishu_client import FeishuClient
from device_gateway.adb_ui_driver import AdbUiDriver
from device_gateway.fanqie_workflow import FanqiePublishWorkflow, PublishChapter


async def publish_live(chapter_id: str, device_id: str, account_id: str) -> None:
    feishu = FeishuClient()
    scanner = PublishScanner(feishu_client=feishu)
    try:
        chapters = await feishu.list_records("章节任务表")
        record = next(
            item
            for item in chapters
            if item.get("fields", item).get("章节ID") == chapter_id
        )
        fields = record.get("fields", record)
        content = await scanner._load_final_content(chapter_id)
        if not content:
            raise RuntimeError(f"missing final content for {chapter_id}")

        driver = AdbUiDriver(device_id, pause_seconds=0.8, wait_timeout_seconds=25)
        workflow = FanqiePublishWorkflow(driver)
        result = await workflow.publish(
            PublishChapter(
                number=int(fields["章节号"]),
                title=str(fields["章节名"]),
                content=content,
            )
        )
        await scanner._mark_success(record, account_id, result.status)
        print(f"{chapter_id}: {result.chapter_label} -> {result.status}")
    finally:
        await scanner.device.close()
        await feishu.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish one finalized chapter to a live device")
    parser.add_argument("chapter_id")
    parser.add_argument("device_id")
    parser.add_argument("account_id")
    args = parser.parse_args()
    asyncio.run(publish_live(args.chapter_id, args.device_id, args.account_id))


if __name__ == "__main__":
    main()
