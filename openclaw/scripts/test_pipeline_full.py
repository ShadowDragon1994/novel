"""Full 6-step pipeline test with all 4 models."""
import asyncio, sys
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / ".env")

from business.llm_pipeline import LLMPipeline, PipelineStep, STEP_ORDER
from llm.deepseek import DeepSeekClient
from llm.doubao import DoubaoClient
from llm.qwen import QwenClient
from llm.wenxin import WenxinClient


class MemStore:
    def __init__(self): self.records = []
    async def latest_step(self, chapter_id):
        m = [r for r in self.records if r["cid"]==chapter_id and r["step"] in STEP_ORDER]
        return max(m, key=lambda r: STEP_ORDER.index(r["step"])) if m else None
    async def load_latest_content(self, chapter_id):
        s = await self.latest_step(chapter_id)
        if not s: return ""
        m = [r for r in self.records if r["cid"]==chapter_id and r["step"]==s]
        return str(m[-1]["content"]) if m else ""
    async def save_step(self, chapter_id, step, content):
        self.records.append({"cid": chapter_id, "step": step, "content": content})


class Tee:
    def __init__(self, path):
        self.f = path.open("w", encoding="utf-8")
        self.c = sys.stdout
    def write(self, t): self.c.write(t); self.f.write(t)
    def flush(self): self.c.flush(); self.f.flush()
    def close(self): self.f.close()


async def main():
    out = ROOT / "scripts" / "test_pipeline_full_output.txt"
    tee = Tee(out)
    p = lambda *a, **kw: print(*a, **kw, file=tee)

    p("=" * 60)
    p(f"OpenClaw 6-Step Pipeline — 4 Models Full Test")
    p(f"Date: {datetime.now().isoformat()}")
    p("=" * 60)

    clients = {
        PipelineStep.OUTLINE:     DeepSeekClient(),
        PipelineStep.DRAFT:       DoubaoClient(),
        PipelineStep.CONSISTENCY: QwenClient(),
        PipelineStep.COMPLIANCE:  WenxinClient(),
        PipelineStep.POLISH:      DoubaoClient(),
        PipelineStep.PROOFREAD:   QwenClient(),
    }
    p("\nModel assignment:")
    for step, c in clients.items():
        p(f"  {step.value:6s} → {c.model}")

    store = MemStore()
    pipeline = LLMPipeline(store, clients)

    chapter = {
        "章节ID": "e2e-full-001",
        "章节号": 1,
        "章节名": "第一章：灵气复苏",
        "章节卡内容": (
            "林舟是高三学生，晚自习后在回家路上遭遇诡异黑雾，"
            "意外觉醒沉睡的灵脉。他必须在三天内找到第一个灵气节点，否则灵脉暴走反噬。"
            "与此同时，城市暗处开始出现非人的灵兽踪迹。"
        ),
    }
    p(f"\nChapter: {chapter['章节名']}")
    p(f"Card: {chapter['章节卡内容']}")
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
        p(f"  [{r['step'].value:6s}] {len(c):5d} chars | {c[:80].replace(chr(10),' ')}...")

    p(f"\n{'='*60}")
    p(f"FINAL ({len(result.final_content)} chars)")
    p("=" * 60)
    p(result.final_content)

    # Save individual steps
    sd = ROOT / "scripts" / "e2e_steps_full"
    sd.mkdir(exist_ok=True)
    for r in store.records:
        fn = sd / f"{STEP_ORDER.index(r['step'])+1}_{r['step'].value}.txt"
        fn.write_text(r["content"], encoding="utf-8")
    p(f"\nSaved each step to {sd}")
    p("=" * 60)
    tee.close()
    print(f"\nOutput: {out}")


if __name__ == "__main__":
    asyncio.run(main())
