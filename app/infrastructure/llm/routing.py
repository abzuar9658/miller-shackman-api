from app.application.ports.llm import LLMClient, LLMCompletionRequest, LLMResult
from app.domain.llm import LLMProviderKind


class RoutingLLMClient:
    """Dispatches completion requests to a provider-specific client.

    A request without an explicit provider goes to the platform default.
    A request for a provider with no configured client fails loudly —
    there is no silent fallback to another provider.
    """

    def __init__(
        self,
        *,
        default_provider: LLMProviderKind,
        clients: dict[LLMProviderKind, LLMClient],
    ) -> None:
        if default_provider not in clients:
            raise ValueError(
                f"No LLM client configured for default provider: {default_provider.value}"
            )
        self._default_provider = default_provider
        self._clients = clients

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        provider = request.provider or self._default_provider
        client = self._clients.get(provider)
        if client is None:
            raise ValueError(f"No LLM client configured for provider: {provider.value}")
        return await client.complete(request)

    async def aclose(self) -> None:
        for client in self._clients.values():
            aclose = getattr(client, "aclose", None)
            if aclose is not None:
                await aclose()
