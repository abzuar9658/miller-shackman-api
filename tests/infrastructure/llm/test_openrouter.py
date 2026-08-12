import pytest

from app.application.ports.llm import LLMCompletionRequest
from app.domain.llm import LLMTaskKind
from app.infrastructure.llm.openrouter.client import OpenRouterLLMClient


class _FakeUsage:
    total_tokens = 42


class _FakeMessage:
    content = "Hello, lead."


class _FakeChoice:
    message = _FakeMessage()


class _FakeResponse:
    model = ""
    choices = [_FakeChoice()]
    usage = _FakeUsage()


class _CreateRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def __call__(self, **kwargs: object) -> _FakeResponse:
        self.calls.append(kwargs)
        return _FakeResponse()


async def test_complete_returns_llm_result(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OpenRouterLLMClient(api_key="key")
    recorder = _CreateRecorder()
    monkeypatch.setattr(client._client.chat.completions, "create", recorder)

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
    assert recorder.calls[0]["model"] == "openai/gpt-4o-mini"


async def test_complete_uses_task_specific_default_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OpenRouterLLMClient(
        api_key="key",
        model="openai/gpt-4o-mini",
        drafting_model="anthropic/claude-sonnet-4.5",
        classification_model="anthropic/claude-haiku-4.5",
    )
    recorder = _CreateRecorder()
    monkeypatch.setattr(client._client.chat.completions, "create", recorder)

    drafting = await client.complete(
        LLMCompletionRequest(prompt="p", prompt_version="v1", task=LLMTaskKind.DRAFTING)
    )
    classification = await client.complete(
        LLMCompletionRequest(prompt="p", prompt_version="v1", task=LLMTaskKind.CLASSIFICATION)
    )
    untasked = await client.complete(LLMCompletionRequest(prompt="p", prompt_version="v1"))

    assert drafting.model == "anthropic/claude-sonnet-4.5"
    assert classification.model == "anthropic/claude-haiku-4.5"
    assert untasked.model == "openai/gpt-4o-mini"
    assert [call["model"] for call in recorder.calls] == [
        "anthropic/claude-sonnet-4.5",
        "anthropic/claude-haiku-4.5",
        "openai/gpt-4o-mini",
    ]


async def test_complete_explicit_model_overrides_task_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OpenRouterLLMClient(
        api_key="key",
        drafting_model="anthropic/claude-sonnet-4.5",
    )
    recorder = _CreateRecorder()
    monkeypatch.setattr(client._client.chat.completions, "create", recorder)

    result = await client.complete(
        LLMCompletionRequest(
            prompt="p",
            prompt_version="v1",
            model="openai/gpt-4o",
            task=LLMTaskKind.DRAFTING,
        )
    )

    assert result.model == "openai/gpt-4o"
    assert recorder.calls[0]["model"] == "openai/gpt-4o"
