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
    assert action.next_state == "published"
    assert action.requires_confirmation is True
