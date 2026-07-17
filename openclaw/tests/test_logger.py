import pytest

from core.logger import FeishuLogSink, write_feishu_log


class FakeFeishuClient:
    def __init__(self) -> None:
        self.created = []

    async def create_record(self, table_name, fields):
        self.created.append((table_name, fields))
        return {"record_id": "rec-log", "fields": fields}


@pytest.mark.asyncio
async def test_write_feishu_log_creates_running_log_record() -> None:
    client = FakeFeishuClient()
    record = await write_feishu_log(client, level="INFO", module="unit-test", message="hello", node="logger")
    assert record["record_id"] == "rec-log"
    assert client.created[0][0] == "运行日志表"
    assert client.created[0][1]["节点名称"] == "logger"
    assert client.created[0][1]["输出摘要"] == "hello"


def test_feishu_log_sink_does_not_raise_without_event_loop() -> None:
    sink = FeishuLogSink(FakeFeishuClient())

    class Message:
        record = {
            "extra": {},
            "time": __import__("datetime").datetime.now(),
            "name": "test",
            "level": type("Level", (), {"name": "INFO"})(),
            "function": "unit",
            "message": "hello",
            "exception": None,
        }

    sink(Message())
