
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from business.topic_development import TopicDevelopmentPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run market validation, worldview build, and chapter outline generation.")
    parser.add_argument("--topics-path", required=True, help="topic_candidates_*.json path")
    parser.add_argument("--topic-index", type=int, default=0)
    parser.add_argument("--chapter-count", type=int, default=12)
    args = parser.parse_args()

    result, output_path = TopicDevelopmentPipeline().run_from_topics_file(
        args.topics_path,
        topic_index=args.topic_index,
        chapter_count=args.chapter_count,
    )
    print(json.dumps({
        "output_path": output_path,
        "decision": result.market_validation.decision,
        "market_score": result.market_validation.market_score,
        "title_seed": result.worldview.title_seed,
        "chapter_count": len(result.chapter_outlines),
        "first_chapter": result.chapter_outlines[0].title if result.chapter_outlines else "",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
