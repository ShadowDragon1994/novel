from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from core.feishu_client import FeishuClient

ACCOUNT_FIELDS: dict[str, dict[str, Any]] = {
    "绑定小说ID": {"type": 1},
    "红手指设备ID": {"type": 1},
    "账号健康状态": {
        "type": 3,
        "property": {"options": [{"name": name} for name in ("正常", "观察", "暂停", "异常")]},
    },
    "账号阶段": {
        "type": 3,
        "property": {"options": [{"name": name} for name in ("养号期", "过渡期", "稳定期")]},
    },
}


async def sync_account_fields(*, dry_run: bool = False) -> dict[str, list[str]]:
    async with FeishuClient() as client:
        existing = {field["field_name"] for field in await client.list_fields("账号管理表")}
        created: list[str] = []
        skipped: list[str] = []
        table = client.resolve_table("账号管理表")
        for name, definition in ACCOUNT_FIELDS.items():
            if name in existing:
                skipped.append(name)
                continue
            if not dry_run:
                await client.create_field(table, {"field_name": name, **definition})
            created.append(name)
        return {"created": created, "skipped": skipped}


async def async_main() -> None:
    parser = argparse.ArgumentParser(description="Create missing OpenClaw account fields in Feishu Bitable")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--show", action="store_true", help="print the synchronized field metadata")
    args = parser.parse_args()
    print(await sync_account_fields(dry_run=args.dry_run))
    if args.show:
        async with FeishuClient() as client:
            fields = await client.list_fields("账号管理表")
            selected = [field for field in fields if field.get("field_name") in ACCOUNT_FIELDS]
            print(json.dumps(selected, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(async_main())
