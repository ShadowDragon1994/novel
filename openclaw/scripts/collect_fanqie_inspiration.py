from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from business.topic_scanner import TopicScanner


async def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Fanqie 开书灵感 data and generate topic candidates.")
    parser.add_argument("--device-id", default="", help="ADB device id, e.g. 127.0.0.1:65429")
    parser.add_argument("--max-scrolls", type=int, default=3)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--analyze-snapshot", default="", help="Analyze an existing snapshot JSON without ADB")
    args = parser.parse_args()

    scanner = TopicScanner()
    if args.analyze_snapshot:
        result = scanner.analyze_snapshot_file(args.analyze_snapshot, limit=args.limit)
    else:
        result = await scanner.run_once(
            device_id=args.device_id or None,
            max_scrolls=args.max_scrolls,
            limit=args.limit,
        )
    print(
        json.dumps(
            {
                "snapshot_path": result.snapshot_path,
                "topics_path": result.topics_path,
                "topic_count": len(result.topics),
                "top_topics": [topic.to_dict() for topic in result.topics[:5]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
