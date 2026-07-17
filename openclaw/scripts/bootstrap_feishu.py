from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.feishu_client import FeishuClient


@dataclass(frozen=True)
class BootstrapResult:
    created: int
    skipped: int


def build_novel_seed(index: int) -> dict[str, Any]:
    novel_id = f"NOVEL-{index:02d}"
    return {
        "小说ID": novel_id,
        "书名": f"OpenClaw 测试小说 {index:02d}",
        "题材": "玄幻",
        "核心卖点": "自动化创作发布流程验证",
        "总字数": 1_500_000,
        "总卷数": 5,
        "总章节数": 600,
        "日更目标": 25,
        "上线批次": "bootstrap-week1",
        "自动流程开关": False,
        "自动发布开关": False,
        "最低存稿章节数": 6,
        "发布时间窗口": "08:30-22:00",
        "发布暂停原因": "",
        "当前可发布存稿数": 0,
        "已完成章节数": 0,
        "已完成字数": 0,
        "本月已更天数": 0,
    }


def build_account_seed(index: int) -> dict[str, Any]:
    novel_id = f"NOVEL-{index:02d}"
    return {
        "账号ID": f"ACCOUNT-{index:02d}",
        "小说ID": novel_id,
        "绑定小说ID": novel_id,
        "账号昵称": f"OpenClaw 测试账号 {index:02d}",
        "账号状态": "正常/Normal",
        "账号健康状态": "正常/Normal",
        "账号阶段": "稳定期",
        "自动发布开关": False,
        "今日计划发布章数": 2,
        "今日已发布章数": 0,
    }


def build_chapter_seed(novel_index: int, chapter_number: int, finalized_count: int) -> dict[str, Any]:
    novel_id = f"NOVEL-{novel_index:02d}"
    finalized = chapter_number <= finalized_count
    return {
        "小说ID": novel_id,
        "章节ID": f"{novel_id}-CH-{chapter_number:03d}",
        "章节号": chapter_number,
        "章节名": f"第{chapter_number}章",
        "章节卡内容": "验收示例章节卡",
        "任务优先级": "中/Medium",
        "生产状态": "已定稿/Finalized" if finalized else "待生成细纲/Pending Outline",
        "内容锁定状态": "是/Yes" if finalized else "否/No",
        "发布状态": "未排期/Unscheduled",
        "当前版本": "校对稿" if finalized else "",
        "流程重试次数": 0,
        "内容返工次数": 0,
    }


class FeishuBootstrap:
    def __init__(self, feishu_client: FeishuClient) -> None:
        self.feishu_client = feishu_client

    async def initialize_novels(self, count: int = 10, *, dry_run: bool = False) -> BootstrapResult:
        created = 0
        skipped = 0
        existing_ids = await self._existing_novel_ids()
        for index in range(1, count + 1):
            seed = build_novel_seed(index)
            if seed["小说ID"] in existing_ids:
                skipped += 1
                continue
            if not dry_run:
                await self.feishu_client.create_record("小说总览表", seed)
            created += 1
        return BootstrapResult(created=created, skipped=skipped)

    async def _existing_novel_ids(self) -> set[str]:
        records = await self.feishu_client.list_records("小说总览表")
        novel_ids = set()
        for record in records:
            fields = record.get("fields", record)
            novel_id = fields.get("小说ID")
            if isinstance(novel_id, str):
                novel_ids.add(novel_id)
        return novel_ids

    async def initialize_acceptance_data(
        self,
        *,
        count: int = 10,
        chapters_per_novel: int = 30,
        finalized_per_novel: int = 6,
        dry_run: bool = False,
    ) -> dict[str, int]:
        novel_result = await self.initialize_novels(count, dry_run=dry_run)
        if not dry_run:
            for index in range(1, count + 1):
                await self.feishu_client.create_record("账号管理表", build_account_seed(index))
                for chapter_number in range(1, chapters_per_novel + 1):
                    await self.feishu_client.create_record(
                        "章节任务表",
                        build_chapter_seed(index, chapter_number, finalized_per_novel),
                    )
        return {
            "novels": novel_result.created,
            "accounts": count,
            "chapters": count * chapters_per_novel,
        }


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="Initialize OpenClaw Feishu seed data")
    parser.add_argument("--count", type=int, default=10, help="number of novels to initialize")
    parser.add_argument("--dry-run", action="store_true", help="calculate actions without writing Feishu")
    parser.add_argument("--with-samples", action="store_true", help="also initialize accounts and chapter samples")
    args = parser.parse_args()

    async with FeishuClient() as feishu_client:
        bootstrap = FeishuBootstrap(feishu_client)
        if args.with_samples:
            sample_result = await bootstrap.initialize_acceptance_data(count=args.count, dry_run=args.dry_run)
            print(f"bootstrap acceptance data: {sample_result}; dry_run={args.dry_run}")
        else:
            novel_result = await bootstrap.initialize_novels(args.count, dry_run=args.dry_run)
            print(
                f"bootstrap novels: created={novel_result.created}, skipped={novel_result.skipped}, "
                f"dry_run={args.dry_run}"
            )
    return 0


def main() -> None:
    exit_code = asyncio.run(async_main())
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
