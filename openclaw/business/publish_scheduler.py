from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from business.guard_layer import GuardLayer
from core.config import load_settings
from core.feishu_client import FeishuClient

READY_PRODUCTION_STATUS = {"已定稿", "已定稿/Finalized", "已审核", "已完成"}
SCHEDULABLE_PUBLISH_STATUS = {"未排期", "未排期/Unscheduled", ""}
LOCKED_VALUES = {"是", "是/Yes", True, "人工锁定", "已锁定"}


@dataclass(frozen=True)
class NovelConfig:
    novel_id: str
    daily_max: int
    available_drafts: int | None = None
    reserve_drafts: int = 0


@dataclass
class ScheduleResult:
    assigned: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


class PublishScheduler:
    def __init__(
        self,
        feishu_client: FeishuClient | None = None,
        guard_layer: GuardLayer | None = None,
        *,
        today: date | None = None,
    ) -> None:
        self.feishu_client = feishu_client or FeishuClient()
        self.guard_layer = guard_layer or GuardLayer(self.feishu_client)
        self.settings = load_settings()
        self.today = today

    async def generate_daily_plan(self, *, now: datetime | None = None) -> ScheduleResult:
        now = now or datetime.now()
        target_date = self._target_date(now)
        pending = await self._pending_chapters()
        if not pending:
            return ScheduleResult()
        existing = await self._scheduled_chapters(target_date)
        existing_counts = self._count_by_novel(existing)
        used_slots = self._used_slots_by_novel(existing)
        globally_used_slots = [slot for slots_for_novel in used_slots.values() for slot in slots_for_novel]
        slots = self._time_slots(target_date)
        by_novel = self._group_by_novel(pending)
        configs = await self._novel_configs()
        result = ScheduleResult()
        for novel_id, chapters in by_novel.items():
            config = configs.get(novel_id, NovelConfig(novel_id, daily_max=1))
            remaining = max(config.daily_max - existing_counts.get(novel_id, 0), 0)
            if config.available_drafts is not None:
                safe_capacity = max(config.available_drafts - config.reserve_drafts, 0)
                remaining = min(remaining, safe_capacity)
            for chapter in chapters:
                chapter_id = str(chapter.get("fields", chapter).get("章节ID"))
                if remaining <= 0:
                    result.skipped.append(chapter_id)
                    continue
                slot = self._pick_slot(slots, used_slots[novel_id], globally_used_slots)
                if slot is None:
                    result.skipped.append(chapter_id)
                    continue
                await self._assign(chapter, slot)
                used_slots[novel_id].append(slot)
                globally_used_slots.append(slot)
                result.assigned.append(chapter_id)
                remaining -= 1
        return result

    async def _pending_chapters(self) -> list[dict[str, Any]]:
        records = await self.feishu_client.list_records("章节任务表")
        pending = []
        for record in records:
            fields = record.get("fields", record)
            if (
                fields.get("生产状态") in READY_PRODUCTION_STATUS
                and str(fields.get("发布状态") or "") in SCHEDULABLE_PUBLISH_STATUS
                and not fields.get("计划发布时间")
                and fields.get("内容锁定状态") in LOCKED_VALUES
                and fields.get("当前版本")
            ):
                pending.append(record)
        return sorted(pending, key=self._chapter_sort_key)

    async def _scheduled_chapters(self, target_date: date) -> list[dict[str, Any]]:
        records = await self.feishu_client.list_records("章节任务表")
        scheduled = []
        for record in records:
            fields = record.get("fields", record)
            planned_at = self._parse_datetime(fields.get("计划发布时间"))
            if planned_at and planned_at.date() == target_date:
                scheduled.append(record)
        return scheduled

    async def _novel_configs(self) -> dict[str, NovelConfig]:
        records = await self.feishu_client.list_records("小说总览表")
        configs = {}
        for record in records:
            fields = record.get("fields", record)
            novel_id = str(fields.get("小说ID") or "")
            if novel_id:
                available = fields.get("当前可发布存稿数")
                configs[novel_id] = NovelConfig(
                    novel_id=novel_id,
                    daily_max=int(fields.get("日更目标") or 1),
                    available_drafts=int(available) if available not in (None, "") else None,
                    reserve_drafts=int(fields.get("最低存稿章节数") or 0),
                )
        return configs

    def _target_date(self, now: datetime) -> date:
        return (now + timedelta(days=1)).date() if now.time() >= time(23, 0) else now.date()

    def _time_slots(self, target_date: date) -> list[datetime]:
        config = self.settings.raw.get("publish_window", {})
        earliest = self._parse_time(str(config.get("earliest", "08:30")))
        latest = self._parse_time(str(config.get("latest", "22:00")))
        min_gap = max(int(config.get("slot_gap_hours", 3)), 1)
        slots = []
        current = datetime.combine(target_date, earliest)
        end = datetime.combine(target_date, latest)
        while current <= end:
            slots.append(current)
            current += timedelta(hours=min_gap)
        return slots

    def _pick_slot(
        self,
        slots: list[datetime],
        used: list[datetime],
        globally_used: list[datetime] | None = None,
    ) -> datetime | None:
        min_gap = timedelta(hours=int(self.settings.raw.get("publish_window", {}).get("min_gap_hours", 6)))
        global_slots = globally_used or []
        for slot in slots:
            candidate = slot + self._jitter(slot)
            while used and not all(abs(candidate - used_slot) >= min_gap for used_slot in used):
                candidate += timedelta(minutes=5)
            while candidate in global_slots:
                candidate += timedelta(minutes=5)
            if candidate.time() <= self._parse_time(
                str(self.settings.raw.get("publish_window", {}).get("latest", "22:00"))
            ):
                return candidate
        return None

    def _jitter(self, slot: datetime) -> timedelta:
        jitter = self.settings.raw.get("publish_window", {}).get("jitter_minutes", [5, 15])
        return timedelta(minutes=random.randint(int(jitter[0]), int(jitter[-1])))

    async def _assign(self, chapter: dict[str, Any], slot: datetime) -> None:
        record_id = str(chapter.get("record_id") or chapter.get("fields", chapter).get("章节ID"))
        await self.guard_layer.write(
            "章节任务表",
            record_id,
            {
                "计划发布时间": slot.isoformat(),
                "发布状态": "待发布/Pending Publish",
                "排班批次": f"batch-{slot.date().isoformat()}",
                "排班生成时间": datetime.now().isoformat(),
            },
        )

    def _group_by_novel(self, records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            fields = record.get("fields", record)
            grouped[str(fields.get("小说ID") or "")].append(record)
        return dict(grouped)

    def _count_by_novel(self, records: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for record in records:
            counts[str(record.get("fields", record).get("小说ID") or "")] += 1
        return dict(counts)

    def _used_slots_by_novel(self, records: list[dict[str, Any]]) -> dict[str, list[datetime]]:
        used: dict[str, list[datetime]] = defaultdict(list)
        for record in records:
            fields = record.get("fields", record)
            planned_at = self._parse_datetime(fields.get("计划发布时间"))
            if planned_at:
                used[str(fields.get("小说ID") or "")].append(planned_at)
        return used

    def _chapter_sort_key(self, record: dict[str, Any]) -> tuple[str, str]:
        fields = record.get("fields", record)
        return str(fields.get("审核时间") or ""), str(fields.get("章节号") or "")

    def _parse_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000)
        if isinstance(value, str) and value:
            return datetime.fromisoformat(value)
        return None

    def _parse_time(self, value: str) -> time:
        return datetime.strptime(value, "%H:%M").time()
