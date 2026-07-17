from pathlib import Path

import pytest

from business.llm_pipeline import STEP_ORDER, FeishuVersionStore, LLMPipeline, PipelineConfigError, PipelineStep


class FakeClient:
    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self.calls = calls

    async def generate(self, prompt: str) -> str:
        self.calls.append(self.name)
        return f"{self.name} 输出：{prompt[:20]}"


class FakeVersionStore:
    def __init__(self, latest=None, content: str = "") -> None:
        self.latest = latest
        self.content = content
        self.saved = []

    async def latest_step(self, chapter_id: str):
        return self.latest

    async def load_latest_content(self, chapter_id: str) -> str:
        return self.content

    async def save_step(self, chapter_id: str, step: PipelineStep, content: str) -> None:
        self.saved.append((chapter_id, step, content))
        self.latest = step
        self.content = content


def make_pipeline(store: FakeVersionStore) -> tuple[LLMPipeline, list[str]]:
    calls: list[str] = []
    clients = {step: FakeClient(step.value, calls) for step in STEP_ORDER}
    return LLMPipeline(store, clients), calls


@pytest.mark.asyncio
async def test_pipeline_runs_six_steps_and_persists_each_step() -> None:
    store = FakeVersionStore()
    pipeline, calls = make_pipeline(store)
    result = await pipeline.run_chapter({"章节ID": "c1", "章节名": "第一章", "章节卡内容": "主角登场"})
    assert result.executed_steps == STEP_ORDER
    assert len(store.saved) == 6
    assert calls == [step.value for step in STEP_ORDER]


@pytest.mark.asyncio
async def test_pipeline_resumes_from_next_step() -> None:
    store = FakeVersionStore(latest=PipelineStep.CONSISTENCY, content="一致性稿内容")
    pipeline, calls = make_pipeline(store)
    result = await pipeline.run_chapter({"章节ID": "c1", "章节名": "第一章", "章节卡内容": "主角登场"})
    assert result.executed_steps == [PipelineStep.COMPLIANCE, PipelineStep.POLISH, PipelineStep.PROOFREAD]
    assert calls == ["合规稿", "润色稿", "校对稿"]


@pytest.mark.asyncio
async def test_pipeline_does_nothing_when_already_proofread() -> None:
    store = FakeVersionStore(latest=PipelineStep.PROOFREAD, content="终稿")
    pipeline, calls = make_pipeline(store)
    result = await pipeline.run_chapter({"章节ID": "c1", "章节名": "第一章", "章节卡内容": "主角登场"})
    assert result.executed_steps == []
    assert result.final_content == "终稿"
    assert calls == []


def test_pipeline_render_prompt_contains_chinese_chapter_info() -> None:
    store = FakeVersionStore()
    pipeline, _ = make_pipeline(store)
    chapter = {"章节ID": "c1", "章节名": "第一章", "章节卡内容": "主角登场"}
    prompt = pipeline._render_prompt(PipelineStep.OUTLINE, chapter, "")
    assert "中文" in prompt
    assert "第一章" in prompt
    assert "主角登场" in prompt


class FakeFeishuClient:
    def __init__(self) -> None:
        self.records = []
        self.created = []

    async def list_records(self, table_name):
        return self.records

    async def create_record(self, table_name, fields):
        self.created.append((table_name, fields))
        self.records.append({"fields": fields})
        return {"record_id": fields.get("版本ID", f"record-{len(self.created)}"), "fields": fields}


@pytest.mark.asyncio
async def test_feishu_version_store_saves_step() -> None:
    client = FakeFeishuClient()
    store = FeishuVersionStore(client)
    await store.save_step("c1", PipelineStep.OUTLINE, "细纲内容")
    assert client.created[0][0] == "正文版本表"
    assert client.created[0][1]["版本类型"] == "细纲稿"
    assert client.created[0][1]["字数"] == 4


@pytest.mark.asyncio
async def test_feishu_version_store_logs_each_step_and_quality_checks() -> None:
    client = FakeFeishuClient()
    store = FeishuVersionStore(client)
    await store.save_step("c1", PipelineStep.CONSISTENCY, "一致性检查结果")
    assert [table for table, _ in client.created] == ["正文版本表", "质量检查表", "运行日志表"]


@pytest.mark.asyncio
async def test_feishu_version_store_finds_latest_step_by_order() -> None:
    client = FakeFeishuClient()
    client.records = [
        {"fields": {"章节ID": "c1", "版本类型": "细纲稿", "版本内容": "a"}},
        {"fields": {"章节ID": "c1", "版本类型": "润色稿", "版本内容": "b"}},
        {"fields": {"章节ID": "c2", "版本类型": "校对稿", "版本内容": "c"}},
    ]
    store = FeishuVersionStore(client)
    assert await store.latest_step("c1") == PipelineStep.POLISH
    assert await store.load_latest_content("c1") == "b"


def test_all_prompt_templates_are_filled() -> None:
    for path in Path("prompts").glob("*.j2"):
        text = path.read_text(encoding="utf-8")
        assert "Phase 3 placeholder" not in text
        assert "中文" in text


@pytest.mark.asyncio
async def test_pipeline_missing_client_raises_friendly_error() -> None:
    store = FakeVersionStore()
    pipeline = LLMPipeline(store, {})
    with pytest.raises(PipelineConfigError, match="missing LLM client"):
        await pipeline.run_chapter({"章节ID": "c1", "章节名": "第一章", "章节卡内容": "主角登场"})
