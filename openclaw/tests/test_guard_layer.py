import pytest

from business.guard_layer import GuardLayer


class FakeFeishuClient:
    def __init__(self, record=None) -> None:
        self.record = record or {"fields": {}}
        self.updated = []

    async def get_record(self, table, record_id):
        return self.record

    async def update_record(self, table, record_id, fields):
        self.updated.append((table, record_id, fields))
        return {"table": table, "record_id": record_id, "fields": fields}


@pytest.mark.asyncio
async def test_guard_layer_rejects_empty_fields() -> None:
    guard = GuardLayer(FakeFeishuClient())
    with pytest.raises(PermissionError):
        await guard.write("章节任务表", "rec-1", {})


@pytest.mark.asyncio
async def test_guard_layer_blocks_locked_chapter_content_fields() -> None:
    guard = GuardLayer(FakeFeishuClient({"fields": {"内容锁定状态": "是/Yes"}}))
    with pytest.raises(PermissionError, match="content locked"):
        await guard.write("章节任务表", "rec-1", {"章节名": "新标题"})


@pytest.mark.asyncio
async def test_guard_layer_allows_locked_chapter_publish_status() -> None:
    client = FakeFeishuClient({"fields": {"内容锁定状态": "是/Yes"}})
    guard = GuardLayer(client)
    result = await guard.write("章节任务表", "rec-1", {"发布状态": "发布成功/Published"})
    assert result["fields"] == {"发布状态": "发布成功/Published"}


@pytest.mark.asyncio
async def test_guard_layer_allows_unlocked_chapter_content_fields() -> None:
    client = FakeFeishuClient({"fields": {"内容锁定状态": "否/No"}})
    guard = GuardLayer(client)
    await guard.write("章节任务表", "rec-1", {"章节名": "新标题"})
    assert client.updated


@pytest.mark.asyncio
async def test_guard_layer_blocks_manual_core_character_overwrite() -> None:
    guard = GuardLayer(FakeFeishuClient({"fields": {"来源状态": "人工创建/Manual", "是否核心": "是/Yes"}}))
    with pytest.raises(PermissionError, match="manual core"):
        await guard.write("人物档案表", "rec-1", {"人物名称": "新名字"})


@pytest.mark.asyncio
async def test_guard_layer_allows_manual_core_confirmation_status() -> None:
    client = FakeFeishuClient({"fields": {"来源状态": "人工创建/Manual", "是否核心": "是/Yes"}})
    guard = GuardLayer(client)
    await guard.write("人物档案表", "rec-1", {"确认状态": "已确认/Confirmed"})
    assert client.updated


@pytest.mark.asyncio
async def test_guard_layer_allows_ai_non_core_record_update() -> None:
    client = FakeFeishuClient({"fields": {"来源状态": "AI自动新增/AI Auto", "是否核心": "否/No"}})
    guard = GuardLayer(client)
    await guard.write("人物档案表", "rec-1", {"人物名称": "AI角色"})
    assert client.updated


@pytest.mark.asyncio
async def test_guard_layer_blocks_main_foreshadow_overwrite() -> None:
    guard = GuardLayer(FakeFeishuClient({"fields": {"来源状态": "人工创建/Manual", "是否主线伏笔": "是/Yes"}}))
    with pytest.raises(PermissionError):
        await guard.write("伏笔追踪表", "rec-1", {"伏笔内容": "改写"})
