from datetime import datetime

import pytest

from business.review_processor import ReviewProcessor


class FakeFeishu:
    def __init__(self, chapters):
        self.chapters = chapters

    async def list_records(self, table_name):
        return self.chapters if table_name == "章节任务表" else []


class FakeGuard:
    def __init__(self):
        self.writes = []

    async def write(self, table, record_id, fields):
        self.writes.append((table, record_id, fields))
        return {"record_id": record_id, "fields": fields}


@pytest.mark.asyncio
async def test_review_processor_finalizes_approved_chapter() -> None:
    guard = FakeGuard()
    processor = ReviewProcessor(
        FakeFeishu([{"record_id": "r1", "fields": {"章节ID": "c1", "人工审核结果": "通过"}}]),
        guard,
    )
    assert await processor.run_once(now=datetime(2026, 7, 17, 22, 30)) == ["c1"]
    fields = guard.writes[0][2]
    assert fields["生产状态"] == "已定稿/Finalized"
    assert fields["内容锁定状态"] == "是/Yes"
    assert fields["发布状态"] == "未排期/Unscheduled"


@pytest.mark.asyncio
async def test_review_processor_returns_rejected_chapter_to_draft() -> None:
    guard = FakeGuard()
    processor = ReviewProcessor(
        FakeFeishu(
            [
                {
                    "record_id": "r1",
                    "fields": {"章节ID": "c1", "人工审核结果": "不通过", "内容返工次数": 1},
                }
            ]
        ),
        guard,
    )
    await processor.run_once()
    fields = guard.writes[0][2]
    assert fields["生产状态"] == "待生成初稿/Pending Draft"
    assert fields["内容返工次数"] == 2
    assert fields["内容锁定状态"] == "否/No"
