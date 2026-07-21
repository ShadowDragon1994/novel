from pathlib import Path

import pytest

from business.production_scanner import ProductionScanner
from core.task_lock import TaskLock


class FakeFeishuClient:
    def __init__(self, records) -> None:
        self.records = records

    async def list_records(self, table_name):
        return self.records


class FakePipeline:
    def __init__(self) -> None:
        self.chapters = []

    async def run_chapter(self, chapter):
        self.chapters.append(chapter["章节ID"])


class FakeGuardLayer:
    def __init__(self) -> None:
        self.writes = []

    async def write(self, table, record_id, fields):
        self.writes.append((table, record_id, fields))
        return {"record_id": record_id, "fields": fields}


def make_record(
    record_id,
    chapter_id,
    priority="中/Medium",
    number=1,
    status="待生成细纲/Pending Outline",
    novel_id="n1",
    locked="否/No",
    retries=0,
    revisions=0,
):
    return {
        "record_id": record_id,
        "fields": {
            "章节ID": chapter_id,
            "章节号": number,
            "章节名": f"第{number}章",
            "章节卡内容": "主角行动",
            "任务优先级": priority,
            "生产状态": status,
            "小说ID": novel_id,
            "内容锁定状态": locked,
            "流程重试次数": retries,
            "内容返工次数": revisions,
        },
    }


def make_scanner(records, tmp_path: Path, global_max=5, per_novel_max=2):
    pipeline = FakePipeline()
    guard = FakeGuardLayer()
    scanner = ProductionScanner(
        feishu_client=FakeFeishuClient(records),
        task_lock=TaskLock(tmp_path / "openclaw.sqlite"),
        pipeline=pipeline,
        guard_layer=guard,
        global_max=global_max,
        per_novel_max=per_novel_max,
    )
    return scanner, pipeline, guard


class FakeExtractor:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.chapters = []

    async def extract_after_final(self, chapter_id: str) -> None:
        self.chapters.append(chapter_id)
        if self.fail:
            raise RuntimeError("extract failed")


@pytest.mark.asyncio
async def test_production_scanner_runs_one_chapter_end_to_end(tmp_path: Path) -> None:
    scanner, pipeline, guard = make_scanner([make_record("rec-1", "c1")], tmp_path)
    assert await scanner.run_once() == ["c1"]
    assert pipeline.chapters == ["c1"]
    assert guard.writes == [("章节任务表", "rec-1", {"生产状态": "待人工审核/Pending Review"})]


@pytest.mark.asyncio
async def test_production_scanner_sorts_by_priority_then_chapter_number(tmp_path: Path) -> None:
    records = [
        make_record("rec-2", "c2", "低/Low", 2, novel_id="n2"),
        make_record("rec-1", "c1", "高/High", 3, novel_id="n1"),
        make_record("rec-3", "c3", "高/High", 1, novel_id="n3"),
    ]
    scanner, pipeline, _ = make_scanner(records, tmp_path)
    await scanner.run_once()
    assert pipeline.chapters == ["c3", "c1", "c2"]


@pytest.mark.asyncio
async def test_production_scanner_filters_non_pending_status(tmp_path: Path) -> None:
    records = [make_record("rec-1", "c1", status="已定稿/Finalized")]
    scanner, pipeline, guard = make_scanner(records, tmp_path)
    assert await scanner.run_once() == []
    assert pipeline.chapters == []
    assert guard.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        "待生成细纲",
        "待生成细纲/Pending Outline",
        "待创作/Pending",
        "待生成初稿/Pending Draft",
        "待一致性检查/Pending Consistency",
        "待辅助检查/Pending Compliance",
        "待润色/Pending Polish",
        "待校对/Pending Proofread",
        "返工中/Reworking",
    ],
)
async def test_production_scanner_accepts_all_pending_status_aliases(tmp_path: Path, status: str) -> None:
    records = [make_record("rec-1", "c1", status=status)]
    scanner, pipeline, _ = make_scanner(records, tmp_path)
    assert await scanner.run_once() == ["c1"]
    assert pipeline.chapters == ["c1"]


@pytest.mark.asyncio
async def test_scanner_skips_locked_content(tmp_path: Path) -> None:
    scanner, pipeline, _ = make_scanner([make_record("rec-1", "c1", locked="是/Yes")], tmp_path)
    assert await scanner.run_once() == []
    assert pipeline.chapters == []


@pytest.mark.asyncio
async def test_scanner_skips_max_retries(tmp_path: Path) -> None:
    scanner, pipeline, _ = make_scanner([make_record("rec-1", "c1", retries=3)], tmp_path)
    assert await scanner.run_once() == []
    assert pipeline.chapters == []


@pytest.mark.asyncio
async def test_scanner_skips_max_revisions(tmp_path: Path) -> None:
    scanner, pipeline, _ = make_scanner([make_record("rec-1", "c1", revisions=3)], tmp_path)
    assert await scanner.run_once() == []
    assert pipeline.chapters == []


@pytest.mark.asyncio
async def test_scanner_respects_per_novel_max(tmp_path: Path) -> None:
    records = [make_record(f"rec-{index}", f"c{index}", novel_id="n1", number=index) for index in range(1, 5)]
    scanner, pipeline, _ = make_scanner(records, tmp_path, global_max=5, per_novel_max=2)
    assert await scanner.run_once() == ["c1", "c2"]
    assert pipeline.chapters == ["c1", "c2"]


@pytest.mark.asyncio
async def test_production_scanner_respects_global_max(tmp_path: Path) -> None:
    records = [make_record(f"rec-{index}", f"c{index}", number=index, novel_id=f"n{index}") for index in range(1, 8)]
    scanner, pipeline, _ = make_scanner(records, tmp_path, global_max=5)
    result = await scanner.run_once()
    assert len(result) == 5
    assert len(pipeline.chapters) == 5


@pytest.mark.asyncio
async def test_production_scanner_skips_locked_chapter(tmp_path: Path) -> None:
    records = [make_record("rec-1", "c1")]
    scanner, pipeline, _ = make_scanner(records, tmp_path)
    assert scanner.task_lock.acquire("c1", "external", 1)
    assert await scanner.run_once() == []
    assert pipeline.chapters == []


@pytest.mark.asyncio
async def test_production_scanner_releases_lock_after_success(tmp_path: Path) -> None:
    records = [make_record("rec-1", "c1")]
    scanner, _, _ = make_scanner(records, tmp_path)
    await scanner.run_once()
    assert scanner.task_lock.acquire("c1", "next", 1)


@pytest.mark.asyncio
async def test_production_scanner_releases_lock_after_pipeline_error(tmp_path: Path) -> None:
    class FailingPipeline(FakePipeline):
        async def run_chapter(self, chapter):
            raise RuntimeError("boom")

    records = [make_record("rec-1", "c1")]
    scanner, _, _ = make_scanner(records, tmp_path)
    scanner.pipeline = FailingPipeline()
    assert await scanner.run_once() == []
    assert scanner.task_lock.acquire("c1", "next", 1)


def test_production_scanner_sort_key_unknown_priority_is_last(tmp_path: Path) -> None:
    scanner, _, _ = make_scanner([], tmp_path)
    assert scanner._sort_key(make_record("rec-1", "c1", "未知", 9))[0] == 9


@pytest.mark.asyncio
async def test_production_scanner_calls_settings_extractor_after_success(tmp_path: Path) -> None:
    records = [make_record("rec-1", "c1")]
    scanner, _, _ = make_scanner(records, tmp_path)
    extractor = FakeExtractor()
    scanner.settings_extractor = extractor
    await scanner.run_once()
    assert extractor.chapters == ["c1"]


@pytest.mark.asyncio
async def test_production_scanner_extractor_failure_does_not_block_review(tmp_path: Path) -> None:
    records = [make_record("rec-1", "c1")]
    scanner, _, guard = make_scanner(records, tmp_path)
    scanner.settings_extractor = FakeExtractor(fail=True)
    assert await scanner.run_once() == ["c1"]
    assert any("错误信息" in fields for _, _, fields in guard.writes)


@pytest.mark.asyncio
async def test_production_scanner_close_closes_feishu_and_llm_clients(tmp_path: Path) -> None:
    class ClosableFeishu(FakeFeishuClient):
        def __init__(self) -> None:
            super().__init__([])
            self.closed = False

        async def close(self):
            self.closed = True

    class ClosableClient:
        def __init__(self) -> None:
            self.closed = False

        async def close(self):
            self.closed = True

    feishu = ClosableFeishu()
    llm_client = ClosableClient()
    scanner = ProductionScanner(
        feishu_client=feishu,
        task_lock=TaskLock(tmp_path / "openclaw.sqlite"),
        pipeline=type("Pipeline", (), {"clients": {"x": llm_client}})(),
        guard_layer=FakeGuardLayer(),
    )
    await scanner.close()
    assert feishu.closed
    assert llm_client.closed


@pytest.mark.asyncio
async def test_production_scanner_skips_novel_when_auto_workflow_is_disabled(tmp_path: Path) -> None:
    class TableFeishu(FakeFeishuClient):
        async def list_records(self, table_name):
            if table_name == "小说总览表":
                return [{"fields": {"小说ID": "n1", "自动流程开关": False}}]
            return self.records

    pipeline = FakePipeline()
    scanner = ProductionScanner(
        feishu_client=TableFeishu([make_record("rec-1", "c1")]),
        task_lock=TaskLock(tmp_path / "openclaw.sqlite"),
        pipeline=pipeline,
        guard_layer=FakeGuardLayer(),
    )

    assert await scanner.run_once() == []
    assert pipeline.chapters == []


@pytest.mark.asyncio
async def test_production_scanner_records_pipeline_failure_and_retry(tmp_path: Path) -> None:
    class TableFeishu(FakeFeishuClient):
        def __init__(self, records):
            super().__init__(records)
            self.created = []

        async def list_records(self, table_name):
            if table_name == "小说总览表":
                return [{"fields": {"小说ID": "n1", "自动流程开关": True}}]
            return self.records

        async def create_record(self, table_name, fields):
            self.created.append((table_name, fields))
            return {"record_id": "log-1", "fields": fields}

    class FailingPipeline(FakePipeline):
        async def run_chapter(self, chapter):
            raise RuntimeError("model timeout")

    feishu = TableFeishu([make_record("rec-1", "c1")])
    guard = FakeGuardLayer()
    scanner = ProductionScanner(
        feishu_client=feishu,
        task_lock=TaskLock(tmp_path / "openclaw.sqlite"),
        pipeline=FailingPipeline(),
        guard_layer=guard,
    )

    assert await scanner.run_once() == []
    assert guard.writes[0][2]["流程重试次数"] == 1
    assert "model timeout" in guard.writes[0][2]["错误信息"]
    assert feishu.created[0][0] == "运行日志表"


@pytest.mark.asyncio
async def test_production_scanner_writes_final_version_metadata(tmp_path: Path) -> None:
    class ResultPipeline(FakePipeline):
        async def run_chapter(self, chapter):
            step = type("Step", (), {"value": "校对稿"})()
            return type("Result", (), {"final_content": "最终正文", "final_step": step})()

    scanner, _, guard = make_scanner([make_record("rec-1", "c1")], tmp_path)
    scanner.pipeline = ResultPipeline()
    await scanner.run_once()
    fields = guard.writes[0][2]
    assert fields["最终字数"] == 4
    assert fields["当前版本"] == 1
