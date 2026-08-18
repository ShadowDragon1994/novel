from __future__ import annotations

import json
from pathlib import Path

from scripts.run_full_flow_once import (
    FLOW_NODES,
    FullFlowConfig,
    FullFlowRunner,
    choose_mode,
    is_approved_plan,
    latest_approved_plan,
)


def test_choose_mode_respects_explicit_mode(tmp_path):
    assert choose_mode(mode="new-book", plan_path=None, output_root=tmp_path, fanqie_has_chapters=True) == "new-book"
    assert choose_mode(mode="continue-book", plan_path=None, output_root=tmp_path, fanqie_has_chapters=False) == "continue-book"


def test_choose_mode_uses_approved_plan_before_phone_state(tmp_path):
    plan = tmp_path / "topic_development" / "topic_development_1.json"
    plan.parent.mkdir()
    plan.write_text(json.dumps({"market_validation": {"decision": "立项通过"}}), encoding="utf-8")

    assert is_approved_plan(plan) is True
    assert latest_approved_plan(tmp_path) == plan
    assert choose_mode(mode="auto", plan_path=plan, output_root=tmp_path, fanqie_has_chapters=False) == "continue-book"


def test_choose_mode_falls_back_to_new_book_without_plan_or_chapters(tmp_path):
    assert choose_mode(mode="auto", plan_path=None, output_root=tmp_path, fanqie_has_chapters=False) == "new-book"


def test_flow_nodes_include_new_and_continue_boundaries():
    assert FLOW_NODES[0] == "adb_connect"
    assert "collect_topic_inspiration" in FLOW_NODES
    assert "market_validation" in FLOW_NODES
    assert "generate_7_stage_chapter" in FLOW_NODES
    assert FLOW_NODES[-1] == "write_run_report"


def test_runner_report_records_artifacts(tmp_path):
    runner = FullFlowRunner(FullFlowConfig(device_id="127.0.0.1:1", mode="continue-book", output_root=tmp_path, dry_run=True))
    runner.record_node("test_node", status="ok", artifact="abc.json")
    report = runner.build_report(status="success")
    assert report["status"] == "success"
    assert report["mode"] == "continue-book"
    assert report["nodes"][0]["node"] == "test_node"
    assert report["artifacts"]["test_node"] == "abc.json"
