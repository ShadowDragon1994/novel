
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from device_gateway.adb_ui_driver import AdbUiDriver
from device_gateway.fanqie_workflow import FanqiePublishWorkflow, PublishChapter
from device_gateway.fanqie_inspiration_workflow import FanqieInspirationWorkflow


async def run(device_id: str, chapter_number: int, title: str, content_path: str) -> None:
    content = Path(content_path).read_text(encoding="utf-8-sig").strip()
    driver = AdbUiDriver(device_id, pause_seconds=0.8, startup_wait_seconds=5, wait_timeout_seconds=35)
    # Reset away from restored secondary pages such as Fanqie articles, then
    # enter Works -> first work explicitly before publishing.
    await FanqieInspirationWorkflow(driver, device_id=device_id).open_my_page()
    await driver.tap((228, 1224))
    await asyncio.sleep(2.0)
    await driver.tap((268, 650))
    await asyncio.sleep(2.0)

    workflow = FanqiePublishWorkflow(driver)
    result = await workflow.publish(PublishChapter(number=chapter_number, title=title, content=content))
    print(f"chapter_label={result.chapter_label}")
    print(f"status={result.status}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish one local final_content.txt to Fanqie via ADB")
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--chapter-number", type=int, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--content-path", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.device_id, args.chapter_number, args.title, args.content_path))


if __name__ == "__main__":
    main()
