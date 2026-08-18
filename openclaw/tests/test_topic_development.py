
from __future__ import annotations

import json

from business.topic_development import TopicDevelopmentPipeline


def test_topic_development_pipeline_generates_market_worldview_and_outlines(tmp_path):
    topics_path = tmp_path / "topics.json"
    topics_path.write_text(json.dumps([
        {
            "topic_id": "TOPIC-1",
            "genre": "??",
            "keywords": ["??", "??", "??", "??", "???"],
            "core_selling_point": "????",
            "target_reader": "??",
            "source": "??????",
            "source_terms": ["??", "??"],
            "rank_heat_score": 85,
            "search_heat_score": 81,
            "trend_score": 83,
            "competition_score": 85,
            "differentiation_score": 70,
            "long_serial_score": 92,
            "compliance_score": 88,
            "total_score": 74,
            "status": "?????",
            "created_at": "2026-08-10T00:00:00",
        }
    ], ensure_ascii=False), encoding="utf-8")

    result, output_path = TopicDevelopmentPipeline(output_dir=tmp_path).run_from_topics_file(topics_path, chapter_count=6)

    assert result.market_validation.decision == "立项通过"
    assert result.market_validation.validation_signals["track_batch_score"] == 25
    assert result.market_validation.test_materials["first_three_chapters"]
    assert result.worldview.title_seed
    assert len(result.chapter_outlines) == 6
    assert result.chapter_outlines[0].memory_updates
    assert output_path.endswith(".json")
