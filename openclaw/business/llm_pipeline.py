from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from core.config import ROOT_DIR
from llm.base import LLMClient


class PipelineStep(str, Enum):
    OUTLINE = "细纲稿"
    DRAFT = "初稿"
    CONSISTENCY = "一致性稿"
    COMPLIANCE = "合规稿"
    POLISH = "润色稿"
    PROOFREAD = "校对稿"


class PipelineConfigError(RuntimeError):
    pass


STEP_ORDER = [
    PipelineStep.OUTLINE,
    PipelineStep.DRAFT,
    PipelineStep.CONSISTENCY,
    PipelineStep.COMPLIANCE,
    PipelineStep.POLISH,
    PipelineStep.PROOFREAD,
]

STEP_TEMPLATE = {
    PipelineStep.OUTLINE: "outline.j2",
    PipelineStep.DRAFT: "draft.j2",
    PipelineStep.CONSISTENCY: "consistency.j2",
    PipelineStep.COMPLIANCE: "compliance.j2",
    PipelineStep.POLISH: "polish.j2",
    PipelineStep.PROOFREAD: "proofread.j2",
}


class VersionStore(Protocol):
    async def latest_step(self, chapter_id: str) -> PipelineStep | None: ...

    async def load_latest_content(self, chapter_id: str) -> str: ...

    async def save_step(self, chapter_id: str, step: PipelineStep, content: str) -> None: ...


@dataclass(frozen=True)
class PipelineResult:
    chapter_id: str
    final_step: PipelineStep
    final_content: str
    executed_steps: list[PipelineStep]


class FeishuVersionStore:
    def __init__(self, feishu_client: Any) -> None:
        self.feishu_client = feishu_client

    async def latest_step(self, chapter_id: str) -> PipelineStep | None:
        record = await self._latest_record(chapter_id)
        if not record:
            return None
        step_value = record.get("fields", record).get("版本类型")
        try:
            return PipelineStep(step_value)
        except ValueError:
            return None

    async def load_latest_content(self, chapter_id: str) -> str:
        record = await self._latest_record(chapter_id)
        if not record:
            return ""
        return str(record.get("fields", record).get("版本内容") or "")

    async def save_step(self, chapter_id: str, step: PipelineStep, content: str) -> None:
        created_at = datetime.now()
        fields = {
            "版本ID": f"{chapter_id}-{step.name.lower()}-{created_at.strftime('%Y%m%d%H%M%S%f')}",
            "章节ID": chapter_id,
            "版本类型": step.value,
            "版本内容": content,
            "字数": len(content),
            "是否当前最终版": step == PipelineStep.PROOFREAD,
            "创建时间": int(created_at.timestamp() * 1000),
        }
        await self.feishu_client.create_record("正文版本表", fields)
        if step in {PipelineStep.CONSISTENCY, PipelineStep.COMPLIANCE, PipelineStep.PROOFREAD}:
            await self.feishu_client.create_record(
                "质量检查表",
                {
                    "检查ID": f"check-{chapter_id}-{step.name.lower()}-{created_at.strftime('%Y%m%d%H%M%S%f')}",
                    "章节ID": chapter_id,
                    "检查类型": step.value,
                    "检查时间": int(created_at.timestamp() * 1000),
                    "问题列表": content[:2000],
                    "修改建议": "",
                },
            )
        await self.feishu_client.create_record(
            "运行日志表",
            {
                "日志ID": f"pipeline-{chapter_id}-{step.name.lower()}-{created_at.strftime('%Y%m%d%H%M%S%f')}",
                "节点名称": f"llm_pipeline:{step.value}",
                "执行状态": "成功/Success",
                "错误信息": "",
                "输入摘要": chapter_id,
                "输出摘要": f"step={step.value}; chars={len(content)}",
                "重试次数": 0,
            },
        )

    async def _latest_record(self, chapter_id: str) -> dict[str, Any] | None:
        records = await self.feishu_client.list_records("正文版本表")
        matched = [
            record
            for record in records
            if record.get("fields", record).get("章节ID") == chapter_id
            and record.get("fields", record).get("版本类型") in {step.value for step in STEP_ORDER}
        ]
        if not matched:
            return None
        step_rank = {step.value: index for index, step in enumerate(STEP_ORDER)}
        return max(matched, key=lambda record: step_rank[record.get("fields", record).get("版本类型")])


class LLMPipeline:
    def __init__(
        self,
        version_store: VersionStore,
        clients: Mapping[PipelineStep, LLMClient],
        *,
        prompt_dir: Path | None = None,
    ) -> None:
        self.version_store = version_store
        self.clients = clients
        self.prompt_dir = prompt_dir or ROOT_DIR / "prompts"
        self.jinja = Environment(
            loader=FileSystemLoader(self.prompt_dir),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    async def run_chapter(self, chapter: dict[str, Any]) -> PipelineResult:
        chapter_id = str(chapter["章节ID"])
        latest_step = await self.version_store.latest_step(chapter_id)
        previous_content = await self.version_store.load_latest_content(chapter_id)
        start_index = self._next_step_index(latest_step)
        executed_steps: list[PipelineStep] = []
        content = previous_content
        for step in STEP_ORDER[start_index:]:
            if step not in self.clients:
                raise PipelineConfigError(f"missing LLM client for step: {step.value}")
            prompt = self._render_prompt(step, chapter, content)
            content = await self.clients[step].generate(prompt)
            await self.version_store.save_step(chapter_id, step, content)
            executed_steps.append(step)
        return PipelineResult(
            chapter_id=chapter_id,
            final_step=STEP_ORDER[-1],
            final_content=content,
            executed_steps=executed_steps,
        )

    def _next_step_index(self, latest_step: PipelineStep | None) -> int:
        if latest_step is None:
            return 0
        return STEP_ORDER.index(latest_step) + 1

    def _render_prompt(self, step: PipelineStep, chapter: dict[str, Any], previous_content: str) -> str:
        template = self.jinja.get_template(STEP_TEMPLATE[step])
        return template.render(chapter=chapter, previous_content=previous_content, step=step.value)
