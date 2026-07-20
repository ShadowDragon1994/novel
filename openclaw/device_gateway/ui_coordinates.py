from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PROFILE_PATH = Path(__file__).with_name("ui_coordinates.yaml")


class UiCoordinateError(ValueError):
    """Raised when an action is not valid for the current UI state."""


@dataclass(frozen=True)
class ResolvedAction:
    point: tuple[int, int]
    next_state: str
    verify_any: tuple[str, ...]


class CoordinateProfile:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    @classmethod
    def load_default(cls) -> CoordinateProfile:
        with DEFAULT_PROFILE_PATH.open(encoding="utf-8") as profile_file:
            return cls(yaml.safe_load(profile_file) or {})

    def resolve(self, state: str, action: str, *, width: int, height: int) -> ResolvedAction:
        try:
            definition = self.data["states"][state]["actions"][action]
        except KeyError:
            raise UiCoordinateError(f"action {action!r} is not configured for state {state!r}") from None

        reference = self.data["reference_resolution"]
        x = round(int(definition["x"]) * width / int(reference["width"]))
        y = round(int(definition["y"]) * height / int(reference["height"]))
        return ResolvedAction(
            point=(x, y),
            next_state=str(definition["next_state"]),
            verify_any=tuple(str(label) for label in definition.get("verify_any", [])),
        )
