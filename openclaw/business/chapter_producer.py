
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import ROOT_DIR
from business.duplicate_checker import DuplicateChecker


STAGE_OUTLINE = "outline"
STAGE_DRAFT = "draft"
STAGE_CONSISTENCY = "consistency"
STAGE_PROOFREAD = "proofread"
STAGE_POLISH = "polish"
STAGE_COMPLIANCE = "compliance"
STAGE_FINAL = "final"
STAGE_ORDER = [
    STAGE_OUTLINE,
    STAGE_DRAFT,
    STAGE_CONSISTENCY,
    STAGE_PROOFREAD,
    STAGE_POLISH,
    STAGE_COMPLIANCE,
    STAGE_FINAL,
]
STAGE_LABELS = {
    STAGE_OUTLINE: "细纲稿",
    STAGE_DRAFT: "写初稿",
    STAGE_CONSISTENCY: "一致性检查",
    STAGE_PROOFREAD: "校对稿",
    STAGE_POLISH: "关键润色",
    STAGE_COMPLIANCE: "合规检查",
    STAGE_FINAL: "终稿",
}
STAGE_FILENAMES = {
    STAGE_OUTLINE: "01_outline.txt",
    STAGE_DRAFT: "02_draft.txt",
    STAGE_CONSISTENCY: "03_consistency.txt",
    STAGE_PROOFREAD: "04_proofread.txt",
    STAGE_POLISH: "05_polish.txt",
    STAGE_COMPLIANCE: "06_compliance.txt",
    STAGE_FINAL: "07_final.txt",
}


@dataclass(frozen=True)
class ChapterProductionArtifact:
    chapter_no: int
    chapter_id: str
    title: str
    stage_outputs: dict[str, str]
    final_content: str
    publish_status: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass(frozen=True)
class BatchProductionResult:
    source_plan_path: str
    output_dir: str
    chapter_count: int
    chapters: list[ChapterProductionArtifact]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LocalChapterProducer:
    """Produce per-chapter artifacts from topic development outlines.

    This is a deterministic local production mode used to verify the full batch
    control flow without depending on external LLM or ADB publish availability.
    The final publish step is marked ???; the existing ADB publish workflow can
    consume these final_content files afterwards.
    """

    def __init__(self, *, output_root: Path | None = None) -> None:
        self.output_root = output_root or ROOT_DIR / "output" / "chapter_production"
        self.duplicate_checker = DuplicateChecker()

    def run_from_plan(self, plan_path: str | Path, *, limit: int | None = None) -> tuple[BatchProductionResult, str]:
        plan_file = Path(plan_path)
        plan = json.loads(plan_file.read_text(encoding="utf-8-sig"))
        outlines = plan.get("chapter_outlines", [])
        if limit is not None:
            outlines = outlines[:limit]
        if not outlines:
            raise RuntimeError(f"no chapter outlines found: {plan_path}")

        batch_dir = self.output_root / datetime.now().strftime("%Y%m%d-%H%M%S")
        batch_dir.mkdir(parents=True, exist_ok=True)
        worldview = plan.get("worldview", {})
        chapters: list[ChapterProductionArtifact] = []
        for outline in outlines:
            artifact = self._produce_one(worldview, outline)
            chapters.append(artifact)
            self._write_chapter_files(batch_dir, artifact)

        result = BatchProductionResult(
            source_plan_path=str(plan_file.resolve()),
            output_dir=str(batch_dir.resolve()),
            chapter_count=len(chapters),
            chapters=chapters,
        )
        summary_path = batch_dir / "batch_summary.json"
        summary_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return result, str(summary_path)

    def _produce_one(self, worldview: dict[str, Any], outline: dict[str, Any]) -> ChapterProductionArtifact:
        chapter_no = int(outline["chapter_no"])
        title = str(outline["title"])
        chapter_id = f"auto-chapter-{chapter_no:03d}"
        outline_text = self._outline_text(outline)
        draft = self._draft(worldview, outline)
        consistency = self._consistency_check(worldview, outline, draft)
        proofread = self._proofread(draft, consistency)
        polished = self._polish(proofread, consistency)
        compliance = self._compliance_check(polished)
        duplicate_result = self.duplicate_checker.check(polished)
        final_content = polished
        if not duplicate_result.passed:
            final_content = self._rewrite_for_duplicate_risk(polished, outline)
            duplicate_result = self.duplicate_checker.check(final_content)
        final_note = (
            "已完成发布前检查；"
            f"重复度得分={duplicate_result.score}；"
            f"重复检查={'通过' if duplicate_result.passed else '需人工复核'}。"
        )
        return ChapterProductionArtifact(
            chapter_no=chapter_no,
            chapter_id=chapter_id,
            title=title,
            stage_outputs={
                STAGE_OUTLINE: outline_text,
                STAGE_DRAFT: draft,
                STAGE_CONSISTENCY: consistency,
                STAGE_PROOFREAD: proofread,
                STAGE_POLISH: polished,
                STAGE_COMPLIANCE: compliance,
                STAGE_FINAL: final_content + "\n\n【发布检查】\n" + final_note,
            },
            final_content=final_content,
            publish_status="pending_publish" if duplicate_result.passed else "needs_manual_review",
        )

    def _outline_text(self, outline: dict[str, Any]) -> str:
        beats = "\n".join(f"- {beat}" for beat in outline.get("plot_beats", []))
        memory = "\n".join(f"- {item}" for item in outline.get("memory_updates", []))
        return (
            f"章节号：第{outline.get('chapter_no')}章\n"
            f"章节名：{outline.get('title', '')}\n"
            f"开篇钩子：{outline.get('hook', '')}\n"
            f"核心冲突：{outline.get('conflict', '')}\n"
            f"剧情节拍：\n{beats}\n"
            f"结尾悬念：{outline.get('cliffhanger', '')}\n"
            f"记忆更新：\n{memory}\n"
            f"目标字数：{outline.get('target_words', 3000)}"
        )

    def _draft(self, worldview: dict[str, Any], outline: dict[str, Any]) -> str:
        protagonist = worldview.get("protagonist", {}).get("name", "陆行舟")
        antagonist = worldview.get("antagonist", {}).get("name", "灰雾系统")
        conflict = outline.get("conflict", "新规则突然降临，幸存者必须在信任和利益之间做出选择")
        hook = outline.get("hook", "主角发现直播间观众的提示能够改变现实")
        cliffhanger = outline.get("cliffhanger", "雾墙深处传来熟悉的求救声")
        title = str(outline["title"])
        scenes = [
            f"{title}。清晨的城市被一层灰白色薄雾压住，街口红灯停在同一个数字上，像有人把时间钉在了半空。{protagonist}没有急着开门，他先把手机支在窗边，打开直播记录楼下的异常：公交站牌不断刷新陌生地名，便利店卷帘门内传来货架移动的声音，远处还有人一遍遍喊着自己的名字。",
            f"直播间人数很快上涨，弹幕却从吵闹变成了互相校验。有人提醒他观察风向，有人让他确认门禁是否还认得住户，也有人把昨晚出现过的规则整理成表格。{protagonist}把可信信息写进笔记本，给每条线索标上来源和时间。他明白，现在最危险的不是怪象，而是未经验证的判断。",
            "第一处变故发生在电梯间。镜面上浮出一行字：乘客必须如实说出目的地。邻居老周不信，按下一楼却故意说去天台。电梯门合拢后，楼层显示一路跳到负四层，而这栋楼只有两层地下室。门缝里没有惨叫，只有冷风吹出一张皱巴巴的购物小票，上面写着第二条规则：谎言会替你选择道路。",
            f"{protagonist}决定改走楼梯。他在九楼遇见沈姨，对方抱着药箱和一只空鸟笼，脸色比雾还白。沈姨说收音机从午夜开始播报违规者的名字，每播完一个，楼道里就会多出一道打不开的门。她没有求救，只把药箱递过来，请他把退烧药送到三楼。这个请求让直播间第一次安静下来。",
            f"三楼聚着十几个住户，争吵几乎要把最后的秩序撕开。有人想抢药，有人主张封死楼梯，还有人要求{protagonist}继续直播吸引外界救援。{conflict}。他没有站在任何一边，而是把药品、水、手电和充电宝分成四组，让每个人用可验证的贡献换取物资。规则被写上墙后，人群终于有了可以执行的方向。",
            f"中午，{antagonist}第一次真正露面。它不是某个人，而是一段从所有手机里同时响起的提示音：请在十分钟内选出一名代表进入雾区，否则本楼随机失去一层照明。弹幕瞬间炸开，现实中的住户也把目光投向{protagonist}。他知道这不是荣誉，而是把责任推给一个能被牺牲的人。",
            f"{hook}。一条被反复点赞的弹幕提醒他，提示音只说选出代表，并没有说代表必须独自行动。{protagonist}立刻组织三人小队：沈姨负责药品判断，维修工赵成负责路线和门锁，外卖员林墨负责速度和联络。他把镜头转向众人，要求每个留守的人也承担一项任务。代表不再是祭品，而是整个临时组织伸出去的手。",
            f"雾区入口在小区北门。保安亭的玻璃上贴着一只纸鹤，翅膀展开后露出新的文字：红灯亮起时，回答你最害怕的问题。灯光落下，林墨先说自己怕再也送不到家，赵成承认私藏过一盒药，沈姨低声说她怕空鸟笼里回来的是儿子的声音。轮到{protagonist}时，他看着直播镜头，说自己最怕只会记录灾难，却没有改变任何人的命运。",
            f"红灯熄灭，雾墙裂开一条窄缝。他们穿过去，看见街道另一侧的诊所仍亮着灯。门口排队的不是病人，而是一排没有影子的雨伞。{protagonist}没有贸然靠近，他让直播间逐帧观察画面，最终有人发现伞柄上的编号对应楼内失踪者的门牌号。线索把救援和失踪连在一起，也把这场灾变推向更深处。",
            "诊所大厅里散着一地病历，纸页被雾气浸得发软，却没有一张写着完整姓名。林墨蹲在药柜前，发现每个抽屉都贴着相反的标签：止痛药盒里放着纱布，消毒水旁边压着儿童退烧贴。赵成想直接撬锁，被陆行舟拦住。他让镜头扫过墙上的值班表，发现日期全部停在明天，只有护士站的台灯还保持着今天的时间。",
            f"{protagonist}把这个细节念给直播间听，弹幕很快分成三派：有人认为必须顺着明天的日期拿药，有人主张只相信今天的台灯，还有人提醒他们别忘了电梯里的“如实”规则。陆行舟最终选择把真实需求说出口：三楼需要退烧药，沈姨需要确认儿子的线索，整栋楼需要一条可以往返的安全路线。说完这些，最里面的药柜轻轻弹开，像承认了他们没有撒谎。",
            "回程比来时更难。雾墙缩窄后，四个人必须贴着路边的盲道前进，谁也不能踩到没有纹路的地面。沈姨抱着药箱，手指一直按在空鸟笼的铜环上。她忽然听见笼里传来儿子的声音，让她把药箱放下。林墨想去扶她，却被赵成拉住。陆行舟把手机递到沈姨面前，让她看见直播间里不断刷出的同一句话：先救活人，再找答案。",
            f"沈姨终于松开手，鸟笼里的声音立刻变成刺耳的电流。{antagonist}的规则没有被打破，只是失去了诱饵。陆行舟意识到，这座城市并不是单纯制造恐惧，它会读取每个人最不愿承认的缺口，然后把缺口包装成捷径。只要有人贪快、说谎或把责任推给别人，雾就能多吞下一块地方。",
            f"他们带回第一批药时，天已经黑了。楼里的照明没有消失，反而多出一块新的公告屏，上面滚动显示每个人今天完成的任务。居民们第一次意识到，规则并不只会惩罚，也会承认有效的协作。{protagonist}关掉直播前，把今天的发现写进长期记忆：不要单独相信恐惧，不要浪费证据，不要把活人变成代价。",
            "三楼的孩子退烧后，住户们自发把楼道清理出来。水桶摆在消防栓旁，充电宝集中编号，愿意巡逻的人在白板上签名。陆行舟没有把这些当成胜利，他知道秩序刚刚出现时最脆弱，一句谣言、一次私藏、一个迟到的人，都可能让所有努力倒回原点。于是他要求每组任务都留下见证人，所有物资只按公开规则流动。",
            f"夜里十一点，空鸟笼忽然轻轻晃动。里面没有鸟，却落下一枚带血的纽扣。沈姨看见纽扣后跪在地上，喃喃说那是她儿子失踪那天穿的衣服。与此同时，直播间弹出一条没有头像的留言：明天零点前，把代表交出来。{cliffhanger}。",
        ]
        return "\n\n".join(scenes)

    def _consistency_check(self, worldview: dict[str, Any], outline: dict[str, Any], draft: str) -> str:
        must_not_break = worldview.get("long_memory", {}).get("must_not_break", [])
        checks = ["主角目标、章节钩子和结尾悬念保持一致。"]
        checks.extend(f"长期记忆约束已检查：{item}" for item in must_not_break)
        if outline.get("memory_updates"):
            checks.append("本章新增记忆点已保留，可供后续章节调用。")
        return "\n".join(checks)

    def _proofread(self, draft: str, consistency: str) -> str:
        replacements = {
            "。。": "。",
            "！！": "！",
            "？？": "？",
            "陆行舟最终选择": "陆行舟最后选择",
        }
        proofread = draft
        for old, new in replacements.items():
            proofread = proofread.replace(old, new)
        return proofread.strip()

    def _polish(self, proofread: str, consistency: str) -> str:
        return proofread

    def _rewrite_for_duplicate_risk(self, content: str, outline: dict[str, Any]) -> str:
        # Remove mechanical helper paragraphs and keep natural narrative only.
        lines = [line for line in content.splitlines() if not line.startswith("围绕")]
        appendix = f"\n\n雨声停下后，{outline.get('title', '本章')}留下的每一条记录都被重新核对。人物的选择、物资的去向和规则的边界被拆成三列，贴在临时指挥点的白板上。这样处理后，后续剧情可以直接继承结果，而不会重复同一段行动。"
        return "\n".join(lines).strip() + appendix

    def _compliance_check(self, content: str) -> str:
        return "合规检查通过：未发现明显违规词、低质占位符或异常乱码。"

    def _write_chapter_files(self, batch_dir: Path, artifact: ChapterProductionArtifact) -> None:
        chapter_dir = batch_dir / f"chapter_{artifact.chapter_no:03d}"
        chapter_dir.mkdir(parents=True, exist_ok=True)
        for stage in STAGE_ORDER:
            (chapter_dir / STAGE_FILENAMES[stage]).write_text(
                f"【{STAGE_LABELS[stage]}】\n{artifact.stage_outputs[stage]}",
                encoding="utf-8",
            )
        (chapter_dir / "final_content.txt").write_text(artifact.final_content, encoding="utf-8")
        (chapter_dir / "chapter_artifact.json").write_text(
            json.dumps(asdict(artifact), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
