from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from business.chapter_validation import validate_chapter_text
from business.guard_layer import GuardLayer
from business.llm_pipeline import FeishuVersionStore, LLMPipeline, PipelineStep
from business.settings_extractor import SettingsExtractor
from core.config import ROOT_DIR, load_settings
from core.feishu_client import FeishuClient
from core.task_lock import TaskLock
from llm.deepseek import DeepSeekClient
from llm.doubao import DoubaoClient
from llm.qwen import QwenClient
from llm.wenxin import WenxinClient

PENDING_PRODUCTION_STATUSES = {
    "待生成细纲",
    "待生成细纲/Pending Outline",
    "待创作/Pending",
    "待生成初稿/Pending Draft",
    "待一致性检查/Pending Consistency",
    "待辅助检查/Pending Compliance",
    "待润色/Pending Polish",
    "待校对/Pending Proofread",
    "返工中/Reworking",
}
LOCKED_VALUES = {"是", "是/Yes", True}
PRIORITY_RANK = {
    "高/High": 0,
    "高": 0,
    "中/Medium": 1,
    "中": 1,
    "低/Low": 2,
    "低": 2,
}


class ProductionScanner:
    def __init__(
        self,
        *,
        feishu_client: FeishuClient | None = None,
        task_lock: TaskLock | None = None,
        pipeline: LLMPipeline | None = None,
        guard_layer: GuardLayer | None = None,
        settings_extractor: SettingsExtractor | None = None,
        global_max: int | None = None,
        per_novel_max: int | None = None,
    ) -> None:
        settings = load_settings()
        db_path = ROOT_DIR / settings.raw.get("paths", {}).get("sqlite", "data/openclaw.sqlite")
        self.feishu_client = feishu_client or FeishuClient()
        self.task_lock = task_lock or TaskLock(Path(db_path))
        self.guard_layer = guard_layer or GuardLayer(self.feishu_client)
        self.pipeline = pipeline or self._build_pipeline(self.feishu_client)
        self.settings_extractor = settings_extractor or SettingsExtractor(self.feishu_client, self.guard_layer)
        self.global_max = global_max or settings.raw.get("concurrency", {}).get("global_max", 5)
        self.per_novel_max = per_novel_max or settings.raw.get("concurrency", {}).get("per_novel_max", 2)

    async def run_once(self) -> list[str]:
        tasks = await self._pending_tasks()
        selected = self._select_with_limits(tasks)
        semaphore = asyncio.Semaphore(self.global_max)
        results = await asyncio.gather(
            *(self._run_one(record, semaphore) for record in selected),
            return_exceptions=True,
        )
        return [result for result in results if isinstance(result, str)]

    async def close(self) -> None:
        close = getattr(self.feishu_client, "close", None)
        if close:
            await close()
        clients = getattr(self.pipeline, "clients", {})
        for client in clients.values():
            client_close = getattr(client, "close", None)
            if client_close:
                await client_close()

    async def _pending_tasks(self) -> list[dict[str, Any]]:
        records = await self.feishu_client.list_records("章节任务表")
        novels = await self.feishu_client.list_records("小说总览表")
        workflow_by_novel = {
            str(item.get("fields", item).get("小说ID") or ""): item.get("fields", item).get("自动流程开关")
            for item in novels
            if item.get("fields", item).get("小说ID")
        }
        pending = []
        for record in records:
            fields = record.get("fields", record)
            if workflow_by_novel.get(str(fields.get("小说ID") or "")) is False:
                continue
            if fields.get("内容锁定状态") in LOCKED_VALUES:
                continue
            if int(fields.get("流程重试次数") or 0) >= 3:
                continue
            if int(fields.get("内容返工次数") or 0) >= 3:
                continue
            if fields.get("生产状态") in PENDING_PRODUCTION_STATUSES:
                pending.append(record)
        return sorted(pending, key=self._sort_key)

    def _select_with_limits(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selected = []
        per_novel_counts: dict[str, int] = {}
        for task in tasks:
            novel_id = str(task.get("fields", task).get("小说ID") or "")
            if per_novel_counts.get(novel_id, 0) >= self.per_novel_max:
                continue
            selected.append(task)
            per_novel_counts[novel_id] = per_novel_counts.get(novel_id, 0) + 1
            if len(selected) >= self.global_max:
                break
        return selected

    async def _run_one(self, record: dict[str, Any], semaphore: asyncio.Semaphore) -> str | None:
        async with semaphore:
            fields = record.get("fields", record)
            chapter_id = str(fields["章节ID"])
            if not self.task_lock.acquire(chapter_id, "llm_pipeline", os.getpid()):
                return None
            try:
                validate_chapter_text(fields)
                pipeline_result = await self.pipeline.run_chapter(fields)
                final_content = str(getattr(pipeline_result, "final_content", "") or "")
                review_fields: dict[str, Any] = {"生产状态": "待人工审核/Pending Review"}
                if final_content:
                    review_fields.update(
                        {
                            "最终字数": len(final_content),
                            "当前版本": int(fields.get("当前版本") or 1),
                            "上下文哈希": hashlib.sha256(final_content.encode("utf-8")).hexdigest(),
                        }
                    )
                await self.guard_layer.write(
                    "章节任务表",
                    record.get("record_id", chapter_id),
                    review_fields,
                )
                if self.settings_extractor:
                    try:
                        await self.settings_extractor.extract_after_final(chapter_id)
                    except Exception as exc:
                        await self.guard_layer.write(
                            "章节任务表",
                            record.get("record_id", chapter_id),
                            {"错误信息": f"SettingsExtractor failed: {exc}"},
                        )
                return chapter_id
            except Exception as exc:
                retries = int(fields.get("流程重试次数") or 0) + 1
                await self.guard_layer.write(
                    "章节任务表",
                    record.get("record_id", chapter_id),
                    {
                        "流程重试次数": retries,
                        "错误信息": str(exc),
                        "生产状态": "失败/Failed" if retries >= 3 else fields.get("生产状态"),
                    },
                )
                await self.feishu_client.create_record(
                    "运行日志表",
                    {
                        "日志ID": f"production-{chapter_id}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                        "节点名称": "production_scanner",
                        "执行状态": "失败/Failed",
                        "错误信息": str(exc),
                        "输入摘要": chapter_id,
                        "输出摘要": "pipeline failed",
                        "重试次数": retries,
                    },
                )
                return None
            finally:
                self.task_lock.release(chapter_id)

    def _sort_key(self, record: dict[str, Any]) -> tuple[int, int]:
        fields = record.get("fields", record)
        priority = PRIORITY_RANK.get(str(fields.get("任务优先级", "")), 9)
        chapter_number = int(fields.get("章节号") or 0)
        return priority, chapter_number

    def _build_pipeline(self, feishu_client: FeishuClient) -> LLMPipeline:
        clients = {
            PipelineStep.OUTLINE: DeepSeekClient(),
            PipelineStep.DRAFT: DoubaoClient(),
            PipelineStep.CONSISTENCY: QwenClient(),
            PipelineStep.COMPLIANCE: WenxinClient(),
            PipelineStep.POLISH: DoubaoClient(),
            PipelineStep.PROOFREAD: QwenClient(),
        }
        return LLMPipeline(FeishuVersionStore(feishu_client), clients)
