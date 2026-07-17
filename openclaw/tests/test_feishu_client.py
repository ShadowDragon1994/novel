import httpx
import pytest

from core.config import load_settings
from core.feishu_client import FeishuClient
from core.rate_limiter import RateLimiter
from core.read_cache import ReadCache

TABLE_CASES = [
    (table_name, table["table_id"])
    for table_name, table in load_settings().field_mapping.items()
]


def make_client(handler):
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(base_url="https://open.feishu.cn", transport=transport)
    return FeishuClient(
        RateLimiter(1000, 1000),
        RateLimiter(1000, 1000),
        app_id="app-id",
        app_secret="app-secret",
        app_token="app-token",
        http_client=http_client,
    )


def make_cached_client(handler, tmp_path):
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(base_url="https://open.feishu.cn", transport=transport)
    return FeishuClient(
        RateLimiter(1000, 1000),
        RateLimiter(1000, 1000),
        app_id="app-id",
        app_secret="app-secret",
        app_token="app-token",
        http_client=http_client,
        read_cache=ReadCache(tmp_path / "openclaw.sqlite", ttl_seconds=60),
    )


@pytest.mark.asyncio
async def test_tenant_access_token_is_reused() -> None:
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.path.endswith("/tenant_access_token/internal"):
            token_calls += 1
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token-1", "expire": 7200})
        raise AssertionError(request.url.path)

    client = make_client(handler)
    try:
        assert await client.tenant_access_token() == "token-1"
        assert await client.tenant_access_token() == "token-1"
        assert token_calls == 1
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("table_name,table_id", TABLE_CASES)
async def test_records_crud_methods_for_each_table(table_name: str, table_id: str) -> None:
    seen = []
    expected_records_path = f"/open-apis/bitable/v1/apps/app-token/tables/{table_id}/records"

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token-1", "expire": 7200})
        if request.method == "GET" and request.url.path == expected_records_path:
            return httpx.Response(200, json={"code": 0, "data": {"items": [{"record_id": "rec-1"}], "has_more": False}})
        if request.method == "GET" and request.url.path == f"{expected_records_path}/rec-1":
            return httpx.Response(200, json={"code": 0, "data": {"record": {"record_id": "rec-1"}}})
        if request.method == "POST" and request.url.path == expected_records_path:
            return httpx.Response(200, json={"code": 0, "data": {"record": {"record_id": "rec-2"}}})
        if request.method == "PUT" and request.url.path == f"{expected_records_path}/rec-2":
            return httpx.Response(200, json={"code": 0, "data": {"record": {"record_id": "rec-2"}}})
        if request.method == "DELETE" and request.url.path == f"{expected_records_path}/rec-2":
            return httpx.Response(200, json={"code": 0})
        raise AssertionError(f"unexpected request {request.method} {request.url.path}")

    client = make_client(handler)
    try:
        assert await client.list_records(table_name) == [{"record_id": "rec-1"}]
        assert await client.get_record(table_name, "rec-1") == {"record_id": "rec-1"}
        assert await client.create_record(table_name, {"测试字段": "create"}) == {"record_id": "rec-2"}
        assert await client.update_record(table_name, "rec-2", {"测试字段": "update"}) == {"record_id": "rec-2"}
        assert await client.delete_record(table_name, "rec-2")
        assert ("GET", expected_records_path) in seen
        assert ("POST", expected_records_path) in seen
        assert ("PUT", f"{expected_records_path}/rec-2") in seen
        assert ("DELETE", f"{expected_records_path}/rec-2") in seen
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_request_retries_three_times() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token-1", "expire": 7200})
        if calls < 4:
            return httpx.Response(200, json={"code": 999, "msg": "temporary"})
        return httpx.Response(200, json={"code": 0, "data": {"items": [], "has_more": False}})

    client = make_client(handler)
    try:
        await client.list_records("章节任务表")
        assert calls == 4
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_forbidden_error_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token-1", "expire": 7200})
        return httpx.Response(403, json={"code": 91403, "msg": "Forbidden"})

    client = make_client(handler)
    try:
        with pytest.raises(Exception, match="91403"):
            await client.list_records("章节任务表")
        assert calls == 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_rate_limit_error_is_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token-1", "expire": 7200})
        if calls < 4:
            return httpx.Response(429, json={"code": 429, "msg": "rate limited"})
        return httpx.Response(200, json={"code": 0, "data": {"items": [], "has_more": False}})

    client = make_client(handler)
    try:
        await client.list_records("章节任务表")
        assert calls == 4
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_list_fields_uses_table_mapping() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token-1", "expire": 7200})
        if request.method == "GET" and request.url.path.endswith("/tables/tblQ0lBtkFeVEYId/fields"):
            return httpx.Response(
                200,
                json={"code": 0, "data": {"items": [{"field_name": "章节ID"}], "has_more": False}},
            )
        raise AssertionError(f"unexpected request {request.method} {request.url.path}")

    client = make_client(handler)
    try:
        assert await client.list_fields("章节任务表") == [{"field_name": "章节ID"}]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_list_records_uses_cache_on_second_call(tmp_path) -> None:
    record_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal record_calls
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token-1", "expire": 7200})
        if request.method == "GET" and request.url.path.endswith("/records"):
            record_calls += 1
            return httpx.Response(200, json={"code": 0, "data": {"items": [{"record_id": "rec-1"}], "has_more": False}})
        raise AssertionError(request.url.path)

    client = make_cached_client(handler, tmp_path)
    try:
        assert await client.list_records("章节任务表") == [{"record_id": "rec-1"}]
        assert await client.list_records("章节任务表") == [{"record_id": "rec-1"}]
        assert record_calls == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_get_record_uses_cache_on_second_call(tmp_path) -> None:
    record_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal record_calls
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token-1", "expire": 7200})
        if request.method == "GET" and request.url.path.endswith("/records/rec-1"):
            record_calls += 1
            return httpx.Response(200, json={"code": 0, "data": {"record": {"record_id": "rec-1"}}})
        raise AssertionError(request.url.path)

    client = make_cached_client(handler, tmp_path)
    try:
        assert await client.get_record("章节任务表", "rec-1") == {"record_id": "rec-1"}
        assert await client.get_record("章节任务表", "rec-1") == {"record_id": "rec-1"}
        assert record_calls == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_create_record_invalidates_list_cache(tmp_path) -> None:
    list_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal list_calls
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token-1", "expire": 7200})
        if request.method == "GET" and request.url.path.endswith("/records"):
            list_calls += 1
            return httpx.Response(
                200,
                json={"code": 0, "data": {"items": [{"record_id": f"rec-{list_calls}"}], "has_more": False}},
            )
        if request.method == "POST" and request.url.path.endswith("/records"):
            return httpx.Response(200, json={"code": 0, "data": {"record": {"record_id": "rec-new"}}})
        raise AssertionError(f"{request.method} {request.url.path}")

    client = make_cached_client(handler, tmp_path)
    try:
        assert await client.list_records("章节任务表") == [{"record_id": "rec-1"}]
        await client.create_record("章节任务表", {"章节ID": "c1"})
        assert await client.list_records("章节任务表") == [{"record_id": "rec-2"}]
        assert list_calls == 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_update_record_invalidates_record_cache(tmp_path) -> None:
    get_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_calls
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token-1", "expire": 7200})
        if request.method == "GET" and request.url.path.endswith("/records/rec-1"):
            get_calls += 1
            return httpx.Response(
                200,
                json={"code": 0, "data": {"record": {"record_id": "rec-1", "version": get_calls}}},
            )
        if request.method == "PUT" and request.url.path.endswith("/records/rec-1"):
            return httpx.Response(200, json={"code": 0, "data": {"record": {"record_id": "rec-1"}}})
        raise AssertionError(f"{request.method} {request.url.path}")

    client = make_cached_client(handler, tmp_path)
    try:
        assert (await client.get_record("章节任务表", "rec-1"))["version"] == 1
        await client.update_record("章节任务表", "rec-1", {"章节名": "x"})
        assert (await client.get_record("章节任务表", "rec-1"))["version"] == 2
        assert get_calls == 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_delete_record_invalidates_record_cache(tmp_path) -> None:
    get_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_calls
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token-1", "expire": 7200})
        if request.method == "GET" and request.url.path.endswith("/records/rec-1"):
            get_calls += 1
            return httpx.Response(
                200,
                json={"code": 0, "data": {"record": {"record_id": "rec-1", "version": get_calls}}},
            )
        if request.method == "DELETE" and request.url.path.endswith("/records/rec-1"):
            return httpx.Response(200, json={"code": 0})
        raise AssertionError(f"{request.method} {request.url.path}")

    client = make_cached_client(handler, tmp_path)
    try:
        await client.get_record("章节任务表", "rec-1")
        await client.delete_record("章节任务表", "rec-1")
        assert (await client.get_record("章节任务表", "rec-1"))["version"] == 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_list_records_treats_null_items_as_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token-1", "expire": 7200})
        if request.method == "GET" and request.url.path.endswith("/records"):
            return httpx.Response(200, json={"code": 0, "data": {"items": None, "has_more": False}})
        raise AssertionError(request.url.path)

    client = make_client(handler)
    try:
        assert await client.list_records("小说总览表") == []
    finally:
        await client.close()
