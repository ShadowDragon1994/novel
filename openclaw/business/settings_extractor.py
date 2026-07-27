from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from business.guard_layer import GuardLayer
from core.config import ROOT_DIR
from llm.base import LLMClient
from llm.qwen import QwenClient


@dataclass(frozen=True)
class EntitySpec:
    table: str
    payload_key: str
    name_field: str
    id_field: str
    id_prefix: str
    create_fields: dict[str, str]
    append_field: str


ENTITY_SPECS = {
    "characters": EntitySpec(
        table="人物档案表",
        payload_key="characters",
        name_field="人物名称",
        id_field="人物ID",
        id_prefix="char",
        create_fields={"人物名称": "人物名称", "性格": "性格", "角色定位": "角色定位", "关系": "关系"},
        append_field="人物变化记录",
    ),
    "settings": EntitySpec(
        table="世界观设定表",
        payload_key="settings",
        name_field="设定名称",
        id_field="设定ID",
        id_prefix="setting",
        create_fields={"设定名称": "设定名称", "设定类型": "设定类型", "设定内容": "设定内容"},
        append_field="冲突处理原则",
    ),
    "factions": EntitySpec(
        table="势力组织表",
        payload_key="factions",
        name_field="势力名称",
        id_field="势力ID",
        id_prefix="faction",
        create_fields={"势力名称": "势力名称", "势力类型": "势力类型", "核心资源": "核心资源"},
        append_field="势力回写规则",
    ),
    "foreshadows": EntitySpec(
        table="伏笔追踪表",
        payload_key="foreshadows",
        name_field="伏笔内容",
        id_field="伏笔ID",
        id_prefix="foreshadow",
        create_fields={"伏笔内容": "伏笔内容", "铺设章节": "铺设章节", "重要等级": "重要等级"},
        append_field="伏笔识别提醒逻辑",
    ),
}
CORE_FIELD_BY_KEY = {
    "characters": "是否核心",
    "settings": "是否核心",
    "factions": "是否核心",
    "foreshadows": "是否主线伏笔",
}
CORE_VALUES = {"是", "是/Yes", True}


@dataclass
class ExtractResult:
    created: int = 0
    updated: int = 0
    skipped: bool = False
    entities: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


class SettingsExtractor:
    def __init__(
        self,
        feishu_client: Any,
        guard_layer: GuardLayer | None = None,
        llm_client: LLMClient | None = None,
        *,
        prompt_dir: Path | None = None,
    ) -> None:
        self.feishu_client = feishu_client
        self.guard_layer = guard_layer or GuardLayer(feishu_client)
        self.llm_client = llm_client or QwenClient()
        self.prompt_dir = prompt_dir or ROOT_DIR / "prompts"
        self._current_chapter_id = ""
        self.jinja = Environment(
            loader=FileSystemLoader(self.prompt_dir),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    async def extract_after_final(self, chapter_id: str) -> ExtractResult:
        self._current_chapter_id = chapter_id
        if await self._already_extracted(chapter_id):
            return ExtractResult(skipped=True)
        proofread = await self._load_proofread(chapter_id)
        if not proofread:
            return ExtractResult(skipped=True)
        chapter_card = await self._load_chapter_card(chapter_id)
        memories = await self._load_recent_memories(str(chapter_card.get("小说ID") or ""))
        prompt = self._render_extract_prompt(chapter_id, proofread, chapter_card=chapter_card, memories=memories)
        raw = await self.llm_client.generate(prompt)
        entities = self._parse_entities(raw)
        result = ExtractResult(entities=entities)
        for key, spec in ENTITY_SPECS.items():
            for index, item in enumerate(entities.get(key, []), start=1):
                try:
                    existing = await self._find_match(spec, item)
                    if existing:
                        await self._append_suggestion(spec, existing, item)
                        result.updated += 1
                    else:
                        await self._create_pending(spec, item, index)
                        result.created += 1
                except PermissionError:
                    await self._create_pending(spec, {**item, self._core_field_for_spec(spec): True}, index)
                    result.created += 1
        await self._mark_resolved_foreshadows(entities.get("foreshadows_resolved", []))
        await self._create_long_term_candidates(entities.get("long_term_memory", []))
        await self._write_short_term_memory(chapter_id, proofread, chapter_card, entities)
        await self._maybe_write_mid_term_memory(str(chapter_card.get("小说ID") or ""))
        await self.feishu_client.create_record(
            "运行日志表",
            {
                "日志ID": f"extract-{chapter_id}",
                "节点名称": "settings_extractor",
                "执行状态": "成功/Success",
                "错误信息": "",
                "输入摘要": chapter_id,
                "输出摘要": f"created={result.created}; updated={result.updated}",
                "重试次数": 0,
            },
        )
        return result

    async def _load_proofread(self, chapter_id: str) -> str:
        records = await self.feishu_client.list_records("正文版本表")
        proofreads = [
            record.get("fields", record)
            for record in records
            if record.get("fields", record).get("章节ID") == chapter_id
            and record.get("fields", record).get("版本类型") == "校对稿"
        ]
        if not proofreads:
            return ""
        return str(proofreads[-1].get("版本内容") or "")

    async def _already_extracted(self, chapter_id: str) -> bool:
        records = await self.feishu_client.list_records("章节任务表")
        for record in records:
            fields = record.get("fields", record)
            if fields.get("章节ID") == chapter_id and fields.get("确认状态") == "已提取/Extracted":
                return True
        records = await self.feishu_client.list_records("运行日志表")
        return any(
            record.get("fields", record).get("日志ID") == f"extract-{chapter_id}"
            and record.get("fields", record).get("执行状态") == "成功/Success"
            for record in records
        )

    async def _load_chapter_card(self, chapter_id: str) -> dict[str, Any]:
        records = await self.feishu_client.list_records("章节任务表")
        for record in records:
            fields = record.get("fields", record)
            if fields.get("章节ID") == chapter_id:
                return fields
        return {}

    async def _load_recent_memories(self, novel_id: str, limit: int = 10) -> list[dict[str, Any]]:
        records = await self.feishu_client.list_records("短期记忆表")
        memories = [
            record.get("fields", record)
            for record in records
            if record.get("fields", record).get("小说ID") == novel_id
        ]
        return memories[-limit:]

    def _render_extract_prompt(
        self,
        chapter_id: str,
        proofread_content: str,
        *,
        chapter_card: dict[str, Any] | None = None,
        memories: list[dict[str, Any]] | None = None,
    ) -> str:
        return self.jinja.get_template("extract.j2").render(
            chapter_id=chapter_id,
            proofread_content=proofread_content,
            chapter_card=chapter_card or {},
            memories=memories or [],
        )

    def _parse_entities(self, raw: str) -> dict[str, list[dict[str, Any]]]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, flags=re.S)
            if not match:
                raise
            payload = json.loads(match.group(0))
        result = {key: list(payload.get(key) or []) for key in ENTITY_SPECS}
        result["foreshadows_resolved"] = list(payload.get("foreshadows_resolved") or [])
        if "long_term_memory" in payload:
            result["long_term_memory"] = list(payload.get("long_term_memory") or [])
        return result

    async def _write_short_term_memory(
        self,
        chapter_id: str,
        proofread: str,
        chapter_card: dict[str, Any],
        entities: dict[str, list[dict[str, Any]]],
    ) -> None:
        await self.feishu_client.create_record(
            "短期记忆表",
            {
                "版本ID": f"short-{chapter_id}",
                "小说ID": str(chapter_card.get("小说ID") or ""),
                "关联章节ID": chapter_id,
                "摘要": proofread[:1000],
                "关键事件": json.dumps(entities.get("settings", []), ensure_ascii=False),
                "人物变化": json.dumps(entities.get("characters", []), ensure_ascii=False),
                "伏笔处理": json.dumps(entities.get("foreshadows_resolved", []), ensure_ascii=False),
            },
        )

    async def _maybe_write_mid_term_memory(self, novel_id: str) -> None:
        if not novel_id:
            return
        memories = [
            record.get("fields", record)
            for record in await self.feishu_client.list_records("短期记忆表")
            if str(record.get("fields", record).get("小说ID") or "") == novel_id
        ]
        if not memories or len(memories) % 25:
            return
        await self.feishu_client.create_record(
            "中期记忆表",
            {
                "版本ID": f"mid-{novel_id}-{len(memories) // 25:03d}",
                "触发类型": "每25章/Every 25 Chapters",
                "阶段总结内容": "\n".join(str(item.get("摘要") or "") for item in memories[-25:]),
            },
        )

    async def _create_long_term_candidates(self, items: list[dict[str, Any]]) -> None:
        for index, item in enumerate(items, start=1):
            fields = {
                key: item[key]
                for key in ("主线", "规则", "核心人物", "核心矛盾", "禁止事项")
                if item.get(key) not in (None, "")
            }
            fields.update(
                {
                    "版本ID": f"memory-{self._current_chapter_id}-{index:02d}",
                    "来源状态": "AI建议新增-待确认/AI Pending Confirmation",
                    "确认状态": "待确认/Pending",
                    "是否核心": True,
                    "是否当前生效": False,
                }
            )
            await self.feishu_client.create_record("长期记忆表", fields)

    async def _find_match(self, spec: EntitySpec, item: dict[str, Any]) -> dict[str, Any] | None:
        name = str(item.get(spec.name_field) or "").strip()
        if not name:
            return None
        records = await self.feishu_client.list_records(spec.table)
        for record in records:
            fields = record.get("fields", record)
            aliases = str(fields.get("人物别名") or "")
            if fields.get(spec.name_field) == name or name in aliases:
                return record
        return None

    async def _create_pending(self, spec: EntitySpec, item: dict[str, Any], index: int) -> None:
        fields = {
            target: item.get(source, "")
            for target, source in spec.create_fields.items()
            if item.get(source, "") not in ("", None)
        }
        fields[spec.id_field] = self._entity_id(spec, index)
        core_field = self._core_field_for_spec(spec)
        is_core = item.get(core_field) in CORE_VALUES or str(item.get(core_field) or "").startswith("是")
        if core_field:
            fields[core_field] = True if is_core else False
        fields["来源状态"] = "AI建议新增-待确认/AI Pending Confirmation" if is_core else "AI自动新增/AI Auto"
        fields["确认状态"] = "待确认/Pending" if is_core else "已确认/Confirmed"
        await self.feishu_client.create_record(spec.table, fields)

    async def _append_suggestion(self, spec: EntitySpec, record: dict[str, Any], item: dict[str, Any]) -> None:
        fields = record.get("fields", record)
        record_id = str(record.get("record_id") or fields.get("record_id") or fields.get("ID") or "")
        existing_text = str(fields.get(spec.append_field) or "")
        suggestion = item.get(spec.append_field) or item.get(spec.name_field) or json.dumps(item, ensure_ascii=False)
        new_text = f"{existing_text}\nAI建议更新-待确认：{suggestion}".strip()
        await self.guard_layer.write(spec.table, record_id, {spec.append_field: new_text})

    def _entity_id(self, spec: EntitySpec, index: int) -> str:
        safe_chapter_id = re.sub(r"[^0-9A-Za-z_-]+", "-", self._current_chapter_id).strip("-") or "chapter"
        return f"{spec.id_prefix}-{safe_chapter_id}-{index:02d}"

    def _core_field_for_spec(self, spec: EntitySpec) -> str:
        for key, candidate in ENTITY_SPECS.items():
            if candidate == spec:
                return CORE_FIELD_BY_KEY.get(key, "")
        return ""

    async def _mark_resolved_foreshadows(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        records = await self.feishu_client.list_records("伏笔追踪表")
        by_id = {
            record.get("fields", record).get("伏笔ID"): record
            for record in records
            if record.get("fields", record).get("伏笔ID")
        }
        for item in items:
            foreshadow_id = item.get("伏笔ID")
            if foreshadow_id not in by_id:
                continue
            record = by_id[foreshadow_id]
            await self.guard_layer.write(
                "伏笔追踪表",
                str(record.get("record_id") or foreshadow_id),
                {"回收状态": "已回收/Resolved", "回收方式": item.get("回收方式", "")},
            )
