from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any

import httpx

from core.circuit_breaker import CircuitBreaker
from core.rate_limiter import RateLimiter


class LLMError(RuntimeError):
    pass


class CircuitOpenError(LLMError):
    pass


class LLMClient(ABC):
    @abstractmethod
    async def generate(self, prompt: str) -> str:
        raise NotImplementedError


class ChatCompletionClient(LLMClient):
    def __init__(
        self,
        *,
        api_key_env: str,
        model: str,
        base_url: str,
        endpoint: str = "/chat/completions",
        api_key: str | None = None,
        rate_limiter: RateLimiter | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        http_client: httpx.AsyncClient | None = None,
        temperature: float = 0.7,
        timeout: int = 120,
    ) -> None:
        self.api_key = api_key or os.getenv(api_key_env, "")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.endpoint = endpoint
        self.rate_limiter = rate_limiter or RateLimiter(qps=2, capacity=2)
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.http_client = http_client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            trust_env=False,
        )
        self._owns_client = http_client is None
        self.temperature = temperature

    async def close(self) -> None:
        if self._owns_client:
            await self.http_client.aclose()

    async def generate(self, prompt: str) -> str:
        if not self.circuit_breaker.allow_request():
            raise CircuitOpenError(f"circuit open for model {self.model}")
        await self.rate_limiter.acquire()
        try:
            response = await self.http_client.post(
                self.endpoint,
                headers=self._headers(),
                json=self._payload(prompt),
            )
            response.raise_for_status()
            content = self._extract_content(response.json())
            self.circuit_breaker.record_success()
            return content
        except Exception:
            self.circuit_breaker.record_failure()
            raise

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(self, prompt: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
        }

    def _extract_content(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
        result = payload.get("result")
        if isinstance(result, str) and result.strip():
            return result
        output = payload.get("output")
        if isinstance(output, str) and output.strip():
            return output
        raise LLMError(f"empty model response for {self.model}")
