from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from business.topic_analyzer import TopicAnalyzer, TopicCandidate
from core.config import ROOT_DIR, load_settings
from device_gateway.adb_ui_driver import AdbUiDriver
from device_gateway.fanqie_inspiration_workflow import FanqieInspirationWorkflow, InspirationPage, InspirationSnapshot


@dataclass(frozen=True)
class TopicScanResult:
    snapshot_path: str
    topics_path: str
    topics: list[TopicCandidate]


class TopicScanner:
    def __init__(self, *, analyzer: TopicAnalyzer | None = None, output_dir: Path | None = None) -> None:
        self.analyzer = analyzer or TopicAnalyzer()
        self.output_dir = output_dir or ROOT_DIR / "output" / "topic_discovery"

    async def run_once(self, *, device_id: str | None = None, max_scrolls: int = 3, limit: int = 20) -> TopicScanResult:
        device = device_id or self._default_device_id()
        if not device:
            raise RuntimeError("missing topic discovery device_id")
        driver = AdbUiDriver(device, pause_seconds=0.6, startup_wait_seconds=5, wait_timeout_seconds=30)
        snapshot = await FanqieInspirationWorkflow(driver, device_id=device).collect(max_scrolls=max_scrolls)
        topics = self.analyzer.analyze_snapshot(snapshot, limit=limit)
        return self._write_result(snapshot, topics)

    def analyze_snapshot_file(self, snapshot_path: str | Path, *, limit: int = 20) -> TopicScanResult:
        payload = json.loads(Path(snapshot_path).read_text(encoding="utf-8-sig"))
        snapshot = InspirationSnapshot(
            device_id=str(payload.get("device_id") or ""),
            collected_at=str(payload.get("collected_at") or ""),
            pages=[
                InspirationPage(
                    name=str(item.get("name") or "开书灵感"),
                    text=str(item.get("text") or ""),
                    collected_at=str(item.get("collected_at") or ""),
                    scroll_index=int(item.get("scroll_index") or 0),
                )
                for item in payload.get("pages", [])
            ],
        )
        topics = self.analyzer.analyze_snapshot(snapshot, limit=limit)
        return self._write_result(snapshot, topics)

    def _write_result(self, snapshot: InspirationSnapshot, topics: list[TopicCandidate]) -> TopicScanResult:
        batch = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = self.output_dir / f"fanqie_inspiration_snapshot_{batch}.json"
        topics_path = self.output_dir / f"topic_candidates_{batch}.json"
        snapshot.write_json(snapshot_path)
        topics_path.write_text(
            json.dumps([asdict(topic) for topic in topics], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return TopicScanResult(str(snapshot_path), str(topics_path), topics)

    def _default_device_id(self) -> str:
        settings = load_settings().raw
        topic_config: dict[str, Any] = settings.get("topic_discovery", {}) or {}
        if topic_config.get("device_id"):
            return str(topic_config["device_id"])
        devices = settings.get("adb", {}).get("devices", [])
        return str(devices[0].get("device_id") or "") if devices else ""
