from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.feishu_client import FeishuClient

LOCKED_VALUES = {"是", "是/Yes", True}
CORE_VALUES = {"是", "是/Yes", "核心/Core", "核心人物/Main", "核心势力/Core", True}
MANUAL_VALUES = {"人工创建", "人工创建/Manual", "Manual"}

LOCKED_CHAPTER_FORBIDDEN_FIELDS = {
    "章节名",
    "章节卡内容",
    "当前版本",
    "最终字数",
    "最终评分",
    "上下文哈希",
    "人工审核结果",
    "人工审核意见",
}

CORE_PROTECTED_TABLES = {
    "人物档案表": "是否核心",
    "世界观设定表": "是否核心",
    "势力组织表": "是否核心",
    "伏笔追踪表": "是否主线伏笔",
    "长期记忆表": "是否核心",
}

CORE_ALWAYS_WRITABLE_FIELDS = {
    "确认状态",
    "来源状态",
    "最后更新时间",
    "最近出场章节",
}


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    reason: str = ""


class GuardLayer:
    def __init__(self, feishu_client: FeishuClient) -> None:
        self.feishu_client = feishu_client

    async def write(self, table: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        decision = await self.check_write(table, record_id, fields)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        return await self.feishu_client.update_record(table, record_id, fields)

    async def check_write(self, table: str, record_id: str, fields: dict[str, Any]) -> GuardDecision:
        if not fields:
            return GuardDecision(False, "empty fields are not allowed")
        record = await self.feishu_client.get_record(table, record_id)
        record_fields = record.get("fields", record)
        if table == "章节任务表":
            decision = self._check_locked_chapter(record_fields, fields)
            if not decision.allowed:
                return decision
        if table in CORE_PROTECTED_TABLES:
            decision = self._check_core_record(table, record_fields, fields)
            if not decision.allowed:
                return decision
        return GuardDecision(True)

    def _check_locked_chapter(self, record_fields: dict[str, Any], fields: dict[str, Any]) -> GuardDecision:
        if record_fields.get("内容锁定状态") not in LOCKED_VALUES:
            return GuardDecision(True)
        forbidden = sorted(set(fields) & LOCKED_CHAPTER_FORBIDDEN_FIELDS)
        if forbidden:
            return GuardDecision(False, f"content locked; forbidden fields: {', '.join(forbidden)}")
        return GuardDecision(True)

    def _check_core_record(self, table: str, record_fields: dict[str, Any], fields: dict[str, Any]) -> GuardDecision:
        core_field = CORE_PROTECTED_TABLES[table]
        is_manual = record_fields.get("来源状态") in MANUAL_VALUES
        is_core = record_fields.get(core_field) in CORE_VALUES
        if not (is_manual and is_core):
            return GuardDecision(True)
        writable = set(fields) <= CORE_ALWAYS_WRITABLE_FIELDS
        if writable:
            return GuardDecision(True)
        return GuardDecision(False, "manual core record is protected; create an AI suggestion instead")
