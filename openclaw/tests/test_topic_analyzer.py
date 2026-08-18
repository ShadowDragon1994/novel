from __future__ import annotations

from business.topic_analyzer import TopicAnalyzer
from device_gateway.fanqie_inspiration_workflow import InspirationPage, InspirationSnapshot


def test_topic_analyzer_generates_ranked_candidates_from_inspiration_text() -> None:
    snapshot = InspirationSnapshot(
        device_id="127.0.0.1:65429",
        collected_at="2026-08-09T19:43:00",
        pages=[
            InspirationPage(
                name="开书灵感",
                text="榜单 热词 游戏降临 全民转职 隐藏职业 副本 系统 末世囤货 重生 灵气复苏",
                collected_at="2026-08-09T19:43:00",
            )
        ],
    )

    topics = TopicAnalyzer().analyze_snapshot(snapshot, limit=5)

    assert topics
    assert topics[0].total_score >= topics[-1].total_score
    assert topics[0].source == "番茄开书灵感"
    assert topics[0].status == "待市场验证"
    assert topics[0].topic_id.startswith("TOPIC-")


def test_topic_analyzer_returns_empty_for_empty_text() -> None:
    assert TopicAnalyzer().analyze_text("开书灵感 常用工具 查看更多") == []
