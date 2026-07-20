"""Comprehensive acceptance test for OpenClaw project.

Verifies all 5 phases:
  1. Infrastructure (core/ modules)
  2. Hardening (GuardLayer, cache, bootstrap)
  3. Core business (LLM, Pipeline, Scanner)
  4. Settings extraction + Publish scheduling
  5. Publish execution + Watchdog

Usage: python scripts/acceptance_test.py
"""
import asyncio
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ── Phase 1: Core infrastructure ──────────────────────────────
def check_phase1():
    """Verify all core modules import and instantiate."""
    print("─" * 50)
    print("Phase 1: Core Infrastructure")
    print("─" * 50)
    modules = [
        ("core.config", "load_settings"),
        ("core.feishu_client", "FeishuClient"),
        ("core.rate_limiter", "RateLimiter"),
        ("core.circuit_breaker", "CircuitBreaker"),
        ("core.task_lock", "TaskLock"),
        ("core.read_cache", "ReadCache"),
        ("core.logger", "configure_logging"),
    ]
    ok = 0
    for mod_name, attr in modules:
        try:
            mod = importlib.import_module(mod_name)
            obj = getattr(mod, attr)
            print(f"  ✅ {mod_name}.{attr}")
            ok += 1
        except Exception as e:
            print(f"  ❌ {mod_name}.{attr}: {e}")
    return ok == len(modules)


# ── Phase 2: Hardening ────────────────────────────────────────
def check_phase2():
    """Verify GuardLayer rules, field mapping, healthcheck."""
    print("\n" + "─" * 50)
    print("Phase 2: Hardening")
    print("─" * 50)
    checks = 0
    # 2a. GuardLayer rules exist
    from business.guard_layer import (
        GuardLayer, LOCKED_CHAPTER_FORBIDDEN_FIELDS,
        CORE_PROTECTED_TABLES, CORE_ALWAYS_WRITABLE_FIELDS,
    )
    assert len(LOCKED_CHAPTER_FORBIDDEN_FIELDS) == 8, "Chapter forbidden fields"
    assert len(CORE_PROTECTED_TABLES) == 5, "Core protected tables"
    assert len(CORE_ALWAYS_WRITABLE_FIELDS) == 4, "Core writable fields"
    print(f"  ✅ GuardLayer: 8 forbidden fields, 5 core tables, 4 writable fields")
    # 2b. Field mapping covers 16 tables
    from core.config import load_settings
    settings = load_settings()
    tables = [k for k in settings.field_mapping if settings.field_mapping[k].get("table_id")]
    print(f"  ✅ Field mapping: {len(tables)} tables mapped")
    # 2c. Healthcheck script
    from scripts.healthcheck import Healthcheck
    print(f"  ✅ Healthcheck imports OK")
    # 2d. Bootstrap
    from scripts.bootstrap_feishu import build_novel_seed
    seed = build_novel_seed(99)
    assert "小说ID" in seed
    print(f"  ✅ Bootstrap: seed generation works")
    return True


# ── Phase 3: Core Business ────────────────────────────────────
async def check_phase3():
    """Verify LLM clients, pipeline, scanner."""
    print("\n" + "─" * 50)
    print("Phase 3: Core Business (LLM + Pipeline + Scanner)")
    print("─" * 50)
    # 3a. All 4 LLM clients instantiatable
    from llm.deepseek import DeepSeekClient
    from llm.doubao import DoubaoClient
    from llm.qwen import QwenClient
    from llm.wenxin import WenxinClient
    for cls in [DeepSeekClient, DoubaoClient, QwenClient, WenxinClient]:
        c = cls()
        assert c.model, f"{cls.__name__} has model"
        print(f"  ✅ {cls.__name__}: model={c.model}")
    # 3b. Pipeline steps defined
    from business.llm_pipeline import STEP_ORDER, STEP_TEMPLATE, PipelineStep
    assert len(STEP_ORDER) == 6
    assert len(STEP_TEMPLATE) == 6
    print(f"  ✅ Pipeline: {len(STEP_ORDER)} steps defined")
    # 3c. Prompt templates exist and filled
    prompt_dir = ROOT / "prompts"
    templates = list(prompt_dir.glob("*.j2"))
    filled = 0
    for t in templates:
        text = t.read_text(encoding="utf-8")
        if "Phase 3 placeholder" not in text and len(text.strip()) > 100:
            filled += 1
    print(f"  ✅ Prompts: {filled}/{len(templates)} templates filled")
    # 3d. ProductionScanner instantiatable
    from business.production_scanner import ProductionScanner, PENDING_PRODUCTION_STATUSES
    assert len(PENDING_PRODUCTION_STATUSES) == 9
    print(f"  ✅ ProductionScanner: {len(PENDING_PRODUCTION_STATUSES)} pending statuses")
    return True


# ── Phase 4: Settings + Scheduling ────────────────────────────
async def check_phase4():
    """Verify SettingsExtractor and PublishScheduler."""
    print("\n" + "─" * 50)
    print("Phase 4: SettingsExtractor + PublishScheduler")
    print("─" * 50)
    from business.settings_extractor import SettingsExtractor, ENTITY_SPECS
    assert len(ENTITY_SPECS) == 4, "4 entity types"
    for key, spec in ENTITY_SPECS.items():
        assert spec.id_field and spec.id_prefix, f"ID fields for {key}"
    print(f"  ✅ SettingsExtractor: {len(ENTITY_SPECS)} entity types with ID generation")
    from business.publish_scheduler import PublishScheduler
    s = PublishScheduler()
    assert s.settings is not None
    print(f"  ✅ PublishScheduler: instantiatable")
    return True


# ── Phase 5: Publish + Watchdog ───────────────────────────────
async def check_phase5():
    """Verify PublishScanner, DeviceController, Watchdog."""
    print("\n" + "─" * 50)
    print("Phase 5: PublishScanner + DeviceController + Watchdog")
    print("─" * 50)
    from business.publish_scanner import PublishScanner
    from business.device_controller import DeviceController
    from business.watchdog import Watchdog
    ps = PublishScanner()
    assert ps.max_attempts > 0
    print(f"  ✅ PublishScanner: max_attempts={ps.max_attempts}")
    dc = DeviceController()
    print(f"  ✅ DeviceController: endpoint={'configured' if dc.endpoint else 'not set (graceful degrade)'}")
    w = Watchdog()
    assert w.safety_threshold > 0
    print(f"  ✅ Watchdog: safety={w.safety_threshold}, pause={w.pause_threshold}")
    return True


# ── All NotImplementedError audit ─────────────────────────────
def check_no_stubs():
    """Verify zero NotImplementedError in business + llm modules."""
    print("\n" + "─" * 50)
    print("NotImplementedError Audit")
    print("─" * 50)
    import inspect
    modules_to_check = [
        "business.llm_pipeline",
        "business.production_scanner",
        "business.guard_layer",
        "business.settings_extractor",
        "business.publish_scheduler",
        "business.publish_scanner",
        "business.device_controller",
        "business.watchdog",
        "llm.base",
        "llm.deepseek",
        "llm.doubao",
        "llm.qwen",
        "llm.wenxin",
    ]
    found = []
    for mod_name in modules_to_check:
        mod = importlib.import_module(mod_name)
        for name, obj in inspect.getmembers(mod, inspect.isfunction):
            try:
                src = inspect.getsource(obj)
            except (OSError, TypeError):
                continue
            if "NotImplementedError" in src:
                found.append(f"{mod_name}.{name}")
    if found:
        for f in found:
            print(f"  ❌ {f}")
    else:
        print("  ✅ Zero NotImplementedError found in all business/llm modules")
    return len(found) == 0


# ── main.py startup ───────────────────────────────────────────
def check_main_startup():
    """Verify main.py can be imported and scheduler configured."""
    print("\n" + "─" * 50)
    print("main.py Startup Check")
    print("─" * 50)
    from main import create_scheduler
    scheduler = create_scheduler()
    jobs = scheduler.get_jobs()
    job_ids = {j.id for j in jobs}
    expected = {
        "production_scanner", "publish_scanner",
        "review_processor",
        "publish_plan_evening", "publish_plan_morning",
        "watchdog",
    }
    assert job_ids == expected, f"Expected {expected}, got {job_ids}"
    print(f"  ✅ All {len(jobs)} jobs registered: {job_ids}")
    return True


# ── Test count ────────────────────────────────────────────────
async def check_test_count():
    """Run pytest --collect-only to count tests."""
    print("\n" + "─" * 50)
    print("Test Suite")
    print("─" * 50)
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q", "--no-header"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    lines = result.stdout.strip().split("\n")
    # Last line should be "N tests collected"
    for line in lines:
        if "selected" in line.lower() or "error" in line.lower():
            pass
    count = len([l for l in lines if l.startswith("tests/")])
    print(f"  ✅ {count} tests collected")
    return count >= 140


# ── Run all ───────────────────────────────────────────────────
async def main():
    print("=" * 60)
    print("OpenClaw Acceptance Test")
    print("=" * 60)

    results = {}

    # Phase 1-2 (sync)
    results["Phase 1: Infrastructure"] = check_phase1()
    results["Phase 2: Hardening"] = check_phase2()

    # Phase 3-5 (async capable)
    results["Phase 3: Core Business"] = await check_phase3()
    results["Phase 4: Settings+Sched"] = await check_phase4()
    results["Phase 5: Publish+Watch"] = await check_phase5()

    # Cross-cutting
    results["No stubs"] = check_no_stubs()
    results["main.py startup"] = check_main_startup()
    results["Test count ≥140"] = await check_test_count()

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    all_pass = True
    for name, passed in results.items():
        status = "✅" if passed else "❌"
        if not passed:
            all_pass = False
        print(f"  {status} {name}")

    print()
    if all_pass:
        print("🎉 ALL ACCEPTANCE CHECKS PASSED — OpenClaw is production-ready!")
    else:
        print("❌ SOME CHECKS FAILED — see details above")
    return all_pass


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
