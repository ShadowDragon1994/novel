from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT_DIR / "config"


class Settings(BaseModel):
    raw: dict[str, Any]
    field_mapping: dict[str, Any]


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    load_dotenv(CONFIG_DIR / ".env")
    with (CONFIG_DIR / "config.yaml").open("r", encoding="utf-8") as config_file:
        raw = yaml.safe_load(config_file) or {}
    with (CONFIG_DIR / "field_mapping.yaml").open("r", encoding="utf-8") as mapping_file:
        field_mapping = yaml.safe_load(mapping_file) or {}
    return Settings(raw=raw, field_mapping=field_mapping)
