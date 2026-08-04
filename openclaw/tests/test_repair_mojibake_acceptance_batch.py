from datetime import datetime

from scripts.repair_mojibake_acceptance_batch import (
    ACCEPTANCE_CHAPTERS,
    PUBLISHED_CHAPTER_IDS,
    build_approval_update,
    build_chapter_update,
)


def test_repair_manifest_contains_all_fifteen_unique_chapters() -> None:
    chapter_ids = [item.chapter_id for item in ACCEPTANCE_CHAPTERS]

    assert len(chapter_ids) == 15
    assert len(set(chapter_ids)) == 15
    assert len(PUBLISHED_CHAPTER_IDS) == 5
    assert PUBLISHED_CHAPTER_IDS < set(chapter_ids)


def test_unpublished_chapter_is_reset_for_clean_regeneration() -> None:
    item = next(item for item in ACCEPTANCE_CHAPTERS if item.chapter_id == "NOVEL-01-CH-005")

    update = build_chapter_update(item)

    assert update["章节名"] == "第五章：父亲的编号"
    assert update["生产状态"] == "待创作/Pending"
    assert update["发布状态"] == "未排期/Unscheduled"
    assert update["内容锁定状态"] == "否/No"
    assert update["流程重试次数"] == 0


def test_published_chapter_keeps_workflow_state_untouched() -> None:
    item = next(item for item in ACCEPTANCE_CHAPTERS if item.chapter_id == "NOVEL-01-CH-004")

    update = build_chapter_update(item)

    assert update == {
        "章节名": "第四章：灵监会的条件",
        "章节卡内容": item.card,
    }


def test_published_chapter_can_be_reset_without_losing_publish_state() -> None:
    item = next(item for item in ACCEPTANCE_CHAPTERS if item.chapter_id == "NOVEL-01-CH-004")

    update = build_chapter_update(item, regenerate_published=True)

    assert update["生产状态"] == "待创作/Pending"
    assert "发布状态" not in update


def test_approval_update_preserves_publish_state() -> None:
    update = build_approval_update(datetime(2026, 7, 29, 12, 0))

    assert update["人工审核结果"] == "通过"
    assert update["生产状态"] == "已定稿/Finalized"
    assert update["内容锁定状态"] == "是/Yes"
    assert "发布状态" not in update
