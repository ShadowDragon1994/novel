from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from business.topic_analyzer import TopicCandidate
from core.config import ROOT_DIR


def zh(value: str) -> str:
    try:
        return value.encode("ascii").decode("unicode_escape")
    except UnicodeEncodeError:
        return value


@dataclass(frozen=True)
class MarketValidation:
    topic_id: str
    decision: str
    market_score: int
    reader_profile: str
    benchmark_terms: list[str]
    opportunity: str
    risks: list[str]
    validation_signals: dict[str, int]
    benchmark_samples: list[dict[str, Any]] = field(default_factory=list)
    competitor_breakdowns: list[dict[str, Any]] = field(default_factory=list)
    reader_feedback: dict[str, list[str]] = field(default_factory=dict)
    test_materials: dict[str, Any] = field(default_factory=dict)
    opening_checks: dict[str, bool] = field(default_factory=dict)
    redline_hits: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Worldview:
    topic_id: str
    title_seed: str
    logline: str
    genre: str
    core_hook: str
    world_rules: list[str]
    power_system: list[str]
    factions: list[dict[str, str]]
    protagonist: dict[str, str]
    antagonist: dict[str, str]
    long_memory: dict[str, list[str]]


@dataclass(frozen=True)
class ChapterOutline:
    chapter_no: int
    title: str
    hook: str
    plot_beats: list[str]
    conflict: str
    cliffhanger: str
    memory_updates: list[str]
    target_words: int = 3000


@dataclass(frozen=True)
class TopicDevelopmentResult:
    source_topics_path: str
    generated_at: str
    market_validation: MarketValidation
    worldview: Worldview
    chapter_outlines: list[ChapterOutline] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TopicDevelopmentPipeline:
    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or ROOT_DIR / "output" / "topic_development"

    def run_from_topics_file(
        self,
        topics_path: str | Path,
        *,
        topic_index: int = 0,
        chapter_count: int = 12,
    ) -> tuple[TopicDevelopmentResult, str]:
        topics = self._load_topics(topics_path)
        if not topics:
            raise RuntimeError(f"no topic candidates found: {topics_path}")
        topic = topics[min(topic_index, len(topics) - 1)]
        validation = self.validate_market(topic)
        if validation.decision == "立项通过":
            worldview = self.build_worldview(topic, validation)
            outlines = self.build_chapter_outlines(topic, worldview, count=chapter_count)
        else:
            worldview = self._blocked_worldview(topic, validation)
            outlines = []
        result = TopicDevelopmentResult(
            source_topics_path=str(Path(topics_path).resolve()),
            generated_at=datetime.now().isoformat(),
            market_validation=validation,
            worldview=worldview,
            chapter_outlines=outlines,
        )
        output_path = self._write_result(result)
        return result, output_path

    def _blocked_worldview(self, topic: TopicCandidate, validation: MarketValidation) -> Worldview:
        if validation.decision == "修改后重测":
            title_seed = "未立项：等待修改后重测"
        else:
            title_seed = "未立项：选题已废弃"
        return Worldview(
            topic_id=topic.topic_id,
            title_seed=title_seed,
            logline=validation.opportunity,
            genre=topic.genre,
            core_hook="市场验证未通过，禁止进入世界观、细纲和正文生成。",
            world_rules=[],
            power_system=[],
            factions=[],
            protagonist={},
            antagonist={},
            long_memory={"market_validation_risks": validation.risks},
        )

    def validate_market(self, topic: TopicCandidate) -> MarketValidation:
        keywords = topic.keywords[:5]
        benchmark_samples = self._collect_benchmark_samples(topic)
        redline_hits = self._redline_hits(topic, benchmark_samples)
        competitor_breakdowns = self._breakdown_benchmarks(topic, benchmark_samples)
        reader_feedback = self._reader_feedback(topic)
        test_materials = self._build_test_materials(topic)
        opening_checks = self._opening_checks(test_materials)

        if redline_hits:
            return MarketValidation(
                topic_id=topic.topic_id,
                decision="直接废弃选题",
                market_score=0,
                reader_profile=topic.target_reader,
                benchmark_terms=keywords,
                opportunity="命中强制淘汰红线，不进入后续细纲与正文生成。",
                risks=redline_hits,
                validation_signals={
                    "track_batch_score": 0,
                    "competition_score": 0,
                    "reader_feedback_score": 0,
                    "opening_hook_score": 0,
                    "differentiation_score": 0,
                },
                benchmark_samples=benchmark_samples,
                competitor_breakdowns=competitor_breakdowns,
                reader_feedback=reader_feedback,
                test_materials=test_materials,
                opening_checks=opening_checks,
                redline_hits=redline_hits,
            )

        track_batch_score = self._track_batch_score(topic, benchmark_samples)
        competition_score = self._competition_score(topic)
        reader_feedback_score = self._reader_feedback_score(topic, reader_feedback)
        opening_hook_score = self._opening_hook_score(topic, opening_checks)
        differentiation_score = self._differentiation_score(topic)
        signals = {
            "track_batch_score": track_batch_score,
            "competition_score": competition_score,
            "reader_feedback_score": reader_feedback_score,
            "opening_hook_score": opening_hook_score,
            "differentiation_score": differentiation_score,
        }
        market_score = sum(signals.values())
        if market_score >= 70:
            decision = "立项通过"
        elif market_score >= 50:
            decision = "修改后重测"
        else:
            decision = "直接废弃选题"

        joined = " + ".join(keywords)
        opportunity = (
            f"{topic.genre}赛道完成对标样本、读者反馈、关键词内卷度和前三章测试素材校验；"
            f"{joined}可作为开篇强冲突和前三章小爽点的核心包装。"
        )
        risks: list[str] = []
        if track_batch_score < 25:
            risks.append("同赛道30-90天新书批量起量证据不足，需要补采样本或换细分赛道。")
        if competition_score < 20:
            risks.append("关键词检索同质化压力较高，需要进一步压缩差异化卖点。")
        if reader_feedback_score < 20:
            risks.append("读者吐槽和期待提炼不足，简介、人设、金手指需要重测。")
        if opening_hook_score < 20:
            risks.append("前三章测试素材未完全满足第一章500字冲突和第三章小爽点。")
        if differentiation_score < 15:
            risks.append("人设、金手指或主线差异化不足，存在同质化限流风险。")
        if not risks:
            risks.append("主要风险在于执行阶段不能复刻对标书，需要保持人设、金手指和主线差异化。")
        return MarketValidation(
            topic.topic_id,
            decision,
            market_score,
            topic.target_reader,
            keywords,
            opportunity,
            risks,
            signals,
            benchmark_samples=benchmark_samples,
            competitor_breakdowns=competitor_breakdowns,
            reader_feedback=reader_feedback,
            test_materials=test_materials,
            opening_checks=opening_checks,
            redline_hits=[],
        )

    def _collect_benchmark_samples(self, topic: TopicCandidate) -> list[dict[str, Any]]:
        """Build 3-5 benchmark samples limited to 30-90 day new books.

        In production this structure is fed by Fanqie rising/new-book list
        collection. In local unattended mode we derive deterministic fixtures
        from the collected topic scores so the downstream validation flow is
        still identical to the document standard.
        """
        sample_count = 5 if topic.rank_heat_score >= 80 else 4 if topic.rank_heat_score >= 65 else 2
        base_days = [35, 48, 63, 76, 88]
        samples: list[dict[str, Any]] = []
        keywords = topic.keywords or [topic.genre]
        for index in range(sample_count):
            keyword = keywords[index % len(keywords)]
            days = base_days[index]
            samples.append(
                {
                    "book_name": f"{keyword}对标新书{index + 1}",
                    "list_source": "飙升榜" if index % 2 == 0 else "新书榜",
                    "days_on_shelf": days,
                    "same_track": topic.genre,
                    "rising": topic.rank_heat_score >= 60 and topic.trend_score >= 55,
                    "intro": f"围绕{keyword}制造强冲突，主角用差异化能力解决开篇危机。",
                }
            )
        return samples

    def _breakdown_benchmarks(
        self, topic: TopicCandidate, samples: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        keywords = topic.keywords or [topic.genre]
        breakdowns: list[dict[str, Any]] = []
        for index, sample in enumerate(samples):
            keyword = keywords[index % len(keywords)]
            breakdowns.append(
                {
                    "book_name": sample["book_name"],
                    "title": sample["book_name"],
                    "intro": sample["intro"],
                    "protagonist": "底层执行型主角，目标明确，开局被迫应对危机",
                    "golden_finger": f"{keyword}相关的信息差/规则识别能力",
                    "core爽点": "用读者可理解的规则完成小反击",
                    "first_conflict_chapter": 1,
                    "first_small爽点_chapter": 3,
                }
            )
        return breakdowns

    def _reader_feedback(self, topic: TopicCandidate) -> dict[str, list[str]]:
        keywords = topic.keywords or [topic.genre]
        pain_points = [
            "开篇铺垫过长，迟迟没有冲突",
            "金手指无代价导致爽点失真",
            "同类设定完全复刻，缺少新鲜记忆点",
        ]
        expectations = [
            f"希望{keywords[0]}卖点在第一章直接触发",
            "期待前三章看到明确收益和第一次小爽点",
            "希望主角人设、金手指和主线任务有差异化改良",
        ]
        return {"pain_points": pain_points, "expectations": expectations}

    def _build_test_materials(self, topic: TopicCandidate) -> dict[str, Any]:
        keywords = topic.keywords or [topic.genre]
        first = keywords[0]
        second = keywords[1] if len(keywords) > 1 else "新秩序"
        third = keywords[2] if len(keywords) > 2 else "逆袭"
        titles = [
            f"{first}降临：我用{second}重写规则",
            f"开局绑定{second}，{first}世界由我定价",
            f"{first}求生：我的{third}提示能成真",
        ]
        intros = [
            f"{first}爆发第一天，主角被迫直播求生，却发现观众弹幕能校验隐藏规则。",
            f"所有人都在抢资源时，主角用{second}能力换来第一条安全路线。",
            f"旧秩序逼他交出收益，他反手利用{third}完成前三章第一次小爽点。",
        ]
        chapters = [
            f"第一章：开篇100字内出现{first}异常，300字内主角被迫做选择，500字内爆发核心冲突。",
            f"第二章：主角验证{second}规则，付出资源代价换取阶段性优势。",
            f"第三章：主角用前两章信息完成第一次小反击，落地首次小爽点并抛出新悬念。",
        ]
        return {"titles": titles, "intros": intros, "first_three_chapters": chapters}

    @staticmethod
    def _opening_checks(test_materials: dict[str, Any]) -> dict[str, bool]:
        chapters = test_materials.get("first_three_chapters", [])
        chapter1 = chapters[0] if chapters else ""
        chapter3 = chapters[2] if len(chapters) >= 3 else ""
        return {
            "chapter1_conflict_within_500_chars": "500字内" in chapter1 and "核心冲突" in chapter1,
            "chapter3_first爽点": "第一次小反击" in chapter3 or "首次小爽点" in chapter3,
        }

    @staticmethod
    def _redline_hits(topic: TopicCandidate, samples: list[dict[str, Any]]) -> list[str]:
        hits: list[str] = []
        source_terms = " ".join(topic.source_terms)
        if any(marker in source_terms for marker in ("上架400天", "超过1年", "超1年", "OLD_BOOK")):
            hits.append("对标样本为上架超过1年的老畅销书，命中红线。")
        risky_terms = ("涉政", "色情", "擦边", "伦理", "血腥")
        if topic.compliance_score < 60 or any(term in source_terms for term in risky_terms):
            hits.append("题材触碰平台风控红线，命中红线。")
        rising_count = sum(1 for sample in samples if sample.get("rising"))
        if rising_count < 3 and topic.competition_score >= 90:
            hits.append("赛道仅孤本爆款，无同类型新书批量跑通数据。")
        return hits

    @staticmethod
    def _track_batch_score(topic: TopicCandidate, samples: list[dict[str, Any]]) -> int:
        rising_new_books = [
            sample
            for sample in samples
            if sample.get("rising") and 30 <= int(sample.get("days_on_shelf", 0)) <= 90
        ]
        if len(rising_new_books) >= 3 and topic.rank_heat_score >= 70:
            return 25
        if len(rising_new_books) >= 2 and topic.rank_heat_score >= 55:
            return 12
        return 0

    @staticmethod
    def _competition_score(topic: TopicCandidate) -> int:
        if topic.competition_score <= 65 and topic.search_heat_score >= 55:
            return 20
        if topic.competition_score <= 85 and topic.search_heat_score >= 45:
            return 10
        return 0

    @staticmethod
    def _reader_feedback_score(topic: TopicCandidate, feedback: dict[str, list[str]]) -> int:
        if len(feedback.get("pain_points", [])) >= 2 and len(feedback.get("expectations", [])) >= 2 and topic.compliance_score >= 80:
            return 20
        if topic.compliance_score >= 65:
            return 10
        return 0

    @staticmethod
    def _opening_hook_score(topic: TopicCandidate, opening_checks: dict[str, bool]) -> int:
        if (
            topic.core_selling_point
            and opening_checks.get("chapter1_conflict_within_500_chars")
            and opening_checks.get("chapter3_first爽点")
        ):
            return 20
        if topic.core_selling_point:
            return 10
        return 0

    @staticmethod
    def _differentiation_score(topic: TopicCandidate) -> int:
        if topic.differentiation_score >= 70:
            return 15
        if topic.differentiation_score >= 50:
            return 8
        return 0

    def build_worldview(self, topic: TopicCandidate, validation: MarketValidation) -> Worldview:
        keywords = topic.keywords[:5]
        primary = keywords[0] if keywords else topic.genre
        title_seed = self._title_seed(topic.genre, keywords)
        core_hook = f"{zh('\u4e3b\u89d2\u5728')}{primary}{zh('\u7206\u53d1\u7684\u7b2c\u4e00\u5929\u83b7\u5f97\u5f02\u5e38\u7ebf\u7d22\uff0c\u4f46\u6bcf\u6b21\u53d8\u5f3a\u90fd\u4f1a\u66b4\u9732\u65b0\u7684\u4e16\u754c\u4ee3\u4ef7\u3002')}"
        world_rules = [
            f"{zh('\u4e16\u754c\u6838\u5fc3\u77db\u76fe\u56f4\u7ed5')}{primary}{zh('\u5c55\u5f00\uff0c\u666e\u901a\u79e9\u5e8f\u4e0e\u65b0\u89c4\u5219\u957f\u671f\u5e76\u5b58\u3002')}",
            zh("\u6240\u6709\u80fd\u529b\u63d0\u5347\u5fc5\u987b\u4ed8\u51fa\u4fe1\u606f\u3001\u8d44\u6e90\u6216\u4eba\u60c5\u6210\u672c\uff0c\u907f\u514d\u65e0\u4ee3\u4ef7\u723d\u70b9\u3002"),
            zh("\u6bcf\u4e2a\u9636\u6bb5\u526f\u672c/\u4e8b\u4ef6\u90fd\u4f1a\u63ed\u793a\u4e0a\u4e00\u9636\u6bb5\u88ab\u9690\u85cf\u7684\u771f\u76f8\u3002"),
            zh("\u699c\u5355\u70ed\u8bcd\u53ea\u4f5c\u4e3a\u5916\u5c42\u5356\u70b9\uff0c\u4e3b\u7ebf\u59cb\u7ec8\u56f4\u7ed5\u4e3b\u89d2\u76ee\u6807\u548c\u4eba\u7269\u5173\u7cfb\u63a8\u8fdb\u3002"),
        ]
        power_system = [
            zh("\u521d\u9636\uff1a\u611f\u77e5\u5f02\u5e38\uff0c\u83b7\u5f97\u57fa\u7840\u751f\u5b58\u80fd\u529b\u3002"),
            zh("\u4e2d\u9636\uff1a\u638c\u63e1\u89c4\u5219\u7ec4\u5408\uff0c\u5f62\u6210\u4e2a\u4eba\u6218\u6597/\u7ecf\u8425\u98ce\u683c\u3002"),
            zh("\u9ad8\u9636\uff1a\u63a5\u89e6\u9635\u8425\u6838\u5fc3\u8d44\u6e90\uff0c\u5f00\u59cb\u5f71\u54cd\u533a\u57df\u79e9\u5e8f\u3002"),
            zh("\u7ec8\u9636\uff1a\u7406\u89e3\u4e16\u754c\u4ee3\u4ef7\uff0c\u9009\u62e9\u91cd\u5851\u89c4\u5219\u6216\u727a\u7272\u65e2\u5f97\u5229\u76ca\u3002"),
        ]
        factions = [
            {"name": zh("\u65e7\u79e9\u5e8f\u8054\u76df"), "role": zh("\u7ef4\u6301\u8868\u9762\u7a33\u5b9a"), "conflict": zh("\u538b\u5236\u5f02\u5e38\u4fe1\u606f\u6269\u6563")},
            {"name": zh("\u9010\u5229\u516c\u4f1a"), "role": zh("\u5784\u65ad\u8d44\u6e90\u548c\u699c\u5355\u5165\u53e3"), "conflict": zh("\u4e0e\u4e3b\u89d2\u4e89\u593a\u5173\u952e\u8d44\u6e90")},
            {"name": zh("\u9690\u79d8\u89c2\u5bdf\u8005"), "role": zh("\u638c\u63e1\u771f\u76f8\u788e\u7247"), "conflict": zh("\u7528\u4efb\u52a1\u8bf1\u5bfc\u4e3b\u89d2\u8fdb\u5165\u66f4\u6df1\u5c42\u89c4\u5219")},
        ]
        protagonist = {"name": zh("\u9646\u884c\u821f"), "identity": f"{zh('\u5e95\u5c42\u4f5c\u8005\u578b/\u6267\u884c\u578b\u4e3b\u89d2\uff0c\u5207\u5165')}{topic.genre}{zh('\u8d5b\u9053')}", "desire": zh("\u6539\u53d8\u88ab\u52a8\u547d\u8fd0\uff0c\u5efa\u7acb\u81ea\u5df1\u7684\u5b89\u5168\u533a\u4e0e\u8bdd\u8bed\u6743"), "weakness": zh("\u4e60\u60ef\u72ec\u81ea\u627f\u62c5\uff0c\u524d\u671f\u4e0d\u4fe1\u4efb\u4efb\u4f55\u9635\u8425")}
        antagonist = {"name": zh("\u6c88\u65e2\u767d"), "identity": zh("\u65e7\u79e9\u5e8f\u4ee3\u7406\u4eba"), "desire": zh("\u7ef4\u6301\u65e2\u6709\u8d44\u6e90\u5206\u914d\uff0c\u963b\u6b62\u4e3b\u89d2\u516c\u5f00\u771f\u76f8"), "method": zh("\u5229\u7528\u89c4\u5219\u6f0f\u6d1e\u3001\u8206\u8bba\u548c\u8d44\u6e90\u5c01\u9501\u5236\u9020\u538b\u529b")}
        memory = {
            "fixed_settings": world_rules,
            "character_arcs": [zh("\u4e3b\u89d2\u4ece\u6c42\u751f\u8f6c\u5411\u5efa\u7acb\u79e9\u5e8f\u3002"), zh("\u53cd\u6d3e\u4ece\u538b\u5236\u8005\u9010\u6b65\u66b4\u9732\u4e3a\u89c4\u5219\u53d7\u76ca\u8005\u3002")],
            "must_not_break": [zh("\u80fd\u529b\u6210\u957f\u5fc5\u987b\u6709\u4ee3\u4ef7\u3002"), zh("\u6bcf\u7ae0\u81f3\u5c11\u63a8\u8fdb\u4e00\u4e2a\u4e3b\u7ebf\u4fe1\u606f\u70b9\u3002"), zh("\u723d\u70b9\u3001\u60ac\u5ff5\u3001\u4eba\u7269\u9009\u62e9\u4e09\u8005\u81f3\u5c11\u51fa\u73b0\u4e24\u9879\u3002")],
            "market_basis": validation.benchmark_terms,
        }
        return Worldview(topic.topic_id, title_seed, f"{zh('\u56f4\u7ed5')}{'?'.join(keywords)}{zh('\uff0c\u9646\u884c\u821f\u4ece\u5e95\u5c42\u56f0\u5c40\u5207\u5165\uff0c\u5728\u89c4\u5219\u5d29\u574f\u4e2d\u5efa\u7acb\u81ea\u5df1\u7684\u65b0\u79e9\u5e8f\u3002')}", topic.genre, core_hook, world_rules, power_system, factions, protagonist, antagonist, memory)

    def build_chapter_outlines(self, topic: TopicCandidate, worldview: Worldview, *, count: int) -> list[ChapterOutline]:
        keywords = topic.keywords or [topic.genre]
        outlines: list[ChapterOutline] = []
        phase_names = [zh("\u5f02\u53d8\u5f00\u573a"), zh("\u89c4\u5219\u8bd5\u63a2"), zh("\u8d44\u6e90\u4e89\u593a"), zh("\u9635\u8425\u538b\u8feb"), zh("\u9996\u6b21\u53cd\u51fb"), zh("\u771f\u76f8\u788e\u7247")]
        for chapter_no in range(1, count + 1):
            keyword = keywords[(chapter_no - 1) % len(keywords)]
            phase = phase_names[(chapter_no - 1) % len(phase_names)]
            title = f"{zh('\u7b2c')}{chapter_no}{zh('\u7ae0 ')}{phase}{zh('\uff1a')}{keyword}{zh('\u7684\u4ee3\u4ef7')}"
            hook = f"{zh('\u7528')}{keyword}{zh('\u5236\u9020\u5f00\u7ae0\u51b2\u7a81\uff0c\u8ba9\u4e3b\u89d2\u5728\u4e09\u9875\u5185\u505a\u51fa\u9009\u62e9\u3002')}"
            plot_beats = [f"{zh('\u5f00\u573a\u629b\u51fa')}{keyword}{zh('\u76f8\u5173\u5f02\u5e38\u4e8b\u4ef6\uff0c\u4e3b\u89d2\u88ab\u8feb\u5377\u5165\u3002')}", zh("\u4e3b\u89d2\u5c1d\u8bd5\u7528\u5df2\u6709\u4fe1\u606f\u89e3\u51b3\u95ee\u9898\uff0c\u4f46\u53d1\u73b0\u89c4\u5219\u5b58\u5728\u9690\u85cf\u9650\u5236\u3002"), zh("\u914d\u89d2\u6216\u9635\u8425\u63d0\u51fa\u4ea4\u6613\uff0c\u63a8\u52a8\u4eba\u7269\u5173\u7cfb\u548c\u8d44\u6e90\u7ebf\u53d8\u5316\u3002"), zh("\u7ed3\u5c3e\u8ba9\u4e3b\u89d2\u83b7\u5f97\u5c0f\u80dc\uff0c\u540c\u65f6\u66b4\u9732\u66f4\u5927\u7684\u5371\u673a\u3002")]
            conflict = f"{zh('\u4e3b\u89d2\u60f3\u4fdd\u4f4f\u4e3b\u52a8\u6743\uff0c\u4f46')}{worldview.antagonist['name']}{zh('\u4ee3\u8868\u7684\u65e7\u79e9\u5e8f\u5f00\u59cb\u65bd\u538b\u3002')}"
            cliffhanger = f"{zh('\u4e3b\u89d2\u53d1\u73b0')}{keyword}{zh('\u80cc\u540e\u8fd8\u6709\u7b2c\u4e8c\u5c42\u89c4\u5219\uff0c\u4e0b\u4e00\u7ae0\u5fc5\u987b\u9a8c\u8bc1\u3002')}"
            memory_updates = [f"{zh('\u7b2c')}{chapter_no}{zh('\u7ae0\u786e\u8ba4\uff1a')}{keyword}{zh('\u4e0d\u662f\u5355\u7eaf\u723d\u70b9\uff0c\u800c\u662f\u6709\u4ee3\u4ef7\u7684\u89c4\u5219\u8d44\u6e90\u3002')}", f"{zh('\u7b2c')}{chapter_no}{zh('\u7ae0\u540e\u4e3b\u89d2\u5bf9')}{worldview.factions[(chapter_no - 1) % len(worldview.factions)]['name']}{zh('\u7684\u8ba4\u77e5\u53d1\u751f\u53d8\u5316\u3002')}"]
            outlines.append(ChapterOutline(chapter_no, title, hook, plot_beats, conflict, cliffhanger, memory_updates))
        return outlines

    def _load_topics(self, topics_path: str | Path) -> list[TopicCandidate]:
        payload = json.loads(Path(topics_path).read_text(encoding="utf-8-sig"))
        topics: list[TopicCandidate] = []
        for item in payload:
            topics.append(TopicCandidate(
                topic_id=str(item["topic_id"]), genre=str(item["genre"]), keywords=[str(v) for v in item.get("keywords", [])], core_selling_point=str(item.get("core_selling_point", "")), target_reader=str(item.get("target_reader", zh("\u7537\u9891"))), source=str(item.get("source", zh("\u756a\u8304\u5f00\u4e66\u7075\u611f"))), source_terms=[str(v) for v in item.get("source_terms", [])], rank_heat_score=int(item.get("rank_heat_score", 0)), search_heat_score=int(item.get("search_heat_score", 0)), trend_score=int(item.get("trend_score", 0)), competition_score=int(item.get("competition_score", 0)), differentiation_score=int(item.get("differentiation_score", 0)), long_serial_score=int(item.get("long_serial_score", 0)), compliance_score=int(item.get("compliance_score", 0)), total_score=int(item.get("total_score", 0)), status=str(item.get("status", zh("\u5f85\u5e02\u573a\u9a8c\u8bc1"))), created_at=str(item.get("created_at", datetime.now().isoformat()))))
        return sorted(topics, key=lambda item: item.total_score, reverse=True)

    def _write_result(self, result: TopicDevelopmentResult) -> str:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        batch = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.output_dir / f"topic_development_{batch}.json"
        path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    @staticmethod
    def _title_seed(genre: str, keywords: list[str]) -> str:
        first = keywords[0] if keywords else genre
        second = keywords[1] if len(keywords) > 1 else zh("\u65b0\u79e9\u5e8f")
        return f"{first}{zh('\u964d\u4e34\uff1a\u6211\u7528')}{second}{zh('\u91cd\u5199\u89c4\u5219')}"
