from __future__ import annotations

from typing import Any

from llm.base import ChatCompletionClient


class DeepSeekClient(ChatCompletionClient):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            api_key_env="DEEPSEEK_API_KEY",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
            **kwargs,
        )
