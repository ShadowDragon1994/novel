from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.feishu_client import FeishuClient
from core.logger import LOG_FILE, configure_logging, get_logger, write_feishu_log

configure_logging()
logger = get_logger(__name__)


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


class Healthcheck:
    def __init__(self, feishu_client: FeishuClient) -> None:
        self.feishu_client = feishu_client

    async def run(self) -> list[CheckResult]:
        results = [
            await self.check_feishu_connectivity(),
            await self.check_table_mapping(),
            await self.check_write_permission(),
            await self.check_log_dual_write(),
        ]
        return results

    async def check_feishu_connectivity(self) -> CheckResult:
        try:
            token = await self.feishu_client.tenant_access_token()
            return CheckResult("飞书连通", bool(token), "tenant_access_token acquired")
        except Exception as exc:
            return CheckResult("飞书连通", False, str(exc))

    async def check_table_mapping(self) -> CheckResult:
        try:
            expected = self.feishu_client.all_table_ids()
            if len(expected) != 16:
                return CheckResult("16 表 ID 映射正确", False, f"expected 16 local tables, got {len(expected)}")
            remote_tables = await self.feishu_client.list_tables()
            remote_ids = {table.get("table_id") for table in remote_tables}
            missing = sorted(set(expected.values()) - remote_ids)
            if missing:
                return CheckResult("16 表 ID 映射正确", False, f"missing remote table ids: {', '.join(missing)}")
            missing_fields = []
            for table_name, table_id in expected.items():
                local_fields = set(self.feishu_client.resolve_table(table_name).fields)
                local_field_entries = self.feishu_client.resolve_table(table_name).fields
                remote_fields = await self.feishu_client.list_fields(table_name)
                remote_field_names = {
                    field.get("field_name") or field.get("name")
                    for field in remote_fields
                }
                remote_field_ids = {field.get("field_id") for field in remote_fields}
                table_missing_fields = []
                for field_name in local_fields:
                    field_entry = local_field_entries[field_name]
                    field_id = field_entry.get("field_id") if isinstance(field_entry, dict) else None
                    remote_field_name = field_entry.get("remote_field_name") if isinstance(field_entry, dict) else None
                    field_exists = (
                        field_name in remote_field_names
                        or remote_field_name in remote_field_names
                        or field_id in remote_field_ids
                    )
                    if field_exists:
                        continue
                    table_missing_fields.append(field_name)
                table_missing_fields = sorted(table_missing_fields)
                if table_missing_fields:
                    missing_fields.append(f"{table_name}({table_id}): {', '.join(table_missing_fields)}")
            if missing_fields:
                return CheckResult("16 表 ID 映射正确", False, "; ".join(missing_fields))
            return CheckResult("16 表 ID 映射正确", True, "all local table IDs found in Feishu")
        except Exception as exc:
            return CheckResult("16 表 ID 映射正确", False, str(exc))

    async def check_write_permission(self) -> CheckResult:
        record_id = ""
        try:
            record = await self.feishu_client.create_record(
                "运行日志表",
                {
                    "日志ID": "healthcheck-write-permission",
                    "节点名称": "write_permission",
                    "执行状态": "成功/Success",
                    "错误信息": "",
                    "输入摘要": "healthcheck",
                    "输出摘要": "healthcheck write permission probe",
                    "重试次数": 0,
                },
            )
            record_id = record.get("record_id", "")
            if record_id:
                await self.feishu_client.delete_record("运行日志表", record_id)
            return CheckResult("写权限正常", True, "create/delete probe succeeded")
        except Exception as exc:
            if record_id:
                try:
                    await self.feishu_client.delete_record("运行日志表", record_id)
                except Exception:
                    pass
            return CheckResult("写权限正常", False, str(exc))

    async def check_log_dual_write(self) -> CheckResult:
        try:
            logger.info("healthcheck local log probe")
            await write_feishu_log(
                self.feishu_client,
                level="INFO",
                module="healthcheck",
                message="healthcheck feishu log probe",
                node="log_dual_write",
                status="成功/Success",
            )
            if not LOG_FILE.exists():
                return CheckResult("日志双写", False, f"local log file missing: {LOG_FILE}")
            return CheckResult("日志双写", True, "local log and Feishu log write succeeded")
        except Exception as exc:
            return CheckResult("日志双写", False, str(exc))


def print_results(results: list[CheckResult]) -> None:
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.name}: {result.detail}")


async def async_main() -> int:
    async with FeishuClient() as feishu_client:
        results = await Healthcheck(feishu_client).run()
    print_results(results)
    return 0 if all(result.passed for result in results) else 1


def main() -> None:
    exit_code = asyncio.run(async_main())
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
