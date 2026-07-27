from apscheduler.schedulers.asyncio import AsyncIOScheduler

from main import add_job_if_implemented, create_scheduler, is_implemented_job


async def implemented_job() -> None:
    return None


async def unimplemented_job() -> None:
    raise NotImplementedError("not ready")


def test_is_implemented_job_detects_stub() -> None:
    assert is_implemented_job(implemented_job)
    assert not is_implemented_job(unimplemented_job)


def test_add_job_if_implemented_skips_stub() -> None:
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    add_job_if_implemented(scheduler, unimplemented_job, "interval", seconds=1, id="stub")
    assert scheduler.get_job("stub") is None


def test_add_job_if_implemented_adds_real_job() -> None:
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    add_job_if_implemented(scheduler, implemented_job, "interval", seconds=1, id="real")
    assert scheduler.get_job("real") is not None


def test_create_scheduler_registers_all_jobs() -> None:
    scheduler = create_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {
        "production_scanner",
        "publish_scanner",
        "review_processor",
        "publish_plan_evening",
        "publish_plan_morning",
        "watchdog",
    }


def test_create_scheduler_uses_configured_scan_intervals_and_tracks_publish_resource() -> None:
    scheduler = create_scheduler(
        settings={
            "scan": {
                "production_interval_seconds": 7,
                "publish_interval_seconds": 11,
                "watchdog_interval_seconds": 13,
            }
        }
    )

    assert scheduler.get_job("production_scanner").trigger.interval.total_seconds() == 7
    assert scheduler.get_job("publish_scanner").trigger.interval.total_seconds() == 11
    assert scheduler.get_job("watchdog").trigger.interval.total_seconds() == 13
    assert len(scheduler.openclaw_resources) >= 2
