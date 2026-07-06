from typing import Protocol

from pydantic import BaseModel, Field


class LLMCompletionRequest(BaseModel):
    prompt: str
    prompt_version: str
    model: str | None = None
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
