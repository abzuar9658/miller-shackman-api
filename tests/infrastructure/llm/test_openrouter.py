import pytest

from app.application.ports.llm import LLMCompletionRequest
from app.infrastructure.llm.openrouter.client import OpenRouterLLMClient


class _FakeUsage:
    total_tokens = 42


class _FakeMessage:
    content = "Hello, lead."


class _FakeChoice:
    message = _FakeMessage()


class _FakeResponse:
    model = "openai/gpt-4o-mini"
    choices = [_FakeChoice()]
    usage = _FakeUsage()


async def _fake_create(**kwargs: object) -> _FakeResponse:
    return _FakeResponse()


async def test_complete_returns_llm_result(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OpenRouterLLMClient(api_key="key")
    monkeypatch.setattr(client._client.chat.completions, "create", _fake_create)

    request = LLMCompletionRequest(
        prompt="Say hello",
        prompt_version="v1",
    )
    result = await client.complete(request)

    assert result.text == "Hello, lead."
    assert result.model == "openai/gpt-4o-mini"
    assert result.prompt_version == "v1"
    assert result.usage_tokens == 42
    assert result.latency_ms >= 0
