from __future__ import annotations

import pytest

from device_gateway.ui_coordinates import CoordinateProfile, UiCoordinateError


def test_start_creation_is_bound_to_works_page() -> None:
    profile = CoordinateProfile.load_default()

    action = profile.resolve("works_page", "start_creation", width=720, height=1280)

    assert action.point == (344, 993)
    assert action.next_state == "chapter_editor"
    assert action.verify_any == ("下一步", "AI工具箱")


def test_coordinates_scale_from_reference_resolution() -> None:
    profile = CoordinateProfile.load_default()

    action = profile.resolve("works_page", "start_creation", width=1080, height=1920)

    assert action.point == (516, 1490)


def test_action_cannot_be_used_from_a_different_page() -> None:
    profile = CoordinateProfile.load_default()

    with pytest.raises(UiCoordinateError, match="start_creation"):
        profile.resolve("home_page", "start_creation", width=720, height=1280)


def test_typo_confirmation_is_guarded() -> None:
    profile = CoordinateProfile.load_default()

    action = profile.resolve("typo_confirmation", "confirm", width=720, height=1280)

    assert action.point == (508, 749)
    assert action.next_state == "content_detection"
    assert action.requires_confirmation is True


def test_final_publish_is_guarded() -> None:
    profile = CoordinateProfile.load_default()

    action = profile.resolve("publish_settings", "confirm_publish", width=720, height=1280)

    assert action.point == (360, 1140)
    assert action.next_state == "final_submission_confirmation"
    assert action.requires_confirmation is True


def test_ai_declaration_uses_semantic_selector() -> None:
    profile = CoordinateProfile.load_default()

    action = profile.resolve("ai_declaration", "used_ai", width=720, height=1280)

    assert action.point is None
    assert action.selector_description == "有使用AI"
    assert action.next_state == "publish_settings"


def test_night_notice_can_be_dismissed_before_editor_input() -> None:
    profile = CoordinateProfile.load_default()

    action = profile.resolve("chapter_editor", "dismiss_night_notice", width=720, height=1280)

    assert action.point == (635, 314)
    assert action.next_state == "chapter_editor"
    assert action.verify_any == ("请输入正文",)


def test_ai_usage_is_selected_from_publish_settings() -> None:
    profile = CoordinateProfile.load_default()

    action = profile.resolve("publish_settings", "select_ai_usage", width=720, height=1280)

    assert action.point == (580, 707)
    assert action.next_state == "ai_declaration"
    assert action.verify_any == ("有使用AI", "未使用AI")


def test_night_submission_confirmation_is_guarded() -> None:
    profile = CoordinateProfile.load_default()

    action = profile.resolve("final_submission_confirmation", "confirm", width=720, height=1280)

    assert action.point == (508, 840)
    assert action.next_state == "chapter_list"
    assert action.requires_confirmation is True
    assert action.verify_any == ("审核中",)


def test_publish_confirmation_allows_direct_return_to_chapter_list() -> None:
    profile = CoordinateProfile.load_default()

    action = profile.resolve("publish_settings", "confirm_publish", width=720, height=1280)

    assert action.verify_any == ("确定要提交章节？", "章节管理", "审核中", "已发布")


def test_chapter_list_terminal_state_uses_semantic_verification() -> None:
    profile = CoordinateProfile.load_default()

    action = profile.resolve("chapter_list", "verify_submitted", width=720, height=1280)

    assert action.point is None
    assert action.selector_description == "第{chapter_number}章 {title}"
    assert action.next_state == "chapter_list"
    assert action.verify_any == ("审核中",)
