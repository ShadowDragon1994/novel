
from __future__ import annotations

import json
from pathlib import Path

from business.chapter_producer import LocalChapterProducer, STAGE_ORDER


def test_local_chapter_producer_writes_every_stage_for_every_chapter(tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({
        "worldview": {
            "protagonist": {"name": "???"},
            "antagonist": {"name": "???"},
            "long_memory": {"must_not_break": ["??????????"]},
        },
        "chapter_outlines": [
            {
                "chapter_no": 1,
                "title": "?1? ??",
                "hook": "????",
                "plot_beats": ["??", "??"],
                "cliffhanger": "????",
                "memory_updates": ["???1"],
            },
            {
                "chapter_no": 2,
                "title": "?2? ??",
                "hook": "????2",
                "plot_beats": ["??2"],
                "cliffhanger": "????2",
                "memory_updates": ["???2"],
            },
        ],
    }, ensure_ascii=False), encoding="utf-8")

    result, summary = LocalChapterProducer(output_root=tmp_path / "out").run_from_plan(plan_path)

    assert result.chapter_count == 2
    assert result.chapters[0].publish_status == "pending_publish"
    assert set(result.chapters[0].stage_outputs) == set(STAGE_ORDER)
    assert (tmp_path / "out").exists()
    assert summary.endswith("batch_summary.json")


def test_local_chapter_producer_writes_named_stage_files(tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({
        "worldview": {
            "protagonist": {"name": "陆行舟"},
            "antagonist": {"name": "沈既白"},
            "long_memory": {"must_not_break": ["能力成长必须有代价。"]},
        },
        "chapter_outlines": [
            {
                "chapter_no": 1,
                "title": "第1章 异变开场",
                "hook": "第一章500字内出现核心冲突",
                "plot_beats": ["异常出现", "主角选择", "首次危机"],
                "conflict": "主角想保住主动权，但旧秩序开始施压。",
                "cliffhanger": "主角发现第二层规则。",
                "memory_updates": ["第1章确认规则有代价。"],
            }
        ],
    }, ensure_ascii=False), encoding="utf-8")

    result, _ = LocalChapterProducer(output_root=tmp_path / "out").run_from_plan(plan_path)
    chapter_dir = Path(result.output_dir) / "chapter_001"

    expected_files = [
        "01_outline.txt",
        "02_draft.txt",
        "03_consistency.txt",
        "04_proofread.txt",
        "05_polish.txt",
        "06_compliance.txt",
        "07_final.txt",
    ]
    assert [path.name for path in sorted(chapter_dir.glob("[0-9][0-9]_*.txt"))] == expected_files
    assert (chapter_dir / "01_outline.txt").read_text(encoding="utf-8").startswith("【细纲稿】")
    assert (chapter_dir / "04_proofread.txt").read_text(encoding="utf-8").startswith("【校对稿】")
    final_stage = (chapter_dir / "07_final.txt").read_text(encoding="utf-8")
    publish_body = (chapter_dir / "final_content.txt").read_text(encoding="utf-8")
    assert final_stage.startswith("【终稿】")
    assert publish_body in final_stage
    assert "proofread" in result.chapters[0].stage_outputs
    assert "final" in result.chapters[0].stage_outputs
