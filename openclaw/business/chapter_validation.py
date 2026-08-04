from __future__ import annotations

from typing import Any


class ChapterTextValidationError(ValueError):
    """Raised when chapter metadata is visibly corrupted."""


def validate_chapter_text(fields: dict[str, Any]) -> None:
    for field_name in ("章节名", "章节卡内容"):
        value = str(fields.get(field_name) or "").strip()
        if _looks_like_question_mark_mojibake(value):
            raise ChapterTextValidationError(f"{field_name}疑似乱码，已阻止继续处理")


def _looks_like_question_mark_mojibake(value: str) -> bool:
    if len(value) < 3:
        return False
    question_marks = value.count("?") + value.count("？")
    return question_marks >= 3 and question_marks / len(value) >= 0.25
