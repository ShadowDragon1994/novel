import httpx
import pytest

from core.circuit_breaker import CircuitBreaker, CircuitState
from core.rate_limiter import RateLimiter
from llm.base import ChatCompletionClient, CircuitOpenError, LLMError
from llm.deepseek import DeepSeekClient
from llm.doubao import DoubaoClient
from llm.qwen import QwenClient
from llm.wenxin import WenxinClient


def make_http_client(handler):
    return httpx.AsyncClient(base_url="https://example.test", transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_owned_http_client_ignores_implicit_environment_proxy() -> None:
    client = ChatCompletionClient(
        api_key_env="TEST_API_KEY",
        model="test-model",
        base_url="https://example.com",
    )

    try:
        assert client.http_client._trust_env is False
    finally:
        await client.close()


@pytest.mark.parametrize(
    "client_cls,model",
    [
        (DeepSeekClient, "deepseek-chat"),
        (DoubaoClient, "doubao-seed-2-0-pro-260215"),
        (QwenClient, "qwen-plus"),
        (WenxinClient, "ernie-4.5-turbo-128k"),
    ],
)
def test_model_clients_have_expected_model_names(client_cls, model) -> None:
    client = client_cls(http_client=make_http_client(lambda request: httpx.Response(200, json={})))
    assert client.model == model


@pytest.mark.asyncio
async def test_chat_completion_client_generates_text_and_records_success() -> None:
    breaker = CircuitBreaker(failure_threshold=1)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer key"
        return httpx.Response(200, json={"choices": [{"message": {"content": "中文结果"}}]})

    client = ChatCompletionClient(
        api_key_env="MISSING",
        api_key="key",
        model="model",
        base_url="https://example.test",
        http_client=make_http_client(handler),
        rate_limiter=RateLimiter(1000, 1000),
        circuit_breaker=breaker,
    )
    assert await client.generate("提示词") == "中文结果"
    assert breaker.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_chat_completion_client_records_failure() -> None:
    breaker = CircuitBreaker(failure_threshold=1)
    client = ChatCompletionClient(
        api_key_env="MISSING",
        api_key="key",
        model="model",
        base_url="https://example.test",
        http_client=make_http_client(lambda request: httpx.Response(500, json={"error": "bad"})),
        rate_limiter=RateLimiter(1000, 1000),
        circuit_breaker=breaker,
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client.generate("提示词")
    assert breaker.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_chat_completion_client_blocks_when_circuit_open() -> None:
    breaker = CircuitBreaker(failure_threshold=1)
    breaker.record_failure()
    client = ChatCompletionClient(
        api_key_env="MISSING",
        model="model",
        base_url="https://example.test",
        http_client=make_http_client(lambda request: httpx.Response(200, json={})),
        circuit_breaker=breaker,
    )
    with pytest.raises(CircuitOpenError):
        await client.generate("提示词")


@pytest.mark.asyncio
async def test_chat_completion_client_rejects_empty_response() -> None:
    client = ChatCompletionClient(
        api_key_env="MISSING",
        model="model",
        base_url="https://example.test",
        http_client=make_http_client(lambda request: httpx.Response(200, json={"choices": []})),
        rate_limiter=RateLimiter(1000, 1000),
        circuit_breaker=CircuitBreaker(failure_threshold=2),
    )
    with pytest.raises(LLMError):
        await client.generate("提示词")


@pytest.mark.asyncio
async def test_chat_completion_client_extracts_result_fallback() -> None:
    client = ChatCompletionClient(
        api_key_env="MISSING",
        model="model",
        base_url="https://example.test",
        http_client=make_http_client(lambda request: httpx.Response(200, json={"result": "备用结果"})),
        rate_limiter=RateLimiter(1000, 1000),
    )
    assert await client.generate("提示词") == "备用结果"


@pytest.mark.asyncio
async def test_chat_completion_client_extracts_output_fallback() -> None:
    client = ChatCompletionClient(
        api_key_env="MISSING",
        model="model",
        base_url="https://example.test",
        http_client=make_http_client(lambda request: httpx.Response(200, json={"output": "输出结果"})),
        rate_limiter=RateLimiter(1000, 1000),
    )
    assert await client.generate("提示词") == "输出结果"
