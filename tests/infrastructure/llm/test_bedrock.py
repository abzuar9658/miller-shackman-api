from typing import Any

import pytest

from app.application.ports.llm import LLMCompletionRequest
from app.domain.llm import LLMTaskKind
from app.infrastructure.llm.bedrock.client import BedrockLLMClient

_RESPONSE: dict[str, Any] = {
    "output": {"message": {"content": [{"text": "Hello, "}, {"text": "lead."}]}},
    "usage": {"inputTokens": 10, "outputTokens": 32, "totalTokens": 42},
}


class _ConverseRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return _RESPONSE


def _client() -> BedrockLLMClient:
    return BedrockLLMClient(
        region="us-east-1",
        drafting_model="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        classification_model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        aws_access_key_id="key",
        aws_secret_access_key="secret",
    )


async def test_complete_returns_llm_result(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    recorder = _ConverseRecorder()
    monkeypatch.setattr(client._client, "converse", recorder)

    result = await client.complete(
        LLMCompletionRequest(
            prompt="Say hello",
            prompt_version="v1",
            temperature=0.4,
            max_tokens=700,
        )
    )

    assert result.text == "Hello, lead."
    assert result.model == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert result.prompt_version == "v1"
    assert result.usage_tokens == 42
    assert result.latency_ms >= 0
    call = recorder.calls[0]
    assert call["modelId"] == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert call["messages"] == [{"role": "user", "content": [{"text": "Say hello"}]}]
    assert call["inferenceConfig"] == {"temperature": 0.4, "maxTokens": 700}


async def test_complete_uses_task_specific_default_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    recorder = _ConverseRecorder()
    monkeypatch.setattr(client._client, "converse", recorder)

    drafting = await client.complete(
        LLMCompletionRequest(prompt="p", prompt_version="v1", task=LLMTaskKind.DRAFTING)
    )
    classification = await client.complete(
        LLMCompletionRequest(prompt="p", prompt_version="v1", task=LLMTaskKind.CLASSIFICATION)
    )
    untasked = await client.complete(LLMCompletionRequest(prompt="p", prompt_version="v1"))

    assert drafting.model == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert classification.model == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert untasked.model == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


async def test_complete_explicit_model_overrides_task_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    recorder = _ConverseRecorder()
    monkeypatch.setattr(client._client, "converse", recorder)

    result = await client.complete(
        LLMCompletionRequest(
            prompt="p",
            prompt_version="v1",
            model="us.amazon.nova-pro-v1:0",
            task=LLMTaskKind.CLASSIFICATION,
        )
    )

    assert result.model == "us.amazon.nova-pro-v1:0"
    assert recorder.calls[0]["modelId"] == "us.amazon.nova-pro-v1:0"


async def test_complete_omits_unset_inference_config_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    recorder = _ConverseRecorder()
    monkeypatch.setattr(client._client, "converse", recorder)

    await client.complete(
        LLMCompletionRequest(
            prompt="p",
            prompt_version="v1",
            temperature=None,
            max_tokens=None,
        )
    )

    assert recorder.calls[0]["inferenceConfig"] == {}
