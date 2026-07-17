"""Generate 3 chapters in sequence to test cross-chapter consistency."""
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


def chapter_card(text):
    """Wrap card text to avoid quote escaping issues."""
    return text


CH1_CARD = chapter_card(
    "林舟是高三学生，晚自习后在回家路上遭遇诡异黑雾，意外觉醒沉睡的灵脉。"
    "他必须在三天内找到第一个灵气节点——东郊废弃化工厂，否则灵脉暴走反噬。"
    "与此同时，城市暗处开始出现非人的灵兽踪迹。当晚，一头无面獠牙的怪物蹲在对楼水箱上盯了他三秒后消失。"
)

CH2_CARD = chapter_card(
    "林舟以高烧为由请假，清晨六点独自前往东郊废弃化工厂。"
    "化工厂锈迹斑斑，三十年前曾有毒气泄漏事故导致17名工人死亡。"
    "他在地下三层发现一处幽蓝微光脉动的圆形穹顶，正是灵脉节点。"
    "然而就在即将共鸣时，三名自称灵监会的黑色风衣人挡住了去路，"
    "为首的冷笑说：你爸当年也是从这里开始的。"
)

CH3_CARD = chapter_card(
    "林舟被灵监会三人围住，为首者摘下墨镜——竟是他父亲失踪前在地质勘探队的同事老周。"
    "老周告诉他：父亲不是失踪，是被灵监会关押在化工厂地下更深处的灵压监狱，"
    "因为发现了灵气复苏的真相。林舟必须在共鸣节点救父亲和维护公共安全之间做出选择。"
    "倒计时还剩47小时。"
)


async def gen_chapter(pipeline, store, cid, cnum, name, card):
    print(f"\n{'─'*60}")
    print(f"Chapter {cnum}: {name}")
    print(f"{'─'*60}")
    chapter = {"章节ID": cid, "章节号": cnum, "章节名": name, "章节卡内容": card}
    try:
        result = await pipeline.run_chapter(chapter)
    except Exception as e:
        print(f"  FAILED: {e}")
        return None
    for r in [x for x in store.records if x["cid"]==cid]:
        c = r["content"]
        print(f"  [{r['step'].value:6s}] {len(c):5d} chars | {c[:100].replace(chr(10),' ')}...")
    return result


async def main():
    out_path = ROOT / "scripts" / "test_3chapters_output.txt"
    f = out_path.open("w", encoding="utf-8")

    def p(*a, **kw):
        print(*a, **kw)
        kw2 = {k:v for k,v in kw.items() if k != 'file'}
        print(*a, **kw2, file=f)

    p("=" * 60)
    p(f"OpenClaw 3-Chapter Consistency Test")
    p(f"Date: {datetime.now().isoformat()}")
    p("=" * 60)

    clients = {
        PipelineStep.OUTLINE: DeepSeekClient(), PipelineStep.DRAFT: DoubaoClient(),
        PipelineStep.CONSISTENCY: QwenClient(), PipelineStep.COMPLIANCE: WenxinClient(),
        PipelineStep.POLISH: DoubaoClient(), PipelineStep.PROOFREAD: QwenClient(),
    }
    store = MemStore()
    pipeline = LLMPipeline(store, clients)

    chapters = [
        ("ch3-001", 1, "第一章：灵气复苏", CH1_CARD),
        ("ch3-002", 2, "第二章：化工厂深处", CH2_CARD),
        ("ch3-003", 3, "第三章：父亲的秘密", CH3_CARD),
    ]

    for cid, cnum, name, card in chapters:
        await gen_chapter(pipeline, store, cid, cnum, name, card)

    p(f"\n{'='*60}")
    p("SUMMARY")
    p("=" * 60)
    for r in store.records:
        p(f"  Ch{r['cid'][-1]} [{r['step'].value:6s}] {len(r['content']):5d} chars")

    p(f"\nFull output & details: {out_path}")
    f.close()


if __name__ == "__main__":
    asyncio.run(main())
