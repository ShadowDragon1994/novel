import pytest

from business.watchdog import Watchdog
from core.circuit_breaker import CircuitBreaker


class FakeFeishu:
    def __init__(self, chapters=None, fail_token: bool = False) -> None:
        self.chapters = chapters or []
        self.fail_token = fail_token
        self.created = []

    async def list_records(self, table_name):
        if table_name == "章节任务表":
            return self.chapters
        return []

    async def tenant_access_token(self):
        if self.fail_token:
            raise RuntimeError("token down")
        return "token"

    async def create_record(self, table_name, fields):
        self.created.append((table_name, fields))
        return {"record_id": "log", "fields": fields}


def chapter(chapter_id="c1", status="待发布/Pending Publish", error="", retries=0):
    return {"fields": {"章节ID": chapter_id, "生产状态": status, "错误信息": error, "流程重试次数": retries}}


@pytest.mark.asyncio
async def test_watchdog_detects_low_inventory() -> None:
    feishu = FakeFeishu(chapters=[chapter("c1"), chapter("c2"), chapter("c3"), chapter("c4")])
    report = await Watchdog(feishu).run_once()
    assert any(alert.category == "inventory" and alert.severity == "警告/Warning" for alert in report.alerts)


@pytest.mark.asyncio
async def test_watchdog_detects_critical_inventory() -> None:
    report = await Watchdog(FakeFeishu(chapters=[chapter("c1")])).run_once()
    assert any(alert.severity == "严重告警/Critical" for alert in report.alerts)


@pytest.mark.asyncio
async def test_watchdog_detects_failed_chapters() -> None:
    report = await Watchdog(FakeFeishu(chapters=[chapter("c1", error="boom")])).run_once()
    assert any(alert.category == "failures" for alert in report.alerts)


@pytest.mark.asyncio
async def test_watchdog_detects_retry_failures() -> None:
    report = await Watchdog(FakeFeishu(chapters=[chapter("c1", retries=3)])).run_once()
    assert any("c1" in alert.message for alert in report.alerts)


@pytest.mark.asyncio
async def test_watchdog_detects_circuit_open() -> None:
    breaker = CircuitBreaker(failure_threshold=1)
    breaker.record_failure()
    client = type("Client", (), {"circuit_breaker": breaker})()
    report = await Watchdog(
        FakeFeishu(chapters=[chapter(str(index)) for index in range(6)]),
        {"qwen": client},
    ).run_once()
    assert any(alert.category == "circuit" for alert in report.alerts)


@pytest.mark.asyncio
async def test_watchdog_detects_feishu_connectivity_loss() -> None:
    report = await Watchdog(
        FakeFeishu(chapters=[chapter(str(index)) for index in range(6)], fail_token=True)
    ).run_once()
    assert any(alert.category == "feishu" and alert.severity == "严重告警/Critical" for alert in report.alerts)


@pytest.mark.asyncio
async def test_watchdog_writes_report_to_log_table() -> None:
    feishu = FakeFeishu(chapters=[chapter("c1")])
    await Watchdog(feishu).run_once()
    assert feishu.created
    assert feishu.created[0][0] == "运行日志表"


@pytest.mark.asyncio
async def test_watchdog_healthy_when_all_ok() -> None:
    feishu = FakeFeishu(chapters=[chapter(str(index)) for index in range(6)])
    report = await Watchdog(feishu).run_once()
    assert report.healthy
    assert feishu.created[0][1]["执行状态"] == "成功/Success"


@pytest.mark.asyncio
async def test_watchdog_reports_critical_over_warning() -> None:
    report = await Watchdog(FakeFeishu(chapters=[], fail_token=True)).run_once()
    severities = {alert.severity for alert in report.alerts}
    assert "严重告警/Critical" in severities


@pytest.mark.asyncio
async def test_watchdog_tracks_multiple_circuit_breakers() -> None:
    clients = {}
    for name in ["deepseek", "qwen"]:
        breaker = CircuitBreaker(failure_threshold=1)
        breaker.record_failure()
        clients[name] = type("Client", (), {"circuit_breaker": breaker})()
    report = await Watchdog(FakeFeishu(chapters=[chapter(str(index)) for index in range(6)]), clients).run_once()
    assert sum(1 for alert in report.alerts if alert.category == "circuit") == 2


@pytest.mark.asyncio
async def test_watchdog_handles_missing_clients() -> None:
    report = await Watchdog(FakeFeishu(chapters=[chapter(str(index)) for index in range(6)])).run_once()
    assert report.healthy


@pytest.mark.asyncio
async def test_watchdog_pauses_novel_with_critical_inventory() -> None:
    class AdvancedFeishu(FakeFeishu):
        def __init__(self):
            super().__init__(
                chapters=[{"fields": {"章节ID": "c1", "小说ID": "n1", "生产状态": "待发布/Pending Publish"}}]
            )
            self.updated = []

        async def list_records(self, table_name):
            if table_name == "章节任务表":
                return self.chapters
            if table_name == "小说总览表":
                return [{"record_id": "novel-1", "fields": {"小说ID": "n1", "自动发布开关": True}}]
            return []

        async def update_record(self, table_name, record_id, fields):
            self.updated.append((table_name, record_id, fields))
            return {"record_id": record_id, "fields": fields}

    feishu = AdvancedFeishu()
    await Watchdog(feishu).run_once()
    assert feishu.updated == [
        ("小说总览表", "novel-1", {"自动发布开关": False, "发布暂停原因": "存稿不足"})
    ]


@pytest.mark.asyncio
async def test_watchdog_counts_finalized_pending_publish_as_inventory() -> None:
    chapters = [
        {
            "fields": {
                "章节ID": f"c{index}",
                "小说ID": "n1",
                "生产状态": "已定稿/Finalized",
                "发布状态": "待发布/Pending Publish",
            }
        }
        for index in range(6)
    ]

    report = await Watchdog(FakeFeishu(chapters=chapters)).run_once()

    assert not any(alert.category == "inventory" for alert in report.alerts)


@pytest.mark.asyncio
async def test_watchdog_resumes_only_inventory_paused_novel_after_stock_recovers() -> None:
    class RecoveringFeishu(FakeFeishu):
        def __init__(self):
            super().__init__(
                chapters=[
                    {
                        "fields": {
                            "章节ID": f"c{index}",
                            "小说ID": "n1",
                            "生产状态": "已定稿/Finalized",
                            "发布状态": "待发布/Pending Publish",
                        }
                    }
                    for index in range(3)
                ]
            )
            self.updated = []

        async def list_records(self, table_name):
            if table_name == "章节任务表":
                return self.chapters
            if table_name == "小说总览表":
                return [
                    {
                        "record_id": "novel-1",
                        "fields": {
                            "小说ID": "n1",
                            "自动发布开关": False,
                            "发布暂停原因": "存稿不足",
                        },
                    },
                    {
                        "record_id": "novel-2",
                        "fields": {
                            "小说ID": "n2",
                            "自动发布开关": False,
                            "发布暂停原因": "人工暂停",
                        },
                    },
                ]
            return []

        async def update_record(self, table_name, record_id, fields):
            self.updated.append((table_name, record_id, fields))
            return {"record_id": record_id, "fields": fields}

    feishu = RecoveringFeishu()
    await Watchdog(feishu).run_once()

    assert feishu.updated == [
        ("小说总览表", "novel-1", {"自动发布开关": True, "发布暂停原因": ""})
    ]


@pytest.mark.asyncio
async def test_watchdog_alerts_when_confirmation_queue_exceeds_threshold() -> None:
    class ConfirmationFeishu(FakeFeishu):
        async def list_records(self, table_name):
            if table_name == "章节任务表":
                return [chapter(str(index)) for index in range(6)]
            if table_name == "人物档案表":
                return [{"fields": {"确认状态": "待确认/Pending"}} for _ in range(21)]
            return []

    report = await Watchdog(ConfirmationFeishu()).run_once()
    assert any(alert.category == "confirm_queue" for alert in report.alerts)
