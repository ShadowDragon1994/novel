from __future__ import annotations

from datetime import datetime
from typing import Any

from business.device_controller import DeviceController
from business.guard_layer import GuardLayer
from core.config import load_settings
from core.feishu_client import FeishuClient

READY_PUBLISH_STATUS = {"待发布", "待发布/Pending Publish"}
SUCCESS_PUBLISH_STATUS = {"发布成功", "发布成功/Published", "成功/Success"}
FINAL_PRODUCTION_STATUS = {"已定稿", "已定稿/Finalized", "已审核", "已完成"}
LOCKED_VALUES = {"是", "是/Yes", True, "人工锁定", "已锁定"}
AUTO_PUBLISH_ON = {"是", "是/Yes", "开启", "开启/Enabled", True}
HEALTHY_ACCOUNT_STATUS = {"正常", "正常/Normal", ""}


class PublishScanner:
    def __init__(
        self,
        feishu_client: FeishuClient | None = None,
        guard_layer: GuardLayer | None = None,
        device_controller: DeviceController | None = None,
    ) -> None:
        self.feishu_client = feishu_client or FeishuClient()
        self.guard_layer = guard_layer or GuardLayer(self.feishu_client)
        self.device = device_controller or DeviceController()
        self.max_attempts = int(load_settings().raw.get("retry", {}).get("publish_max_attempts", 3))

    async def run_once(self, *, now: datetime | None = None) -> list[str]:
        ready = await self._ready_chapters(now or datetime.now())
        results = []
        for record in ready:
            result = await self._publish_one(record)
            if result:
                results.append(result)
        return results

    async def _ready_chapters(self, now: datetime) -> list[dict[str, Any]]:
        records = await self.feishu_client.list_records("章节任务表")
        ready = []
        for record in records:
            fields = record.get("fields", record)
            planned_at = self._parse_datetime(fields.get("计划发布时间"))
            novel_id = str(fields.get("小说ID") or "")
            if fields.get("生产状态") not in FINAL_PRODUCTION_STATUS:
                continue
            if fields.get("内容锁定状态") not in LOCKED_VALUES:
                continue
            if not fields.get("当前版本"):
                continue
            if not await self._novel_auto_publish_enabled(novel_id):
                continue
            account_id = await self._resolve_account(novel_id)
            if not account_id or not await self._account_is_healthy(account_id):
                continue
            if fields.get("发布状态") in READY_PUBLISH_STATUS and planned_at and planned_at <= now:
                ready.append(record)
        return sorted(ready, key=lambda record: str(record.get("fields", record).get("计划发布时间") or ""))

    async def _publish_one(self, record: dict[str, Any]) -> str | None:
        fields = record.get("fields", record)
        chapter_id = str(fields["章节ID"])
        if await self._already_published(chapter_id):
            return None
        account_id = await self._resolve_account(str(fields.get("小说ID") or ""))
        if not account_id:
            await self._mark_failure(record, RuntimeError("missing account_id"), account_id="")
            return None
        try:
            device_id = await self._resolve_device_id(account_id)
            content = await self._load_final_content(chapter_id)
            if not device_id:
                raise RuntimeError("missing hongshouzhi device_id")
            if not content:
                raise RuntimeError("missing final chapter content")
            result = await self.device.publish_chapter(
                chapter_id,
                account_id,
                device_id=device_id,
                platform="fanqie",
                chapter_number=int(fields.get("章节号") or 0),
                title=str(fields.get("章节名") or ""),
                content=content,
            )
            await self._mark_success(record, account_id, result["status"])
            return chapter_id
        except Exception as exc:
            await self._mark_failure(record, exc, account_id=account_id)
            return None

    async def _novel_auto_publish_enabled(self, novel_id: str) -> bool:
        novels = await self.feishu_client.list_records("小说总览表")
        for record in novels:
            fields = record.get("fields", record)
            if fields.get("小说ID") == novel_id:
                switch_val = fields.get("自动发布开关")
                if switch_val is None:
                    return True
                return switch_val in AUTO_PUBLISH_ON
        return True

    async def _already_published(self, chapter_id: str) -> bool:
        records = await self.feishu_client.list_records("发布记录表")
        return any(
            record.get("fields", record).get("章节ID") == chapter_id
            and record.get("fields", record).get("发布尝试状态") in SUCCESS_PUBLISH_STATUS
            for record in records
        )

    async def _resolve_account(self, novel_id: str) -> str:
        novels = await self.feishu_client.list_records("小说总览表")
        for record in novels:
            fields = record.get("fields", record)
            if fields.get("小说ID") == novel_id and fields.get("关联账号"):
                linked = fields["关联账号"]
                if isinstance(linked, list) and linked:
                    linked = linked[0]
                if isinstance(linked, dict):
                    linked = linked.get("record_id") or linked.get("id") or linked.get("text") or ""
                return str(linked)
        accounts = await self.feishu_client.list_records("账号管理表")
        for record in accounts:
            fields = record.get("fields", record)
            if str(fields.get("绑定小说ID") or "") == novel_id:
                return str(fields.get("账号ID") or record.get("record_id") or "")
        return ""

    async def _account_is_healthy(self, account_id: str) -> bool:
        accounts = await self.feishu_client.list_records("账号管理表")
        for record in accounts:
            fields = record.get("fields", record)
            current_id = str(fields.get("账号ID") or fields.get("ID") or record.get("record_id") or "")
            if current_id == account_id:
                healthy = str(fields.get("账号健康状态") or fields.get("账号状态") or "") in HEALTHY_ACCOUNT_STATUS
                enabled = fields.get("自动发布开关", True) in AUTO_PUBLISH_ON
                stage = str(fields.get("账号阶段") or "稳定期")
                return healthy and enabled and stage not in {"养号期", "养号期/Warmup"}
        return False

    async def _resolve_device_id(self, account_id: str) -> str:
        accounts = await self.feishu_client.list_records("账号管理表")
        for record in accounts:
            fields = record.get("fields", record)
            current_id = str(fields.get("账号ID") or fields.get("ID") or record.get("record_id") or "")
            if current_id == account_id:
                return str(fields.get("红手指设备ID") or "")
        return ""

    async def _load_final_content(self, chapter_id: str) -> str:
        versions = await self.feishu_client.list_records("正文版本表")
        candidates = [
            record.get("fields", record)
            for record in versions
            if record.get("fields", record).get("章节ID") == chapter_id
            and (
                record.get("fields", record).get("是否当前最终版") is True
                or record.get("fields", record).get("版本类型") == "校对稿"
            )
        ]
        if not candidates:
            return ""
        return str(candidates[-1].get("版本内容") or "")

    async def _set_account_health(self, account_id: str, status: str) -> None:
        accounts = await self.feishu_client.list_records("账号管理表")
        for record in accounts:
            fields = record.get("fields", record)
            current_id = str(fields.get("账号ID") or fields.get("ID") or record.get("record_id") or "")
            if current_id == account_id:
                await self.feishu_client.update_record(
                    "账号管理表",
                    str(record.get("record_id") or current_id),
                    {"账号状态": status},
                )
                return

    async def _mark_success(self, record: dict[str, Any], account_id: str, platform_status: str) -> None:
        fields = record.get("fields", record)
        chapter_id = str(fields["章节ID"])
        await self.feishu_client.create_record(
            "发布记录表",
            {
                "发布ID": f"pub-{chapter_id}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                "章节ID": chapter_id,
                "账号ID": account_id,
                "发布时间": int(datetime.now().timestamp() * 1000),
                "发布尝试状态": "成功/Success" if platform_status == "已发布" else "已提交/Submitted",
                "失败原因": "",
                "关联正文版本": fields.get("当前版本", ""),
            },
        )
        await self.guard_layer.write(
            "章节任务表",
            str(record.get("record_id") or chapter_id),
            {"发布状态": "发布成功/Published" if platform_status == "已发布" else "审核中/Under Review"},
        )
        await self._update_account_after_success(account_id)

    async def _update_account_after_success(self, account_id: str) -> None:
        accounts = await self.feishu_client.list_records("账号管理表")
        for record in accounts:
            fields = record.get("fields", record)
            current_id = str(fields.get("账号ID") or fields.get("ID") or record.get("record_id") or "")
            if current_id == account_id:
                await self.feishu_client.update_record(
                    "账号管理表",
                    str(record.get("record_id") or current_id),
                    {
                        "上次发布时间": int(datetime.now().timestamp() * 1000),
                        "今日已发布章数": int(fields.get("今日已发布章数") or 0) + 1,
                    },
                )
                return

    async def _mark_failure(self, record: dict[str, Any], exc: Exception, *, account_id: str = "") -> None:
        fields = record.get("fields", record)
        chapter_id = str(fields["章节ID"])
        attempts = int(fields.get("流程重试次数") or 0) + 1
        status = "发布失败/Publish Failed" if attempts >= self.max_attempts else "待发布/Pending Publish"
        error_message = str(exc)
        await self.feishu_client.create_record(
            "发布记录表",
            {
                "发布ID": f"pub-fail-{chapter_id}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                "章节ID": chapter_id,
                "账号ID": account_id or str(fields.get("账号ID") or ""),
                "发布时间": int(datetime.now().timestamp() * 1000),
                "发布尝试状态": "失败/Failed",
                "失败原因": error_message,
            },
        )
        await self.guard_layer.write(
            "章节任务表",
            str(record.get("record_id") or chapter_id),
            {"发布状态": status, "错误信息": error_message, "流程重试次数": attempts},
        )
        if attempts >= self.max_attempts and account_id:
            await self._set_account_health(account_id, "观察/Observing")

    def _parse_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000)
        if isinstance(value, str) and value:
            return datetime.fromisoformat(value)
        return None
