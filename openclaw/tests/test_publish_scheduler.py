from datetime import date, datetime

import pytest

from business.publish_scheduler import PublishScheduler


class FakeFeishu:
    def __init__(self, chapters=None, novels=None) -> None:
        self.chapters = chapters or []
        self.novels = novels or [{"fields": {"小说ID": "n1", "日更目标": 2}}]

    async def list_records(self, table_name):
        if table_name == "章节任务表":
            return self.chapters
        if table_name == "小说总览表":
            return self.novels
        return []


class FakeGuard:
    def __init__(self) -> None:
        self.writes = []

    async def write(self, table, record_id, fields):
        self.writes.append((table, record_id, fields))
        return {"record_id": record_id, "fields": fields}


def chapter(
    record_id,
    chapter_id,
    novel_id="n1",
    status="已定稿/Finalized",
    publish_status="未排期/Unscheduled",
    planned_at=None,
    number=1,
):
    return {
        "record_id": record_id,
        "fields": {
            "章节ID": chapter_id,
            "小说ID": novel_id,
            "生产状态": status,
            "发布状态": publish_status,
            "内容锁定状态": "是/Yes",
            "当前版本": 1,
            "计划发布时间": planned_at,
            "审核时间": f"2026-05-23T0{number}:00:00",
            "章节号": number,
        },
    }


def make_scheduler(chapters, novels=None):
    guard = FakeGuard()
    scheduler = PublishScheduler(FakeFeishu(chapters, novels), guard, today=date(2026, 5, 23))
    return scheduler, guard


@pytest.mark.asyncio
async def test_scheduler_scans_pending_chapters() -> None:
    scheduler, _ = make_scheduler([chapter("r1", "c1"), chapter("r2", "c2", status="生成中/Generating")])
    pending = await scheduler._pending_chapters()
    assert [item["fields"]["章节ID"] for item in pending] == ["c1"]


@pytest.mark.asyncio
async def test_scheduler_respects_daily_max_per_novel() -> None:
    scheduler, guard = make_scheduler([chapter("r1", "c1"), chapter("r2", "c2"), chapter("r3", "c3")])
    result = await scheduler.generate_daily_plan(now=datetime(2026, 5, 23, 8, 10))
    assert result.assigned == ["c1", "c2"]
    assert result.skipped == ["c3"]
    assert len(guard.writes) == 2


@pytest.mark.asyncio
async def test_scheduler_can_assign_three_chapters_with_dense_slots() -> None:
    scheduler, guard = make_scheduler(
        [chapter("r1", "c1", number=1), chapter("r2", "c2", number=2), chapter("r3", "c3", number=3)],
        novels=[{"fields": {"小说ID": "n1", "日更目标": 3}}],
    )
    result = await scheduler.generate_daily_plan(now=datetime(2026, 5, 23, 8, 10))
    assert result.assigned == ["c1", "c2", "c3"]
    slots = [datetime.fromisoformat(write[2]["计划发布时间"]) for write in guard.writes]
    assert all(abs(slots[index + 1] - slots[index]).total_seconds() >= 6 * 3600 for index in range(2))


@pytest.mark.asyncio
async def test_scheduler_enforces_6h_gap() -> None:
    scheduler, guard = make_scheduler([chapter("r1", "c1"), chapter("r2", "c2")])
    await scheduler.generate_daily_plan(now=datetime(2026, 5, 23, 8, 10))
    slots = [datetime.fromisoformat(write[2]["计划发布时间"]) for write in guard.writes]
    assert abs(slots[1] - slots[0]).total_seconds() >= 6 * 3600


@pytest.mark.asyncio
async def test_scheduler_distributes_across_time_window() -> None:
    scheduler, guard = make_scheduler([chapter("r1", "c1")])
    await scheduler.generate_daily_plan(now=datetime(2026, 5, 23, 8, 10))
    slot = datetime.fromisoformat(guard.writes[0][2]["计划发布时间"])
    assert slot.hour >= 8
    assert slot.hour <= 22


@pytest.mark.asyncio
async def test_scheduler_updates_publish_status() -> None:
    scheduler, guard = make_scheduler([chapter("r1", "c1")])
    await scheduler.generate_daily_plan(now=datetime(2026, 5, 23, 8, 10))
    assert guard.writes[0][2]["发布状态"] == "待发布/Pending Publish"
    assert "排班批次" in guard.writes[0][2]
    assert "排班生成时间" in guard.writes[0][2]


@pytest.mark.asyncio
async def test_scheduler_skips_unlocked() -> None:
    item = chapter("r1", "c1")
    item["fields"]["内容锁定状态"] = "否/No"
    scheduler, guard = make_scheduler([item])
    result = await scheduler.generate_daily_plan(now=datetime(2026, 5, 23, 8, 10))
    assert result.assigned == []
    assert guard.writes == []


@pytest.mark.asyncio
async def test_scheduler_skips_empty_version() -> None:
    item = chapter("r1", "c1")
    item["fields"]["当前版本"] = ""
    scheduler, guard = make_scheduler([item])
    result = await scheduler.generate_daily_plan(now=datetime(2026, 5, 23, 8, 10))
    assert result.assigned == []
    assert guard.writes == []


@pytest.mark.asyncio
async def test_scheduler_handles_no_pending_chapters() -> None:
    scheduler, guard = make_scheduler([])
    result = await scheduler.generate_daily_plan(now=datetime(2026, 5, 23, 8, 10))
    assert result.assigned == []
    assert guard.writes == []


@pytest.mark.asyncio
async def test_scheduler_handles_already_fully_scheduled() -> None:
    existing = chapter("r0", "c0", planned_at="2026-05-23T08:35:00", publish_status="待发布/Pending Publish")
    scheduler, guard = make_scheduler(
        [existing, chapter("r1", "c1")],
        novels=[{"fields": {"小说ID": "n1", "日更目标": 1}}],
    )
    result = await scheduler.generate_daily_plan(now=datetime(2026, 5, 23, 8, 10))
    assert result.assigned == []
    assert result.skipped == ["c1"]
    assert guard.writes == []


@pytest.mark.asyncio
async def test_scheduler_morning_batch_only_new_chapters() -> None:
    scheduled = chapter("r0", "c0", planned_at="2026-05-23T08:35:00", publish_status="待发布/Pending Publish")
    scheduler, guard = make_scheduler([scheduled, chapter("r1", "c1")])
    result = await scheduler.generate_daily_plan(now=datetime(2026, 5, 23, 8, 10))
    assert result.assigned == ["c1"]
    assert guard.writes[0][1] == "r1"


@pytest.mark.asyncio
async def test_scheduler_evening_batch_schedules_next_day() -> None:
    scheduler, guard = make_scheduler([chapter("r1", "c1")])
    await scheduler.generate_daily_plan(now=datetime(2026, 5, 23, 23, 0))
    slot = datetime.fromisoformat(guard.writes[0][2]["计划发布时间"])
    assert slot.date() == date(2026, 5, 24)


@pytest.mark.asyncio
async def test_scheduler_applies_jitter() -> None:
    scheduler, guard = make_scheduler([chapter("r1", "c1", "n1"), chapter("r2", "c2", "n2")], novels=[
        {"fields": {"小说ID": "n1", "日更目标": 1}},
        {"fields": {"小说ID": "n2", "日更目标": 1}},
    ])
    await scheduler.generate_daily_plan(now=datetime(2026, 5, 23, 8, 10))
    slots = [write[2]["计划发布时间"] for write in guard.writes]
    assert len(set(slots)) == 2
    assert all(35 <= datetime.fromisoformat(slot).minute <= 50 for slot in slots)


@pytest.mark.asyncio
async def test_scheduler_respects_inventory_reserve() -> None:
    scheduler, guard = make_scheduler(
        [chapter("r1", "c1"), chapter("r2", "c2")],
        novels=[{"fields": {"小说ID": "n1", "日更目标": 2, "当前可发布存稿数": 7, "最低存稿章节数": 6}}],
    )
    result = await scheduler.generate_daily_plan(now=datetime(2026, 5, 23, 8, 10))
    assert result.assigned == ["c1"]
    assert result.skipped == ["c2"]
    assert len(guard.writes) == 1


@pytest.mark.asyncio
async def test_scheduler_guards_against_duplicate_assignment() -> None:
    scheduler, guard = make_scheduler([chapter("r1", "c1", planned_at="2026-05-23T08:35:00")])
    result = await scheduler.generate_daily_plan(now=datetime(2026, 5, 23, 8, 10))
    assert result.assigned == []
    assert guard.writes == []


def test_scheduler_time_slots_respect_window() -> None:
    scheduler, _ = make_scheduler([])
    slots = scheduler._time_slots(date(2026, 5, 23))
    assert slots[0].strftime("%H:%M") == "08:30"
    assert slots[-1].hour <= 22
