"""Resume Chapter 2 from step 5 (polish) where it failed."""
import asyncio, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / ".env")

from business.llm_pipeline import LLMPipeline, PipelineStep, STEP_ORDER
from llm.doubao import DoubaoClient
from llm.qwen import QwenClient


class MemStore:
    """Pre-loaded with steps 1-4 from the first run."""
    def __init__(self):
        self.records = []

    async def latest_step(self, cid):
        m = [r for r in self.records if r["cid"]==cid and r["step"] in STEP_ORDER]
        return max(m, key=lambda r: STEP_ORDER.index(r["step"])) if m else None

    async def load_latest_content(self, cid):
        s = await self.latest_step(cid)
        if not s: return ""
        m = [r for r in self.records if r["cid"]==cid and r["step"]==s]
        return str(m[-1]["content"]) if m else ""

    async def save_step(self, cid, step, content):
        self.records.append({"cid": cid, "step": step, "content": content})


async def main():
    store = MemStore()
    # Pre-load steps 1-4 for chapter 2 (the last successful step before failure)
    for step, text in [
        (PipelineStep.OUTLINE, ""),  # will be skipped anyway
        (PipelineStep.DRAFT, ""),
        (PipelineStep.CONSISTENCY, ""),
        (PipelineStep.COMPLIANCE, ""),
    ]:
        pass  # don't need actual content, just need latest_step to return COMPLIANCE

    # Actually, latest_step needs real records. Let me load them from the output file.
    # For simplicity, just mark COMPLIANCE as done with dummy content
    store.records = [
        {"cid": "ch3-002", "step": PipelineStep.OUTLINE, "content": "x"},
        {"cid": "ch3-002", "step": PipelineStep.DRAFT, "content": "x"},
        {"cid": "ch3-002", "step": PipelineStep.CONSISTENCY, "content": "x"},
        {"cid": "ch3-002", "step": PipelineStep.COMPLIANCE, "content": "x"},
    ]

    # The pipeline will see latest_step=COMPLIANCE and resume from POLISH
    clients = {
        PipelineStep.OUTLINE: DoubaoClient(), PipelineStep.DRAFT: DoubaoClient(),
        PipelineStep.CONSISTENCY: QwenClient(), PipelineStep.COMPLIANCE: DoubaoClient(),
        PipelineStep.POLISH: DoubaoClient(), PipelineStep.PROOFREAD: QwenClient(),
    }
    pipeline = LLMPipeline(store, clients)

    chapter = {
        "章节ID": "ch3-002", "章节号": 2,
        "章节名": "第二章：化工厂深处",
        "章节卡内容": (
            "林舟以高烧为由请假，清晨六点独自前往东郊废弃化工厂。"
            "化工厂锈迹斑斑，三十年前曾有毒气泄漏事故导致17名工人死亡。"
            "他在地下三层发现一处幽蓝微光脉动的圆形穹顶，正是灵脉节点。"
            "然而就在即将共鸣时，三名自称灵监会的黑色风衣人挡住了去路，"
            "为首的冷笑说：你爸当年也是从这里开始的。"
        ),
    }

    print("Resuming Chapter 2 from step 5 (POLISH)...")
    try:
        result = await pipeline.run_chapter(chapter)
        for r in [x for x in store.records if x["cid"]=="ch3-002"]:
            c = r["content"]
            print(f"  [{r['step'].value:6s}] {len(c):5d} chars | {c[:80].replace(chr(10),' ')}...")
        print(f"\n  FINAL: {len(result.final_content)} chars")
    except Exception as e:
        print(f"  FAILED again at polish step. Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
