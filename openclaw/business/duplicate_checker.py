from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
import re


@dataclass(frozen=True)
class DuplicateCheckResult:
    passed: bool
    score: float
    repeated_paragraphs: list[str]
    similar_pairs: list[tuple[int, int, float]]
    warnings: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


class DuplicateChecker:
    """Local pre-publish duplicate guard for Fanqie chapter text."""

    def __init__(self, *, paragraph_threshold: float = 0.86, max_score: float = 0.18) -> None:
        self.paragraph_threshold = paragraph_threshold
        self.max_score = max_score

    def check(self, content: str) -> DuplicateCheckResult:
        paragraphs = [p.strip() for p in re.split(r"\n+", content) if len(p.strip()) >= 40]
        repeated: list[str] = []
        similar_pairs: list[tuple[int, int, float]] = []
        warnings: list[str] = []
        exact_seen: dict[str, int] = {}
        for idx, paragraph in enumerate(paragraphs):
            key = re.sub(r"\s+", "", paragraph)
            if key in exact_seen:
                repeated.append(paragraph[:80])
            exact_seen[key] = idx

        high_similarity = 0.0
        comparisons = 0
        for i in range(len(paragraphs)):
            for j in range(i + 1, len(paragraphs)):
                comparisons += 1
                ratio = SequenceMatcher(None, paragraphs[i], paragraphs[j]).ratio()
                if ratio >= self.paragraph_threshold:
                    similar_pairs.append((i + 1, j + 1, round(ratio, 3)))
                    high_similarity += ratio

        mechanical = len(re.findall(r"(?:Scene|Hour)\s*\d+", content, re.I))
        if mechanical >= 3:
            warnings.append("mechanical numbered paragraphs")
        if repeated:
            warnings.append("exact repeated paragraphs")
        if similar_pairs:
            warnings.append("highly similar paragraphs")

        score = 0.0
        if comparisons:
            score += min(1.0, high_similarity / max(1, len(paragraphs)))
        score += min(0.4, len(repeated) * 0.08)
        score += min(0.3, mechanical * 0.03)
        score = round(score, 3)
        return DuplicateCheckResult(
            passed=not warnings and score <= self.max_score,
            score=score,
            repeated_paragraphs=repeated,
            similar_pairs=similar_pairs[:20],
            warnings=warnings,
        )
