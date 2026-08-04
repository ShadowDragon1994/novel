from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.circuit_breaker import CircuitState
from core.config import load_settings
from core.feishu_client import FeishuClient

INVENTORY_STATUSES = {"待人工审核", "待人工审核/Pending Review", "待发布", "待发布/Pending Publish"}
PENDING_PUBLISH_STATUSES = {"待发布", "待发布/Pending Publish"}
INVENTORY_PAUSE_REASON = "存稿不足"
CONFIRMATION_TABLES = {"人物档案表", "世界观设定表", "势力组织表", "伏笔追踪表", "长期记忆表"}
PENDING_CONFIRMATION = {"待确认", "待确认/Pending"}


@dataclass(frozen=True)
class WatchdogAlert:
    category: str
    severity: str
    message: str


@dataclass
class WatchdogReport:
    alerts: list[WatchdogAlert] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not self.alerts

    def warn(self, category: str, message: str) -> None:
        self.alerts.append(WatchdogAlert(category, "警告/Warning", message))

    def critical(self, category: str, message: str) -> None:
        self.alerts.append(WatchdogAlert(category, "严重告警/Critical", message))


class Watchdog:
    def __init__(self, feishu_client: FeishuClient | None = None, clients: dict[str, Any] | None = None) -> None:
        self.feishu_client = feishu_client or FeishuClient()
        self.clients = clients or {}
        inventory = load_settings().raw.get("inventory", {})
        self.safety_threshold = int(inventory.get("safety_threshold", 6))
        self.pause_threshold = int(inventory.get("pause_threshold", 3))
        self.confirm_threshold = int(load_settings().raw.get("confirm_queue", {}).get("alert_threshold", 20))

    async def run_once(self) -> WatchdogReport:
        report = WatchdogReport()
        chapters = await self.feishu_client.list_records("章节任务表")
        self._check_inventory(report, chapters)
        await self._pause_low_inventory_novels(chapters)
        self._check_failed_chapters(report, chapters)
        self._check_circuits(report)
        await self._check_confirmation_queue(report)
        await self._check_feishu(report)
        await self._write_report(report)
        return report

    def _check_inventory(self, report: WatchdogReport, chapters: list[dict[str, Any]]) -> None:
        count = sum(1 for record in chapters if self._is_inventory_chapter(record.get("fields", record)))
        if count < self.pause_threshold:
            report.critical("inventory", f"存稿仅剩 {count} 章")
        elif count < self.safety_threshold:
            report.warn("inventory", f"存稿不足 {count} 章")

    def _check_failed_chapters(self, report: WatchdogReport, chapters: list[dict[str, Any]]) -> None:
        failed = []
        for record in chapters:
            fields = record.get("fields", record)
            if fields.get("错误信息") or int(fields.get("流程重试次数") or 0) >= 3:
                failed.append(str(fields.get("章节ID") or record.get("record_id") or "unknown"))
        if failed:
            report.warn("failures", f"{len(failed)} 章有错误：{', '.join(failed)}")

    async def _pause_low_inventory_novels(self, chapters: list[dict[str, Any]]) -> None:
        inventory_by_novel: dict[str, int] = {}
        for record in chapters:
            fields = record.get("fields", record)
            novel_id = str(fields.get("小说ID") or "")
            if novel_id and self._is_inventory_chapter(fields):
                inventory_by_novel[novel_id] = inventory_by_novel.get(novel_id, 0) + 1
        novels = await self.feishu_client.list_records("小说总览表")
        for record in novels:
            fields = record.get("fields", record)
            novel_id = str(fields.get("小说ID") or "")
            if not novel_id:
                continue
            available = inventory_by_novel.get(novel_id, 0)
            switch_enabled = fields.get("自动发布开关") is True
            pause_reason = str(fields.get("发布暂停原因") or "")
            if available < self.pause_threshold and switch_enabled:
                await self.feishu_client.update_record(
                    "小说总览表",
                    str(record.get("record_id") or novel_id),
                    {"自动发布开关": False, "发布暂停原因": INVENTORY_PAUSE_REASON},
                )
            elif available >= self.pause_threshold and pause_reason == INVENTORY_PAUSE_REASON:
                await self.feishu_client.update_record(
                    "小说总览表",
                    str(record.get("record_id") or novel_id),
                    {"自动发布开关": True, "发布暂停原因": ""},
                )

    @staticmethod
    def _is_inventory_chapter(fields: dict[str, Any]) -> bool:
        return (
            fields.get("生产状态") in INVENTORY_STATUSES
            or fields.get("发布状态") in PENDING_PUBLISH_STATUSES
        )

    async def _check_confirmation_queue(self, report: WatchdogReport) -> None:
        pending = 0
        for table in CONFIRMATION_TABLES:
            records = await self.feishu_client.list_records(table)
            pending += sum(
                1 for record in records if record.get("fields", record).get("确认状态") in PENDING_CONFIRMATION
            )
        if pending > self.confirm_threshold:
            report.warn("confirm_queue", f"待确认事项已积压 {pending} 条")

    def _check_circuits(self, report: WatchdogReport) -> None:
        for name, client in self.clients.items():
            breaker = getattr(client, "circuit_breaker", None)
            state = getattr(breaker, "state", None)
            if state == CircuitState.OPEN or str(state).lower().endswith("open"):
                report.warn("circuit", f"{name} 已熔断")

    async def _check_feishu(self, report: WatchdogReport) -> None:
        try:
            await self.feishu_client.tenant_access_token()
        except Exception as exc:
            report.critical("feishu", f"飞书连通性异常：{exc}")

    async def _write_report(self, report: WatchdogReport) -> None:
        if report.healthy:
            await self._write_log("成功/Success", "watchdog healthy")
            return
        for alert in report.alerts:
            await self._write_log(alert.severity, f"{alert.category}: {alert.message}")

    async def _write_log(self, status: str, message: str) -> None:
        await self.feishu_client.create_record(
            "运行日志表",
            {
                "日志ID": f"watchdog-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                "节点名称": "watchdog",
                "执行状态": status,
                "错误信息": "" if status == "成功/Success" else message,
                "输入摘要": "watchdog",
                "输出摘要": message,
                "重试次数": 0,
            },
        )
