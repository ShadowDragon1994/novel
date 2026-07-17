import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from business.production_scanner import ProductionScanner
from business.publish_scanner import PublishScanner
from business.publish_scheduler import PublishScheduler
from business.review_processor import ReviewProcessor
from business.watchdog import Watchdog
from core.logger import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


def is_implemented_job(job: Callable[..., Awaitable[Any]]) -> bool:
    try:
        source = inspect.getsource(job)
    except (OSError, TypeError):
        return True
    return "NotImplementedError" not in source


def add_job_if_implemented(
    scheduler: AsyncIOScheduler,
    job: Callable[..., Awaitable[Any]],
    *args: Any,
    **kwargs: Any,
) -> None:
    job_id = kwargs.get("id", getattr(job, "__name__", "unknown"))
    if not is_implemented_job(job):
        logger.warning("Skipping unimplemented job: {}", job_id)
        return
    scheduler.add_job(job, *args, **kwargs)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

    production_scanner = ProductionScanner()
    publish_scanner = PublishScanner()
    publish_scheduler = PublishScheduler()
    review_processor = ReviewProcessor(production_scanner.feishu_client, production_scanner.guard_layer)
    watchdog = Watchdog(clients={step.value: client for step, client in production_scanner.pipeline.clients.items()})

    add_job_if_implemented(scheduler, production_scanner.run_once, "interval", seconds=300, id="production_scanner")
    add_job_if_implemented(scheduler, publish_scanner.run_once, "interval", seconds=300, id="publish_scanner")
    add_job_if_implemented(scheduler, review_processor.run_once, "interval", seconds=60, id="review_processor")
    add_job_if_implemented(
        scheduler,
        publish_scheduler.generate_daily_plan,
        "cron",
        hour=23,
        minute=0,
        id="publish_plan_evening",
    )
    add_job_if_implemented(
        scheduler,
        publish_scheduler.generate_daily_plan,
        "cron",
        hour=8,
        minute=10,
        id="publish_plan_morning",
    )
    add_job_if_implemented(scheduler, watchdog.run_once, "interval", seconds=60, id="watchdog")
    scheduler.openclaw_resources = [production_scanner]
    return scheduler


async def main() -> None:
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("OpenClaw orchestrator started — 5 jobs registered")

    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        logger.info("OpenClaw orchestrator stopped")
        scheduler.shutdown()
        for resource in getattr(scheduler, "openclaw_resources", []):
            close = getattr(resource, "close", None)
            if asyncio.iscoroutinefunction(close):
                await close()
            elif close:
                close()


if __name__ == "__main__":
    asyncio.run(main())
