from __future__ import annotations

from typing import Any

from llm.base import ChatCompletionClient


class WenxinClient(ChatCompletionClient):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            api_key_env="WENXIN_API_KEY",
            model="ernie-4.0-turbo-128k",
            base_url="https://qianfan.baidubce.com/v2",
            **kwargs,
        )
