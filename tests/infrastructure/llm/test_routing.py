import pytest

from app.application.ports.llm import LLMClient, LLMCompletionRequest, LLMResult
from app.domain.llm import LLMProviderKind
from app.infrastructure.llm.routing import RoutingLLMClient


class _FakeLLMClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.requests: list[LLMCompletionRequest] = []
        self.closed = False

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        return LLMResult(
            text=f"from {self.name}",
            model=self.name,
            prompt_version=request.prompt_version,
            latency_ms=1,
        )

    async def aclose(self) -> None:
        self.closed = True


def _request(provider: LLMProviderKind | None = None) -> LLMCompletionRequest:
    return LLMCompletionRequest(prompt="p", prompt_version="v1", provider=provider)


async def test_routes_to_default_provider_when_unspecified() -> None:
    openrouter = _FakeLLMClient("openrouter")
    bedrock = _FakeLLMClient("bedrock")
    router = RoutingLLMClient(
        default_provider=LLMProviderKind.OPENROUTER,
        clients={
            LLMProviderKind.OPENROUTER: openrouter,
            LLMProviderKind.BEDROCK: bedrock,
        },
    )

    result = await router.complete(_request())

    assert result.text == "from openrouter"
    assert len(openrouter.requests) == 1
    assert len(bedrock.requests) == 0


async def test_routes_to_requested_provider() -> None:
    openrouter = _FakeLLMClient("openrouter")
    bedrock = _FakeLLMClient("bedrock")
    router = RoutingLLMClient(
        default_provider=LLMProviderKind.OPENROUTER,
        clients={
            LLMProviderKind.OPENROUTER: openrouter,
            LLMProviderKind.BEDROCK: bedrock,
        },
    )

    result = await router.complete(_request(provider=LLMProviderKind.BEDROCK))

    assert result.text == "from bedrock"
    assert len(bedrock.requests) == 1
    assert len(openrouter.requests) == 0


async def test_unconfigured_provider_fails_loudly() -> None:
    openrouter = _FakeLLMClient("openrouter")
    router = RoutingLLMClient(
        default_provider=LLMProviderKind.OPENROUTER,
        clients={LLMProviderKind.OPENROUTER: openrouter},
    )

    with pytest.raises(ValueError, match="bedrock"):
        await router.complete(_request(provider=LLMProviderKind.BEDROCK))
    assert len(openrouter.requests) == 0


def test_default_provider_must_have_a_client() -> None:
    clients: dict[LLMProviderKind, LLMClient] = {
        LLMProviderKind.OPENROUTER: _FakeLLMClient("openrouter")
    }
    with pytest.raises(ValueError, match="bedrock"):
        RoutingLLMClient(default_provider=LLMProviderKind.BEDROCK, clients=clients)


async def test_aclose_closes_all_clients() -> None:
    openrouter = _FakeLLMClient("openrouter")
    bedrock = _FakeLLMClient("bedrock")
    router = RoutingLLMClient(
        default_provider=LLMProviderKind.OPENROUTER,
        clients={
            LLMProviderKind.OPENROUTER: openrouter,
            LLMProviderKind.BEDROCK: bedrock,
        },
    )

    await router.aclose()

    assert openrouter.closed is True
    assert bedrock.closed is True
