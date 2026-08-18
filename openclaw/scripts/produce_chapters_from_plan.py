
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from business.chapter_producer import LocalChapterProducer


def main() -> None:
    parser = argparse.ArgumentParser(description="Produce per-chapter draft/check/polish/compliance artifacts from a topic development plan.")
    parser.add_argument("--plan-path", required=True)
    parser.add_argument("--limit", type=int, default=0, help="Optional chapter limit; 0 means all chapters")
    args = parser.parse_args()

    result, summary_path = LocalChapterProducer().run_from_plan(args.plan_path, limit=args.limit or None)
    print(json.dumps({
        "summary_path": summary_path,
        "output_dir": result.output_dir,
        "chapter_count": result.chapter_count,
        "publish_status": result.chapters[0].publish_status if result.chapters else "",
        "first_chapter": result.chapters[0].title if result.chapters else "",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
