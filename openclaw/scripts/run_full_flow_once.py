from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from business.chapter_producer import LocalChapterProducer
from business.topic_scanner import TopicScanner
from business.topic_development import TopicDevelopmentPipeline
from core.config import ROOT_DIR
from device_gateway.adb_ui_driver import AdbUiDriver
from device_gateway.fanqie_inspiration_workflow import FanqieInspirationWorkflow
from device_gateway.fanqie_workflow import FanqiePublishWorkflow, PublishChapter

Mode = Literal["auto", "new-book", "continue-book"]
ResolvedMode = Literal["new-book", "continue-book"]

FLOW_NODES = [
    "adb_connect",
    "detect_book_mode",
    "collect_topic_inspiration",
    "generate_topic_candidates",
    "market_validation",
    "project_approval_gate",
    "worldview_build",
    "chapter_outline_build",
    "detect_latest_chapter_number",
    "generate_7_stage_chapter",
    "local_duplicate_check",
    "publish_chapter_adb",
    "verify_publish_status",
    "write_run_report",
]


@dataclass
class FullFlowConfig:
    device_id: str
    mode: Mode = "auto"
    plan_path: Path | None = None
    output_root: Path = ROOT_DIR / "output"
    topic_index: int = 0
    chapter_count: int = 12
    max_scrolls: int = 2
    topic_limit: int = 10
    work_title: str = ""
    chapter_title: str = ""
    chapter_number: int | None = None
    dry_run: bool = False


@dataclass
class FullFlowRunner:
    config: FullFlowConfig
    nodes: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    resolved_mode: ResolvedMode | None = None

    def record_node(self, node: str, *, status: str, artifact: str | None = None, detail: Any = None) -> None:
        item = {"node": node, "status": status, "time": datetime.now().isoformat()}
        if detail is not None:
            item["detail"] = detail
        self.nodes.append(item)
        if artifact:
            self.artifacts[node] = artifact

    def build_report(self, *, status: str, publish_status: str = "") -> dict[str, Any]:
        return {
            "status": status,
            "mode": self.resolved_mode or self.config.mode,
            "device_id": self.config.device_id,
            "publish_status": publish_status,
            "nodes": self.nodes,
            "artifacts": self.artifacts,
            "generated_at": datetime.now().isoformat(),
        }

    async def run(self) -> dict[str, Any]:
        if self.config.dry_run:
            self.resolved_mode = choose_mode(
                mode=self.config.mode,
                plan_path=self.config.plan_path,
                output_root=self.config.output_root,
                fanqie_has_chapters=False,
            )
            self.record_node("detect_book_mode", status="ok", detail=self.resolved_mode)
            return self.build_report(status="dry_run")

        await self._adb_connect()
        driver = AdbUiDriver(self.config.device_id, pause_seconds=0.8, startup_wait_seconds=5, wait_timeout_seconds=35)
        has_chapters, latest_chapter = await self._fanqie_has_published_chapters(driver)
        self.resolved_mode = choose_mode(
            mode=self.config.mode,
            plan_path=self.config.plan_path,
            output_root=self.config.output_root,
            fanqie_has_chapters=has_chapters,
        )
        self.record_node("detect_book_mode", status="ok", detail={"mode": self.resolved_mode, "latest_chapter": latest_chapter})

        plan_path = await self._ensure_plan_path(driver)
        chapter_number = self.config.chapter_number or max(1, latest_chapter + 1)
        self.record_node("detect_latest_chapter_number", status="ok", detail={"chapter_number": chapter_number})

        chapter_summary, chapter_dir = self._produce_chapter(plan_path)
        title = self.config.chapter_title or f"完整流程自动测试：第{chapter_number}章"
        content_path = chapter_dir / "final_content.txt"
        publish_status = await self._publish(driver, chapter_number, title, content_path)
        verify_xml, screenshot = await self._verify(driver, chapter_number, title)
        self.record_node("verify_publish_status", status="ok", artifact=str(verify_xml), detail={"screenshot": str(screenshot), "publish_status": publish_status})
        report = self.build_report(status="success", publish_status=publish_status)
        report_path = self._write_report(report)
        self.record_node("write_run_report", status="ok", artifact=str(report_path))
        report["artifacts"]["write_run_report"] = str(report_path)
        return report

    async def _adb_connect(self) -> None:
        adb = os.getenv("ADB_PATH") or r"C:\Users\Administrator\AppData\Local\Android\Sdk\platform-tools\adb.exe"
        completed = subprocess.run([adb, "connect", self.config.device_id], capture_output=True, text=True, timeout=20)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or completed.stdout)
        self.record_node("adb_connect", status="ok", detail=completed.stdout.strip())

    async def _ensure_plan_path(self, driver: AdbUiDriver) -> Path:
        if self.resolved_mode == "continue-book":
            plan = self.config.plan_path or latest_approved_plan(self.config.output_root)
            if not plan:
                raise RuntimeError("continue-book mode requires --plan-path or an approved local topic_development file")
            self.record_node("market_validation", status="skipped", artifact=str(plan), detail="continue-book uses existing approved plan")
            self.record_node("project_approval_gate", status="ok", detail="existing approved plan")
            self.record_node("worldview_build", status="skipped", artifact=str(plan))
            self.record_node("chapter_outline_build", status="skipped", artifact=str(plan))
            return plan

        scanner = TopicScanner()
        result = await scanner.run_once(device_id=self.config.device_id, max_scrolls=self.config.max_scrolls, limit=self.config.topic_limit)
        self.record_node("collect_topic_inspiration", status="ok", artifact=result.snapshot_path)
        self.record_node("generate_topic_candidates", status="ok", artifact=result.topics_path, detail={"topic_count": len(result.topics)})
        dev_result, plan_path_str = TopicDevelopmentPipeline().run_from_topics_file(
            result.topics_path,
            topic_index=self.config.topic_index,
            chapter_count=self.config.chapter_count,
        )
        self.record_node("market_validation", status="ok", artifact=plan_path_str, detail=dev_result.market_validation.validation_signals)
        self.record_node("project_approval_gate", status=dev_result.market_validation.decision, detail={"score": dev_result.market_validation.market_score})
        if dev_result.market_validation.decision != "立项通过":
            raise RuntimeError(f"topic not approved: {dev_result.market_validation.decision}")
        self.record_node("worldview_build", status="ok", artifact=plan_path_str, detail=dev_result.worldview.title_seed)
        self.record_node("chapter_outline_build", status="ok", artifact=plan_path_str, detail={"chapter_count": len(dev_result.chapter_outlines)})
        return Path(plan_path_str)

    def _produce_chapter(self, plan_path: Path) -> tuple[Path, Path]:
        result, summary = LocalChapterProducer().run_from_plan(plan_path, limit=1)
        chapter_dir = Path(result.output_dir) / "chapter_001"
        self.record_node("generate_7_stage_chapter", status="ok", artifact=str(chapter_dir), detail={"files": [p.name for p in sorted(chapter_dir.glob("[0-9][0-9]_*.txt"))]})
        artifact = result.chapters[0]
        self.record_node("local_duplicate_check", status=artifact.publish_status, artifact=str(chapter_dir / "07_final.txt"))
        if artifact.publish_status != "pending_publish":
            raise RuntimeError(f"chapter is not publish-ready: {artifact.publish_status}")
        return Path(summary), chapter_dir

    async def _publish(self, driver: AdbUiDriver, chapter_number: int, title: str, content_path: Path) -> str:
        content = content_path.read_text(encoding="utf-8-sig").strip()
        await FanqieInspirationWorkflow(driver, device_id=self.config.device_id).open_my_page()
        await driver.tap((228, 1224))
        await asyncio.sleep(2.0)
        await driver.tap((268, 650))
        await asyncio.sleep(2.0)
        workflow = FanqiePublishWorkflow(driver)
        result = await workflow.publish(PublishChapter(number=chapter_number, title=title, content=content))
        self.record_node("publish_chapter_adb", status=result.status, artifact=str(content_path), detail=result.chapter_label)
        return result.status

    async def _verify(self, driver: AdbUiDriver, chapter_number: int, title: str) -> tuple[Path, Path]:
        text = await driver.screen_text()
        if f"第{chapter_number}章" not in text:
            try:
                await driver.tap_description_contains("章节管理")
                await asyncio.sleep(2)
            except Exception:
                pass
        adb = os.getenv("ADB_PATH") or r"C:\Users\Administrator\AppData\Local\Android\Sdk\platform-tools\adb.exe"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        xml_remote = f"/sdcard/full_flow_verify_{stamp}.xml"
        xml_path = ROOT_DIR / "logs" / f"full_flow_verify_{stamp}.xml"
        png_path = ROOT_DIR / "output" / f"full_flow_verify_{stamp}.png"
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([adb, "-s", self.config.device_id, "shell", "uiautomator", "dump", xml_remote], check=False, capture_output=True)
        with xml_path.open("wb") as fh:
            subprocess.run([adb, "-s", self.config.device_id, "exec-out", "cat", xml_remote], check=False, stdout=fh)
        with png_path.open("wb") as fh:
            subprocess.run([adb, "-s", self.config.device_id, "exec-out", "screencap", "-p"], check=False, stdout=fh)
        return xml_path, png_path

    async def _fanqie_has_published_chapters(self, driver: AdbUiDriver) -> tuple[bool, int]:
        try:
            await FanqieInspirationWorkflow(driver, device_id=self.config.device_id).open_my_page()
            await driver.tap((228, 1224))
            await asyncio.sleep(2.0)
            await driver.tap((268, 650))
            await asyncio.sleep(2.0)
            text = await driver.screen_text()
        except Exception:
            return False, 0
        nums = [int(x) for x in re.findall(r"第\s*([0-9]+)\s*章", text)]
        return bool(nums), max(nums) if nums else 0

    def _write_report(self, report: dict[str, Any]) -> Path:
        report_dir = ROOT_DIR / "output" / "full_flow_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / f"full_flow_report_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def is_approved_plan(plan_path: str | Path | None) -> bool:
    if not plan_path:
        return False
    path = Path(plan_path)
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return False
    return payload.get("market_validation", {}).get("decision") == "立项通过"


def latest_approved_plan(output_root: str | Path) -> Path | None:
    root = Path(output_root)
    candidates = sorted((root / "topic_development").glob("topic_development_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        if is_approved_plan(path):
            return path
    return None


def choose_mode(*, mode: Mode, plan_path: str | Path | None, output_root: str | Path, fanqie_has_chapters: bool) -> ResolvedMode:
    if mode in ("new-book", "continue-book"):
        return mode
    if plan_path and is_approved_plan(plan_path):
        return "continue-book"
    if latest_approved_plan(output_root):
        return "continue-book"
    if fanqie_has_chapters:
        return "continue-book"
    return "new-book"


def parse_args() -> FullFlowConfig:
    parser = argparse.ArgumentParser(description="Run one full Fanqie novel workflow: new-book or continue-book.")
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--mode", choices=["auto", "new-book", "continue-book"], default="auto")
    parser.add_argument("--plan-path", default="")
    parser.add_argument("--topic-index", type=int, default=0)
    parser.add_argument("--chapter-count", type=int, default=12)
    parser.add_argument("--max-scrolls", type=int, default=2)
    parser.add_argument("--topic-limit", type=int, default=10)
    parser.add_argument("--work-title", default="")
    parser.add_argument("--chapter-title", default="")
    parser.add_argument("--chapter-number", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return FullFlowConfig(
        device_id=args.device_id,
        mode=args.mode,
        plan_path=Path(args.plan_path) if args.plan_path else None,
        topic_index=args.topic_index,
        chapter_count=args.chapter_count,
        max_scrolls=args.max_scrolls,
        topic_limit=args.topic_limit,
        work_title=args.work_title,
        chapter_title=args.chapter_title,
        chapter_number=args.chapter_number or None,
        dry_run=args.dry_run,
    )


async def amain() -> None:
    report = await FullFlowRunner(parse_args()).run()
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
