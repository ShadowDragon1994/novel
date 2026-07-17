from __future__ import annotations

from datetime import datetime
from typing import Any

from business.guard_layer import GuardLayer
from core.feishu_client import FeishuClient

APPROVED = {"通过", "通过/Approved", "已通过"}
REJECTED = {"不通过", "不通过/Rejected", "驳回"}
FINALIZED = {"已定稿", "已定稿/Finalized"}


class ReviewProcessor:
    def __init__(self, feishu_client: Any | None = None, guard_layer: GuardLayer | None = None) -> None:
        self.feishu_client = feishu_client or FeishuClient()
        self.guard_layer = guard_layer or GuardLayer(self.feishu_client)

    async def run_once(self, *, now: datetime | None = None) -> list[str]:
        processed: list[str] = []
        reviewed_at = now or datetime.now()
        records = await self.feishu_client.list_records("章节任务表")
        for record in records:
            fields = record.get("fields", record)
            chapter_id = str(fields.get("章节ID") or "")
            result = fields.get("人工审核结果") or fields.get("晚班审核结果")
            update: dict[str, Any] | None = None
            if result in APPROVED and fields.get("生产状态") not in FINALIZED:
                update = {
                    "生产状态": "已定稿/Finalized",
                    "内容锁定状态": "是/Yes",
                    "发布状态": "未排期/Unscheduled",
                    "审核时间": reviewed_at.isoformat(),
                }
            elif result in REJECTED and fields.get("生产状态") != "待生成初稿/Pending Draft":
                update = {
                    "生产状态": "待生成初稿/Pending Draft",
                    "内容锁定状态": "否/No",
                    "发布状态": "未排期/Unscheduled",
                    "内容返工次数": int(fields.get("内容返工次数") or 0) + 1,
                    "审核时间": reviewed_at.isoformat(),
                }
            if update:
                await self.guard_layer.write(
                    "章节任务表",
                    str(record.get("record_id") or chapter_id),
                    update,
                )
                processed.append(chapter_id)
        return processed
