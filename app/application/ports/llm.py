from typing import Protocol

from pydantic import BaseModel, Field

from app.domain.llm import LLMProviderKind, LLMTaskKind


class LLMCompletionRequest(BaseModel):
    prompt: str
    prompt_version: str
    model: str | None = None
    # None routes to the platform default provider.
    provider: LLMProviderKind | None = None
    # Lets a provider adapter pick its task-specific default when model is None.
    task: LLMTaskKind | None = None
    temperature: float | None = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)


class LLMResult(BaseModel):
    text: str
    model: str
    prompt_version: str
    latency_ms: int
    usage_tokens: int | None = None


class LLMClient(Protocol):
    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        raise NotImplementedError
