from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from core.config import load_settings
from core.rate_limiter import RateLimiter
from core.read_cache import ReadCache


class FeishuConfigError(RuntimeError):
    pass


class FeishuAPIError(RuntimeError):
    def __init__(self, code: int, message: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(f"Feishu API error {code}: {message}")
        self.code = code
        self.payload = payload or {}


def is_retryable_feishu_error(exception: BaseException) -> bool:
    if isinstance(exception, httpx.RequestError):
        return True
    if isinstance(exception, httpx.HTTPStatusError):
        status_code = exception.response.status_code
        return status_code == 429 or status_code >= 500
    if isinstance(exception, FeishuAPIError):
        if exception.code in {401, 403, 91403, 99991672}:
            return False
        return exception.code == 429 or exception.code >= 500 or exception.code == 999
    return False


@dataclass(frozen=True)
class FeishuTable:
    name: str
    table_id: str
    fields: dict[str, Any]


class FeishuClient:
    def __init__(
        self,
        read_limiter: RateLimiter | None = None,
        write_limiter: RateLimiter | None = None,
        *,
        app_id: str | None = None,
        app_secret: str | None = None,
        app_token: str | None = None,
        base_url: str = "https://open.feishu.cn",
        http_client: httpx.AsyncClient | None = None,
        read_cache: ReadCache | None = None,
    ) -> None:
        settings = load_settings()
        rate_limit = settings.raw.get("rate_limit", {})
        read_capacity = rate_limit.get("feishu_read_bucket_capacity", rate_limit.get("feishu_bucket_capacity", 10))
        write_capacity = rate_limit.get("feishu_write_bucket_capacity", rate_limit.get("feishu_bucket_capacity", 5))
        self.read_limiter = read_limiter or RateLimiter(rate_limit.get("feishu_read_qps", 3), read_capacity)
        self.write_limiter = write_limiter or RateLimiter(rate_limit.get("feishu_write_qps", 2), write_capacity)
        self.app_id = app_id or os.getenv("FEISHU_APP_ID", "")
        self.app_secret = app_secret or os.getenv("FEISHU_APP_SECRET", "")
        self.app_token = app_token or os.getenv("FEISHU_APP_TOKEN", "")
        self.base_url = base_url.rstrip("/")
        self.field_mapping = settings.field_mapping
        self._client = http_client or httpx.AsyncClient(base_url=self.base_url, timeout=20)
        self._owns_client = http_client is None
        self._tenant_access_token: str | None = None
        self._token_expires_at: datetime | None = None
        self._token_lock = asyncio.Lock()
        self.read_cache = read_cache

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> FeishuClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def tenant_access_token(self) -> str:
        if self._is_token_valid():
            return self._tenant_access_token or ""
        async with self._token_lock:
            if self._is_token_valid():
                return self._tenant_access_token or ""
            if not self.app_id or not self.app_secret:
                raise FeishuConfigError("FEISHU_APP_ID and FEISHU_APP_SECRET are required")
            payload = {"app_id": self.app_id, "app_secret": self.app_secret}
            response = await self._request_json(
                "POST",
                "/open-apis/auth/v3/tenant_access_token/internal",
                json=payload,
                auth=False,
            )
            token = response.get("tenant_access_token")
            if not token:
                raise FeishuAPIError(response.get("code", -1), "missing tenant_access_token", response)
            expire_seconds = int(response.get("expire", 7200))
            self._tenant_access_token = token
            self._token_expires_at = datetime.now() + timedelta(seconds=max(expire_seconds - 300, 60))
            return token

    async def list_records(self, table_name: str, **params: Any) -> list[dict[str, Any]]:
        cache_key = self._list_cache_key(table_name, params)
        if self.read_cache:
            cached = self.read_cache.get(cache_key)
            if cached is not None:
                return cached
        await self.read_limiter.acquire()
        table = self.resolve_table(table_name)
        records: list[dict[str, Any]] = []
        query_params = dict(params)
        page_token = query_params.pop("page_token", None)
        while True:
            query = {"page_size": query_params.pop("page_size", 500), **query_params}
            if page_token:
                query["page_token"] = page_token
            response = await self._request_json("GET", self._records_path(table), params=query)
            data = response.get("data", {})
            records.extend(data.get("items") or [])
            if not data.get("has_more"):
                if self.read_cache:
                    self.read_cache.set(cache_key, records)
                return records
            page_token = data.get("page_token")

    async def list_tables(self) -> list[dict[str, Any]]:
        await self.read_limiter.acquire()
        if not self.app_token:
            raise FeishuConfigError("FEISHU_APP_TOKEN is required for Bitable table APIs")
        tables: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            response = await self._request_json(
                "GET",
                f"/open-apis/bitable/v1/apps/{self.app_token}/tables",
                params=params,
            )
            data = response.get("data", {})
            tables.extend(data.get("items") or [])
            if not data.get("has_more"):
                return tables
            page_token = data.get("page_token")

    async def list_fields(self, table_name: str) -> list[dict[str, Any]]:
        await self.read_limiter.acquire()
        table = self.resolve_table(table_name)
        if not self.app_token:
            raise FeishuConfigError("FEISHU_APP_TOKEN is required for Bitable field APIs")
        fields: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            response = await self._request_json(
                "GET",
                f"/open-apis/bitable/v1/apps/{self.app_token}/tables/{table.table_id}/fields",
                params=params,
            )
            data = response.get("data", {})
            fields.extend(data.get("items") or [])
            if not data.get("has_more"):
                return fields
            page_token = data.get("page_token")

    async def get_record(self, table_name: str, record_id: str) -> dict[str, Any]:
        cache_key = self._record_cache_key(table_name, record_id)
        if self.read_cache:
            cached = self.read_cache.get(cache_key)
            if cached is not None:
                return cached
        await self.read_limiter.acquire()
        table = self.resolve_table(table_name)
        response = await self._request_json("GET", f"{self._records_path(table)}/{record_id}")
        record = response.get("data", {}).get("record", {})
        if self.read_cache:
            self.read_cache.set(cache_key, record)
        return record

    async def create_record(self, table_name: str, fields: dict[str, Any]) -> dict[str, Any]:
        await self.write_limiter.acquire()
        table = self.resolve_table(table_name)
        response = await self._request_json("POST", self._records_path(table), json={"fields": fields})
        self._invalidate_table_cache(table_name)
        return response.get("data", {}).get("record", {})

    async def update_record(self, table_name: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        await self.write_limiter.acquire()
        table = self.resolve_table(table_name)
        response = await self._request_json("PUT", f"{self._records_path(table)}/{record_id}", json={"fields": fields})
        self._invalidate_record_cache(table_name, record_id)
        return response.get("data", {}).get("record", {})

    async def delete_record(self, table_name: str, record_id: str) -> bool:
        await self.write_limiter.acquire()
        table = self.resolve_table(table_name)
        await self._request_json("DELETE", f"{self._records_path(table)}/{record_id}")
        self._invalidate_record_cache(table_name, record_id)
        return True

    def resolve_table(self, table_name: str) -> FeishuTable:
        table = self.field_mapping.get(table_name)
        if not table:
            raise FeishuConfigError(f"Unknown Feishu table: {table_name}")
        table_id = table.get("table_id")
        if not table_id:
            raise FeishuConfigError(f"Missing table_id for Feishu table: {table_name}")
        return FeishuTable(name=table_name, table_id=table_id, fields=table.get("fields", {}))

    def all_table_ids(self) -> dict[str, str]:
        return {name: table["table_id"] for name, table in self.field_mapping.items() if table.get("table_id")}

    def _records_path(self, table: FeishuTable) -> str:
        if not self.app_token:
            raise FeishuConfigError("FEISHU_APP_TOKEN is required for Bitable record APIs")
        return f"/open-apis/bitable/v1/apps/{self.app_token}/tables/{table.table_id}/records"

    def _is_token_valid(self) -> bool:
        return bool(self._tenant_access_token and self._token_expires_at and datetime.now() < self._token_expires_at)

    def _list_cache_key(self, table_name: str, params: dict[str, Any]) -> str:
        encoded = json.dumps(params, ensure_ascii=False, sort_keys=True, default=str)
        return f"feishu:list:{table_name}:{encoded}"

    def _record_cache_key(self, table_name: str, record_id: str) -> str:
        return f"feishu:record:{table_name}:{record_id}"

    def _invalidate_table_cache(self, table_name: str) -> None:
        if not self.read_cache:
            return
        self.read_cache.invalidate_prefix(f"feishu:list:{table_name}:")

    def _invalidate_record_cache(self, table_name: str, record_id: str) -> None:
        if not self.read_cache:
            return
        self.read_cache.invalidate(self._record_cache_key(table_name, record_id))
        self._invalidate_table_cache(table_name)

    @retry(
        retry=retry_if_exception(is_retryable_feishu_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.2, min=0.2, max=2),
        reraise=True,
    )
    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        headers = kwargs.pop("headers", {})
        if auth:
            headers["Authorization"] = f"Bearer {await self.tenant_access_token()}"
        response = await self._client.request(method, path, headers=headers, **kwargs)
        try:
            payload = response.json()
        except ValueError:
            response.raise_for_status()
            raise
        if response.is_error:
            code = int(payload.get("code", response.status_code))
            message = payload.get("msg") or payload.get("message") or response.reason_phrase
            raise FeishuAPIError(code, message, payload)
        code = int(payload.get("code", 0))
        if code != 0:
            raise FeishuAPIError(code, payload.get("msg") or payload.get("message") or "unknown error", payload)
        return payload
