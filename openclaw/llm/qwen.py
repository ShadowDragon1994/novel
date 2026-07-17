from __future__ import annotations

from typing import Any

from llm.base import ChatCompletionClient


class QwenClient(ChatCompletionClient):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            api_key_env="QWEN_API_KEY",
            model="qwen-plus",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            **kwargs,
        )
