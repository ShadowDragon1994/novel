from datetime import datetime, timedelta

import pytest

from business.publish_scanner import PublishScanner


class FakeFeishu:
    def __init__(self, chapters=None, records=None, novels=None, accounts=None) -> None:
        self.chapters = [] if chapters is None else chapters
        self.records = [] if records is None else records
        default_novels = [{"fields": {"小说ID": "n1", "关联账号": "acc-1", "自动发布开关": True}}]
        default_accounts = [{"record_id": "acc-1", "fields": {"账号ID": "acc-1", "账号状态": "正常/Normal"}}]
        self.novels = default_novels if novels is None else novels
        self.accounts = default_accounts if accounts is None else accounts
        self.created = []
        self.updated = []

    async def list_records(self, table_name):
        return {
            "章节任务表": self.chapters,
            "发布记录表": self.records,
            "小说总览表": self.novels,
            "账号管理表": self.accounts,
        }.get(table_name, [])

    async def create_record(self, table_name, fields):
        self.created.append((table_name, fields))
        return {"record_id": f"rec-{len(self.created)}", "fields": fields}

    async def update_record(self, table_name, record_id, fields):
        self.updated.append((table_name, record_id, fields))
        return {"record_id": record_id, "fields": fields}


class FakeGuard:
    def __init__(self) -> None:
        self.writes = []

    async def write(self, table, record_id, fields):
        self.writes.append((table, record_id, fields))
        return {"record_id": record_id, "fields": fields}


class FakeDevice:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = []

    async def publish_chapter(self, chapter_id, account_id):
        self.calls.append((chapter_id, account_id))
        if self.fail:
            raise RuntimeError("device failed")


def chapter(
    chapter_id="c1",
    planned_at=None,
    status="待发布/Pending Publish",
    attempts=0,
    production_status="已定稿/Finalized",
    locked="是/Yes",
    current_version=1,
):
    return {
        "record_id": f"rec-{chapter_id}",
        "fields": {
            "章节ID": chapter_id,
            "小说ID": "n1",
            "发布状态": status,
            "生产状态": production_status,
            "内容锁定状态": locked,
            "当前版本": current_version,
            "计划发布时间": (planned_at or datetime.now() - timedelta(minutes=1)).isoformat(),
            "流程重试次数": attempts,
        },
    }


def make_scanner(feishu, device=None):
    guard = FakeGuard()
    scanner = PublishScanner(feishu, guard, device or FakeDevice())
    return scanner, guard, scanner.device


@pytest.mark.asyncio
async def test_scanner_picks_ready_chapter() -> None:
    scanner, _, _ = make_scanner(FakeFeishu(chapters=[chapter("c1")]))
    ready = await scanner._ready_chapters(datetime.now())
    assert ready[0]["fields"]["章节ID"] == "c1"


@pytest.mark.asyncio
async def test_scanner_skips_future_chapter() -> None:
    scanner, _, _ = make_scanner(FakeFeishu(chapters=[chapter("c1", datetime.now() + timedelta(hours=1))]))
    assert await scanner._ready_chapters(datetime.now()) == []


@pytest.mark.asyncio
async def test_scanner_skips_already_published() -> None:
    feishu = FakeFeishu(
        chapters=[chapter("c1")],
        records=[{"fields": {"章节ID": "c1", "发布尝试状态": "成功/Success"}}],
    )
    scanner, _, device = make_scanner(feishu)
    assert await scanner.run_once() == []
    assert device.calls == []


@pytest.mark.asyncio
async def test_scanner_calls_device_controller() -> None:
    scanner, _, device = make_scanner(FakeFeishu(chapters=[chapter("c1")]))
    await scanner.run_once()
    assert device.calls == [("c1", "acc-1")]


@pytest.mark.asyncio
async def test_scanner_marks_success_on_device_ok() -> None:
    feishu = FakeFeishu(chapters=[chapter("c1")])
    scanner, guard, _ = make_scanner(feishu)
    assert await scanner.run_once() == ["c1"]
    assert feishu.created[0][0] == "发布记录表"
    assert feishu.created[0][1]["发布尝试状态"] == "成功/Success"
    assert guard.writes[0][2]["发布状态"] == "发布成功/Published"


@pytest.mark.asyncio
async def test_scanner_marks_failure_on_device_error() -> None:
    feishu = FakeFeishu(chapters=[chapter("c1")])
    scanner, guard, _ = make_scanner(feishu, FakeDevice(fail=True))
    assert await scanner.run_once() == []
    assert feishu.created[0][1]["发布尝试状态"] == "失败/Failed"
    assert guard.writes[0][2]["发布状态"] == "待发布/Pending Publish"


@pytest.mark.asyncio
async def test_scanner_retries_up_to_max() -> None:
    feishu = FakeFeishu(chapters=[chapter("c1", attempts=2)])
    scanner, guard, _ = make_scanner(feishu, FakeDevice(fail=True))
    await scanner.run_once()
    assert guard.writes[0][2]["流程重试次数"] == 3
    assert guard.writes[0][2]["发布状态"] == "发布失败/Publish Failed"


@pytest.mark.asyncio
async def test_scanner_handles_empty_queue() -> None:
    scanner, _, _ = make_scanner(FakeFeishu(chapters=[]))
    assert await scanner.run_once() == []


@pytest.mark.asyncio
async def test_scanner_resolves_account_from_account_table() -> None:
    feishu = FakeFeishu(
        chapters=[chapter("c1")],
        novels=[{"fields": {"小说ID": "n1", "自动发布开关": True}}],
        accounts=[{"record_id": "acc-rec", "fields": {"绑定小说ID": "n1", "账号ID": "acc-2"}}],
    )
    scanner, _, device = make_scanner(feishu)
    await scanner.run_once()
    assert device.calls == [("c1", "acc-2")]


@pytest.mark.asyncio
async def test_scanner_missing_account_marks_failure() -> None:
    feishu = FakeFeishu(chapters=[chapter("c1")], novels=[], accounts=[])
    scanner, guard, device = make_scanner(feishu)
    await scanner._publish_one(feishu.chapters[0])
    assert device.calls == []
    assert "missing account_id" in guard.writes[0][2]["错误信息"]


@pytest.mark.asyncio
async def test_scanner_skips_when_novel_auto_publish_off() -> None:
    feishu = FakeFeishu(chapters=[chapter("c1")], novels=[{"fields": {"小说ID": "n1", "自动发布开关": False}}])
    scanner, _, _ = make_scanner(feishu)
    assert await scanner.run_once() == []


@pytest.mark.asyncio
async def test_scanner_skips_non_finalized() -> None:
    scanner, _, _ = make_scanner(FakeFeishu(chapters=[chapter("c1", production_status="待人工审核/Pending Review")]))
    assert await scanner.run_once() == []


@pytest.mark.asyncio
async def test_scanner_skips_unlocked_content() -> None:
    scanner, _, _ = make_scanner(FakeFeishu(chapters=[chapter("c1", locked="否/No")]))
    assert await scanner.run_once() == []


@pytest.mark.asyncio
async def test_scanner_skips_empty_version() -> None:
    scanner, _, _ = make_scanner(FakeFeishu(chapters=[chapter("c1", current_version="")]))
    assert await scanner.run_once() == []


@pytest.mark.asyncio
async def test_scanner_skips_unhealthy_account() -> None:
    feishu = FakeFeishu(
        chapters=[chapter("c1")],
        accounts=[{"record_id": "acc-1", "fields": {"账号ID": "acc-1", "账号状态": "观察/Observing"}}],
    )
    scanner, _, device = make_scanner(feishu)
    assert await scanner.run_once() == []
    assert device.calls == []


@pytest.mark.asyncio
async def test_scanner_sets_account_unhealthy_after_max_failures() -> None:
    feishu = FakeFeishu(chapters=[chapter("c1", attempts=2)])
    scanner, _, _ = make_scanner(feishu, FakeDevice(fail=True))
    await scanner.run_once()
    assert feishu.updated == [("账号管理表", "acc-1", {"账号状态": "观察/Observing"})]


def test_scanner_parse_datetime_handles_datetime_object() -> None:
    scanner, _, _ = make_scanner(FakeFeishu())
    now = datetime.now()
    assert scanner._parse_datetime(now) == now
