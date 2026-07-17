import json

import pytest

from business.settings_extractor import SettingsExtractor


class FakeLLM:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.prompts = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.payload if isinstance(self.payload, str) else json.dumps(self.payload, ensure_ascii=False)


class FakeFeishu:
    def __init__(self) -> None:
        self.tables = {
            "正文版本表": [{"fields": {"章节ID": "c1", "版本类型": "校对稿", "版本内容": "终稿内容"}}],
            "运行日志表": [],
            "章节任务表": [{"fields": {"章节ID": "c1", "小说ID": "n1", "章节卡内容": "章节卡"}}],
            "短期记忆表": [{"fields": {"小说ID": "n1", "摘要": "前情"}}],
            "人物档案表": [],
            "世界观设定表": [],
            "势力组织表": [],
            "伏笔追踪表": [],
        }
        self.created = []

    async def list_records(self, table_name):
        return self.tables.get(table_name, [])

    async def create_record(self, table_name, fields):
        self.created.append((table_name, fields))
        record = {"record_id": f"rec-{len(self.created)}", "fields": fields}
        self.tables.setdefault(table_name, []).append(record)
        return record


class FakeGuard:
    def __init__(self, fail: bool = False) -> None:
        self.writes = []
        self.fail = fail

    async def write(self, table, record_id, fields):
        if self.fail:
            raise PermissionError("core protected")
        self.writes.append((table, record_id, fields))
        return {"record_id": record_id, "fields": fields}


def payload(**kwargs):
    base = {"characters": [], "settings": [], "factions": [], "foreshadows": [], "foreshadows_resolved": []}
    base.update(kwargs)
    return base


@pytest.mark.asyncio
async def test_extract_parses_json_from_llm() -> None:
    extractor = SettingsExtractor(FakeFeishu(), FakeGuard(), FakeLLM(payload()))
    result = await extractor.extract_after_final("c1")
    assert result.entities == payload()


@pytest.mark.asyncio
async def test_extract_new_character_creates_pending_record() -> None:
    feishu = FakeFeishu()
    extractor = SettingsExtractor(
        feishu,
        FakeGuard(),
        FakeLLM(payload(characters=[{"人物名称": "林舟", "性格": "冷静", "角色定位": "待确认/Pending"}])),
    )
    result = await extractor.extract_after_final("c1")
    assert result.created == 1
    assert feishu.created[0][0] == "人物档案表"
    assert feishu.created[0][1]["人物ID"] == "char-c1-01"
    assert feishu.created[0][1]["来源状态"] == "AI自动新增/AI Auto"
    assert feishu.created[0][1]["确认状态"] == "已确认/Confirmed"


@pytest.mark.asyncio
async def test_extract_creates_core_character_as_pending_confirmation() -> None:
    feishu = FakeFeishu()
    extractor = SettingsExtractor(
        feishu,
        FakeGuard(),
        FakeLLM(payload(characters=[{"人物名称": "林舟", "是否核心": "是/Yes"}])),
    )
    await extractor.extract_after_final("c1")
    record = feishu.created[0][1]
    assert record["来源状态"] == "AI建议新增-待确认/AI Pending Confirmation"
    assert record["确认状态"] == "待确认/Pending"
    assert record["是否核心"] is True


@pytest.mark.asyncio
async def test_extract_existing_character_appends_suggestion() -> None:
    feishu = FakeFeishu()
    feishu.tables["人物档案表"] = [{"record_id": "char-1", "fields": {"人物名称": "林舟", "人物变化记录": "旧记录"}}]
    guard = FakeGuard()
    extractor = SettingsExtractor(
        feishu,
        guard,
        FakeLLM(payload(characters=[{"人物名称": "林舟", "人物变化记录": "学会御火"}])),
    )
    result = await extractor.extract_after_final("c1")
    assert result.updated == 1
    assert guard.writes[0][0] == "人物档案表"
    assert "AI建议更新-待确认" in guard.writes[0][2]["人物变化记录"]


@pytest.mark.asyncio
async def test_extract_permission_error_skips_one_entity_and_continues() -> None:
    feishu = FakeFeishu()
    feishu.tables["人物档案表"] = [{"record_id": "char-1", "fields": {"人物名称": "林舟", "人物变化记录": ""}}]
    extractor = SettingsExtractor(
        feishu,
        FakeGuard(fail=True),
        FakeLLM(
            payload(
                characters=[{"人物名称": "林舟", "人物变化记录": "核心变化"}],
                settings=[{"设定名称": "灵潮", "设定内容": "周期性爆发"}],
            )
        ),
    )
    result = await extractor.extract_after_final("c1")
    assert result.updated == 0
    assert result.created == 2
    assert any(table == "世界观设定表" for table, _ in feishu.created)
    assert any(table == "人物档案表" for table, _ in feishu.created)


@pytest.mark.asyncio
async def test_extract_skips_if_already_extracted() -> None:
    feishu = FakeFeishu()
    feishu.tables["运行日志表"] = [{"fields": {"日志ID": "extract-c1", "执行状态": "成功/Success"}}]
    extractor = SettingsExtractor(feishu, FakeGuard(), FakeLLM(payload(characters=[{"人物名称": "林舟"}])))
    result = await extractor.extract_after_final("c1")
    assert result.skipped
    assert not feishu.created


@pytest.mark.asyncio
async def test_extract_new_setting_creates_pending() -> None:
    feishu = FakeFeishu()
    extractor = SettingsExtractor(
        feishu,
        FakeGuard(),
        FakeLLM(payload(settings=[{"设定名称": "灵潮", "设定内容": "周期性爆发"}])),
    )
    await extractor.extract_after_final("c1")
    assert any(table == "世界观设定表" for table, _ in feishu.created)
    record = next(fields for table, fields in feishu.created if table == "世界观设定表")
    assert record["设定ID"] == "setting-c1-01"


@pytest.mark.asyncio
async def test_extract_new_faction_creates_pending() -> None:
    feishu = FakeFeishu()
    extractor = SettingsExtractor(
        feishu,
        FakeGuard(),
        FakeLLM(payload(factions=[{"势力名称": "青岚盟", "核心资源": "灵矿"}])),
    )
    await extractor.extract_after_final("c1")
    record = next(fields for table, fields in feishu.created if table == "势力组织表")
    assert record["势力ID"] == "faction-c1-01"


@pytest.mark.asyncio
async def test_extract_foreshadow_with_chapter_reference() -> None:
    feishu = FakeFeishu()
    extractor = SettingsExtractor(
        feishu,
        FakeGuard(),
        FakeLLM(payload(foreshadows=[{"伏笔内容": "玉佩发烫", "铺设章节": 1}])),
    )
    await extractor.extract_after_final("c1")
    record = next(fields for table, fields in feishu.created if table == "伏笔追踪表")
    assert record["伏笔ID"] == "foreshadow-c1-01"
    assert record["铺设章节"] == 1


@pytest.mark.asyncio
async def test_extract_empty_result_only_writes_log() -> None:
    feishu = FakeFeishu()
    extractor = SettingsExtractor(feishu, FakeGuard(), FakeLLM(payload()))
    result = await extractor.extract_after_final("c1")
    assert result.created == 0
    assert feishu.created[0][0] == "运行日志表"


def test_extract_parses_json_embedded_in_text() -> None:
    extractor = SettingsExtractor(FakeFeishu(), FakeGuard(), FakeLLM(payload()))
    assert extractor._parse_entities(f"说明\n{json.dumps(payload(), ensure_ascii=False)}") == payload()


@pytest.mark.asyncio
async def test_extract_reads_chapter_card_and_memory() -> None:
    llm = FakeLLM(payload())
    extractor = SettingsExtractor(FakeFeishu(), FakeGuard(), llm)
    await extractor.extract_after_final("c1")
    assert "章节卡" in llm.prompts[0] or "前情" in llm.prompts[0]


@pytest.mark.asyncio
async def test_extract_detects_foreshadow_resolution() -> None:
    feishu = FakeFeishu()
    feishu.tables["伏笔追踪表"] = [{"record_id": "f1", "fields": {"伏笔ID": "f-1", "伏笔内容": "玉佩"}}]
    guard = FakeGuard()
    extractor = SettingsExtractor(
        feishu,
        guard,
        FakeLLM(payload(foreshadows_resolved=[{"伏笔ID": "f-1", "回收方式": "玉佩揭示血脉"}])),
    )
    await extractor.extract_after_final("c1")
    assert guard.writes[0] == (
        "伏笔追踪表",
        "f1",
        {"回收状态": "已回收/Resolved", "回收方式": "玉佩揭示血脉"},
    )


@pytest.mark.asyncio
async def test_extract_skips_when_no_proofread() -> None:
    feishu = FakeFeishu()
    feishu.tables["正文版本表"] = []
    extractor = SettingsExtractor(feishu, FakeGuard(), FakeLLM(payload(characters=[{"人物名称": "林舟"}])))
    result = await extractor.extract_after_final("c1")
    assert result.skipped


@pytest.mark.asyncio
async def test_extract_writes_short_term_memory_after_final() -> None:
    feishu = FakeFeishu()
    extractor = SettingsExtractor(feishu, FakeGuard(), FakeLLM(payload()))
    await extractor.extract_after_final("c1")
    memory = next(fields for table, fields in feishu.created if table == "短期记忆表")
    assert memory["关联章节ID"] == "c1"
    assert memory["摘要"] == "终稿内容"


@pytest.mark.asyncio
async def test_extract_creates_long_term_memory_candidate() -> None:
    feishu = FakeFeishu()
    extractor = SettingsExtractor(
        feishu,
        FakeGuard(),
        FakeLLM(payload(long_term_memory=[{"主线": "主角寻找真相", "规则": "灵力守恒", "是否核心": "是/Yes"}])),
    )
    await extractor.extract_after_final("c1")
    memory = next(fields for table, fields in feishu.created if table == "长期记忆表")
    assert memory["确认状态"] == "待确认/Pending"
    assert memory["是否当前生效"] is False


@pytest.mark.asyncio
async def test_extract_creates_pending_suggestion_when_core_record_rejects_append() -> None:
    feishu = FakeFeishu()
    feishu.tables["人物档案表"] = [{"record_id": "char-1", "fields": {"人物名称": "林舟", "人物变化记录": ""}}]
    extractor = SettingsExtractor(
        feishu,
        FakeGuard(fail=True),
        FakeLLM(payload(characters=[{"人物名称": "林舟", "人物变化记录": "身份暴露", "是否核心": "是/Yes"}])),
    )
    await extractor.extract_after_final("c1")
    suggestion = next(fields for table, fields in feishu.created if table == "人物档案表")
    assert suggestion["确认状态"] == "待确认/Pending"


@pytest.mark.asyncio
async def test_extract_writes_mid_term_memory_every_25_chapters() -> None:
    feishu = FakeFeishu()
    feishu.tables["短期记忆表"] = [
        {"fields": {"小说ID": "n1", "关联章节ID": f"old-{index}", "摘要": f"摘要{index}"}}
        for index in range(24)
    ]
    extractor = SettingsExtractor(feishu, FakeGuard(), FakeLLM(payload()))
    await extractor.extract_after_final("c1")
    memory = next(fields for table, fields in feishu.created if table == "中期记忆表")
    assert memory["触发类型"] == "每25章/Every 25 Chapters"
