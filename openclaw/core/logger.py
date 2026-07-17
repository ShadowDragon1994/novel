from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from typing import Any

from loguru import logger

from core.config import ROOT_DIR

LOG_DIR = ROOT_DIR / "logs"
LOG_FILE = LOG_DIR / "openclaw.log"

_configured = False


def configure_logging(*, console: bool = True) -> None:
    global _configured
    if _configured:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        logger.remove(0)
    except ValueError:
        pass
    logger.add(LOG_FILE, rotation="10 MB", retention="14 days", encoding="utf-8", enqueue=True)
    if console:
        logger.add(sys.stderr, level="INFO")
    _configured = True


def get_logger(name: str):
    return logger.bind(module=name)


def build_log_fields(record: dict[str, Any]) -> dict[str, Any]:
    extra = record.get("extra", {})
    return {
        "日志ID": extra.get("log_id") or f"log-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        "节点名称": extra.get("node") or extra.get("module") or record["function"],
        "执行状态": extra.get("status", "成功/Success"),
        "错误信息": record["exception"] and str(record["exception"]) or extra.get("error_message", ""),
        "输入摘要": extra.get("input_summary", ""),
        "输出摘要": record["message"],
        "重试次数": extra.get("retry_count", 0),
    }


async def write_feishu_log(
    feishu_client: Any,
    *,
    level: str,
    module: str,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    fields = {
        "日志ID": extra.get("log_id") or f"log-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        "节点名称": extra.get("node", module),
        "执行状态": extra.get("status", "成功/Success"),
        "错误信息": extra.get("exception", "") or extra.get("error_message", ""),
        "输入摘要": extra.get("input_summary", f"level={level}; module={module}"),
        "输出摘要": message,
        "重试次数": extra.get("retry_count", 0),
    }
    return await feishu_client.create_record("运行日志表", fields)


class FeishuLogSink:
    def __init__(self, feishu_client: Any) -> None:
        self.feishu_client = feishu_client
        self.tasks: set[asyncio.Task[Any]] = set()

    def __call__(self, message: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        fields = build_log_fields(message.record)
        task = loop.create_task(self.feishu_client.create_record("运行日志表", fields))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)


def configure_feishu_logging(feishu_client: Any, *, level: str = "INFO") -> int:
    return logger.add(FeishuLogSink(feishu_client), level=level, enqueue=False)
