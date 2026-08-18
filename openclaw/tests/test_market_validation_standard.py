from __future__ import annotations

import json

from business.topic_analyzer import TopicCandidate
from business.topic_development import TopicDevelopmentPipeline


def _candidate(**overrides):
    data = dict(
        topic_id="T-1",
        genre="末世",
        keywords=["末世", "直播", "规则怪谈"],
        core_selling_point="直播间观众能校验末世规则",
        target_reader="男频读者",
        source="番茄开书灵感",
        source_terms=["飙升榜", "新书榜"],
        rank_heat_score=82,
        search_heat_score=76,
        trend_score=80,
        competition_score=58,
        differentiation_score=72,
        long_serial_score=85,
        compliance_score=90,
        total_score=78,
        status="待市场验证",
        created_at="2026-08-17T00:00:00",
    )
    data.update(overrides)
    return TopicCandidate(**data)


def test_market_validation_uses_document_scoring_table_and_test_materials():
    topic = _candidate()
    result = TopicDevelopmentPipeline().validate_market(topic)

    assert result.decision == "立项通过"
    assert result.market_score >= 70
    assert result.validation_signals["track_batch_score"] == 25
    assert result.validation_signals["competition_score"] in {10, 20}
    assert result.validation_signals["reader_feedback_score"] == 20
    assert result.validation_signals["opening_hook_score"] == 20
    assert result.validation_signals["differentiation_score"] == 15
    assert len(result.benchmark_samples) >= 3
    assert all(30 <= sample["days_on_shelf"] <= 90 for sample in result.benchmark_samples)
    assert len(result.test_materials["titles"]) == 3
    assert len(result.test_materials["intros"]) == 3
    assert len(result.test_materials["first_three_chapters"]) == 3
    assert result.opening_checks["chapter1_conflict_within_500_chars"] is True
    assert result.opening_checks["chapter3_first爽点"] is True


def test_market_validation_rejects_redline_old_benchmark_or_single_hit():
    old_topic = _candidate(source_terms=["OLD_BOOK:上架400天", "飙升榜"])
    old_result = TopicDevelopmentPipeline().validate_market(old_topic)
    assert old_result.decision == "直接废弃选题"
    assert old_result.market_score == 0
    assert old_result.redline_hits

    single_hit_topic = _candidate(rank_heat_score=45, search_heat_score=35, trend_score=40, competition_score=95)
    single_hit_result = TopicDevelopmentPipeline().validate_market(single_hit_topic)
    assert single_hit_result.decision == "直接废弃选题"
    assert any("孤本爆款" in hit for hit in single_hit_result.redline_hits)


def test_market_validation_modify_and_retest_band():
    topic = _candidate(rank_heat_score=58, search_heat_score=52, trend_score=55, competition_score=74, differentiation_score=55, compliance_score=85)
    result = TopicDevelopmentPipeline().validate_market(topic)
    assert 50 <= result.market_score <= 69
    assert result.decision == "修改后重测"


def test_pipeline_blocks_worldview_and_outlines_when_topic_not_approved(tmp_path):
    topics_path = tmp_path / "topics.json"
    topic = _candidate(
        rank_heat_score=58,
        search_heat_score=52,
        trend_score=55,
        competition_score=74,
        differentiation_score=55,
        compliance_score=85,
    )
    topics_path.write_text(json.dumps([topic.__dict__], ensure_ascii=False), encoding="utf-8")

    result, _ = TopicDevelopmentPipeline(output_dir=tmp_path).run_from_topics_file(topics_path)

    assert result.market_validation.decision == "修改后重测"
    assert result.chapter_outlines == []
    assert result.worldview.title_seed == "未立项：等待修改后重测"
