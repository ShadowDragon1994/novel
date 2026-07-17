"""End-to-end 6-step LLM pipeline test with real API keys.

Usage: python scripts/test_pipeline_e2e.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from business.llm_pipeline import FeishuVersionStore, LLMPipeline, PipelineStep, STEP_ORDER
from llm.deepseek import DeepSeekClient
from llm.doubao import DoubaoClient
from llm.qwen import QwenClient
from llm.wenxin import WenxinClient


class InMemoryVersionStore:
    """Stores versions in memory instead of Feishu, for testing."""

    def __init__(self):
        self.records: list[dict] = []

    async def latest_step(self, chapter_id: str) -> PipelineStep | None:
        matched = [
            r for r in self.records
            if r["chapter_id"] == chapter_id
            and r["step"] in STEP_ORDER
        ]
        if not matched:
            return None
        step_rank = {step: i for i, step in enumerate(STEP_ORDER)}
        return max(matched, key=lambda r: step_rank[r["step"]])

    async def load_latest_content(self, chapter_id: str) -> str:
        step = await self.latest_step(chapter_id)
        if not step:
            return ""
        matched = [r for r in self.records if r["chapter_id"] == chapter_id and r["step"] == step]
        return str(matched[-1]["content"]) if matched else ""

    async def save_step(self, chapter_id: str, step: PipelineStep, content: str) -> None:
        self.records.append({"chapter_id": chapter_id, "step": step, "content": content})


async def main():
    print("=" * 60)
    print("OpenClaw 6-step LLM Pipeline E2E Test")
    print("=" * 60)

    # ---- Build clients ----
    print("\n[1/3] Creating LLM clients ...")
    clients = {
        PipelineStep.OUTLINE:     DeepSeekClient(),
        PipelineStep.DRAFT:       DoubaoClient(),
        PipelineStep.CONSISTENCY: QwenClient(),
        PipelineStep.COMPLIANCE:  WenxinClient(),
        PipelineStep.POLISH:      DoubaoClient(),
        PipelineStep.PROOFREAD:   QwenClient(),
    }
    for step, client in clients.items():
        print(f"  {step.value:8s} → {client.model}")

    # ---- Build pipeline ----
    print("\n[2/3] Building pipeline ...")
    store = InMemoryVersionStore()
    pipeline = LLMPipeline(store, clients)

    # ---- Test chapter context ----
    chapter = {
        "章节ID": "test-e2e-001",
        "章节号": 1,
        "章节名": "第一章：灵气复苏",
        "章节卡内容": (
            "林舟是一名普通高三学生，某天晚自习后，"
            "他在回家路上遇到一场诡异的黑雾。黑雾中，"
            "他觉醒了沉睡的灵脉，发现世界并非表面那样平凡。"
            "他必须在三天内找到第一个灵气节点，否则灵脉会暴走反噬。"
        ),
    }

    print(f"  章节名: {chapter['章节名']}")
    print(f"  章节卡: {chapter['章节卡内容'][:60]}...")

    # ---- Run pipeline ----
    print("\n[3/3] Running 6-step pipeline ...\n")

    try:
        result = await pipeline.run_chapter(chapter)
    except Exception as exc:
        # Check which steps completed before the failure
        completed_steps = [r["step"] for r in store.records if r["chapter_id"] == chapter["章节ID"]]
        if completed_steps:
            print(f"  Pipeline FAILED after completing: {[s.value for s in completed_steps]}")
            for r in store.records:
                print(f"    [{r['step'].value}] {len(r['content'])} chars saved")
        else:
            print(f"  Pipeline FAILED before any step completed")
        print(f"  Error: {exc}")
        return

    print(f"  All 6 steps completed successfully!")
    print(f"  Steps executed: {[s.value for s in result.executed_steps]}")
    print()
    for r in store.records:
        content = r["content"]
        print(f"  [{r['step'].value:6s}] {len(content):5d} chars | {content[:80]}...")
    print()
    print(f"  Final output ({len(result.final_content)} chars):")
    print(f"  ---")
    print(result.final_content[:500])
    print(f"  ---")

    print("=" * 60)
    print("Pipeline E2E test complete!")
    print(f"Total versions saved: {len(store.records)}")
    for r in store.records:
        print(f"  [{r['step'].value}] {len(r['content'])} chars")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
