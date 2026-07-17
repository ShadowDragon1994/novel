import pytest

from scripts.healthcheck import Healthcheck


class FakeFeishuClient:
    def __init__(self) -> None:
        self.deleted = []
        self.created = []

    async def tenant_access_token(self):
        return "token"

    def all_table_ids(self):
        return {f"表{i}": f"tbl{i}" for i in range(16)}

    def resolve_table(self, table_name):
        return type("Table", (), {"fields": {"字段A": {}}})()

    async def list_tables(self):
        return [{"table_id": f"tbl{i}"} for i in range(16)]

    async def list_fields(self, table_name):
        return [{"field_name": "字段A"}]

    async def create_record(self, table_name, fields):
        self.created.append((table_name, fields))
        return {"record_id": "rec-1", "fields": fields}

    async def delete_record(self, table_name, record_id):
        self.deleted.append((table_name, record_id))
        return True


@pytest.mark.asyncio
async def test_healthcheck_all_checks_pass() -> None:
    client = FakeFeishuClient()
    results = await Healthcheck(client).run()
    assert all(result.passed for result in results)
    assert any(fields["节点名称"] == "write_permission" for _, fields in client.created)
    assert any(fields["节点名称"] == "log_dual_write" for _, fields in client.created)
    assert client.deleted == [("运行日志表", "rec-1")]
