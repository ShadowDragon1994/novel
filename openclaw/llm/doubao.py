from __future__ import annotations

from typing import Any

from llm.base import ChatCompletionClient


class DoubaoClient(ChatCompletionClient):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            api_key_env="DOUBAO_API_KEY",
            model="doubao-seed-2-0-pro-260215",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            timeout=300,
            **kwargs,
        )
