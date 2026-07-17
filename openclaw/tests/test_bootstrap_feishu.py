import pytest

from scripts.bootstrap_feishu import FeishuBootstrap, build_novel_seed


class FakeFeishuClient:
    def __init__(self, existing=None) -> None:
        self.existing = existing or []
        self.created = []

    async def list_records(self, table_name):
        return [{"fields": {"小说ID": novel_id}} for novel_id in self.existing]

    async def create_record(self, table_name, fields):
        self.created.append((table_name, fields))
        return {"record_id": fields["小说ID"], "fields": fields}


def test_build_novel_seed_contains_required_fields() -> None:
    seed = build_novel_seed(1)
    assert seed["小说ID"] == "NOVEL-01"
    assert seed["自动流程开关"] is False
    assert seed["最低存稿章节数"] == 6


@pytest.mark.asyncio
async def test_bootstrap_initializes_ten_novels() -> None:
    client = FakeFeishuClient()
    result = await FeishuBootstrap(client).initialize_novels()
    assert result.created == 10
    assert result.skipped == 0
    assert len(client.created) == 10
    assert client.created[0][0] == "小说总览表"


@pytest.mark.asyncio
async def test_bootstrap_skips_existing_novels() -> None:
    client = FakeFeishuClient(existing=["NOVEL-01", "NOVEL-03"])
    result = await FeishuBootstrap(client).initialize_novels(count=3)
    assert result.created == 1
    assert result.skipped == 2
    assert [fields["小说ID"] for _, fields in client.created] == ["NOVEL-02"]


@pytest.mark.asyncio
async def test_bootstrap_dry_run_does_not_create_records() -> None:
    client = FakeFeishuClient()
    result = await FeishuBootstrap(client).initialize_novels(count=2, dry_run=True)
    assert result.created == 2
    assert result.skipped == 0
    assert client.created == []


@pytest.mark.asyncio
async def test_bootstrap_initializes_accounts_and_chapter_samples() -> None:
    client = FakeFeishuClient()
    result = await FeishuBootstrap(client).initialize_acceptance_data(
        count=2,
        chapters_per_novel=3,
        finalized_per_novel=1,
    )
    assert result == {"novels": 2, "accounts": 2, "chapters": 6}
    assert sum(table == "账号管理表" for table, _ in client.created) == 2
    chapters = [fields for table, fields in client.created if table == "章节任务表"]
    assert len(chapters) == 6
    assert sum(fields["生产状态"] == "已定稿/Finalized" for fields in chapters) == 2
