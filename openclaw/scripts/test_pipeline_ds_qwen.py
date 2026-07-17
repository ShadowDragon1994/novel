"""6-step pipeline test using only DeepSeek + Qwen (both verified working).

Usage: python scripts/test_pipeline_ds_qwen.py
Output: prints to console AND writes to scripts/test_pipeline_ds_qwen_output.txt
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / ".env")

from business.llm_pipeline import LLMPipeline, PipelineStep, STEP_ORDER
from llm.deepseek import DeepSeekClient
from llm.qwen import QwenClient


class MemStore:
    def __init__(self):
        self.records: list = []

    async def latest_step(self, chapter_id: str):
        matched = [r for r in self.records if r["cid"] == chapter_id and r["step"] in STEP_ORDER]
        if not matched:
            return None
        rank = {s: i for i, s in enumerate(STEP_ORDER)}
        return max(matched, key=lambda r: rank[r["step"]])

    async def load_latest_content(self, chapter_id: str) -> str:
        step = await self.latest_step(chapter_id)
        if not step:
            return ""
        matched = [r for r in self.records if r["cid"] == chapter_id and r["step"] == step]
        return str(matched[-1]["content"]) if matched else ""

    async def save_step(self, chapter_id: str, step, content: str) -> None:
        self.records.append({"cid": chapter_id, "step": step, "content": content})


class Tee:
    """Write to console and file simultaneously."""
    def __init__(self, path: Path):
        self.file = path.open("w", encoding="utf-8")
        self.console = sys.stdout

    def write(self, text):
        self.console.write(text)
        self.file.write(text)

    def flush(self):
        self.console.flush()
        self.file.flush()

    def close(self):
        self.file.close()


async def main():
    out_path = ROOT / "scripts" / "test_pipeline_ds_qwen_output.txt"
    tee = Tee(out_path)
    p = lambda *a, **kw: print(*a, **kw, file=tee)

    p("=" * 60)
    p("OpenClaw 6-Step Pipeline E2E Test")
    p(f"Date: {datetime.now().isoformat()}")
    p("=" * 60)

    clients = {
        PipelineStep.OUTLINE:     DeepSeekClient(),
        PipelineStep.DRAFT:       DeepSeekClient(),
        PipelineStep.CONSISTENCY: QwenClient(),
        PipelineStep.COMPLIANCE:  QwenClient(),
        PipelineStep.POLISH:      DeepSeekClient(),
        PipelineStep.PROOFREAD:   QwenClient(),
    }
    p("\nModel assignment:")
    for step, c in clients.items():
        p(f"  {step.value:6s} → {c.model}")

    store = MemStore()
    pipeline = LLMPipeline(store, clients)

    chapter = {
        "章节ID": "e2e-001",
        "章节号": 1,
        "章节名": "第一章：灵气复苏",
        "章节卡内容": (
            "林舟是高三学生，晚自习后在回家路上遭遇诡异黑雾，"
            "意外觉醒沉睡的灵脉。他必须在三天内找到第一个灵气节点，否则灵脉暴走反噬。"
            "与此同时，城市暗处开始出现非人的灵兽踪迹。"
        ),
    }
    p(f"\nChapter: {chapter['章节名']}")
    p(f"Chapter card: {chapter['章节卡内容']}")
    p(f"\n{'='*60}")
    p("Running pipeline...")
    p("=" * 60)

    try:
        result = await pipeline.run_chapter(chapter)
    except Exception as exc:
        done = [r for r in store.records if r["cid"] == chapter["章节ID"]]
        p(f"\nFAILED after {len(done)} steps:")
        for r in done:
            p(f"  [{r['step'].value}] {len(r['content'])} chars")
        p(f"Error: {exc}")
        tee.close()
        return

    p(f"\n{'='*60}")
    p("ALL 6 STEPS COMPLETE")
    p("=" * 60)
    for r in store.records:
        c = r["content"]
        p(f"  [{r['step'].value:6s}] {len(c):5d} chars | {c[:80].replace(chr(10), ' ')}...")

    p(f"\n{'='*60}")
    p(f"FINAL OUTPUT ({len(result.final_content)} chars)")
    p("=" * 60)
    p(result.final_content)
    p(f"\n{'='*60}")
    p("Test complete. Full output saved to scripts/test_pipeline_ds_qwen_output.txt")
    p("=" * 60)

    # Also save each step's full content separately
    steps_dir = ROOT / "scripts" / "e2e_steps"
    steps_dir.mkdir(exist_ok=True)
    for r in store.records:
        step_name = r["step"].value
        step_file = steps_dir / f"{STEP_ORDER.index(r['step'])+1:01d}_{step_name}.txt"
        step_file.write_text(r["content"], encoding="utf-8")
    p(f"\nIndividual step outputs saved to: {steps_dir}")

    tee.close()


if __name__ == "__main__":
    asyncio.run(main())
