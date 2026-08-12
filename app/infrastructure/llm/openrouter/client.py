import time

from openai import AsyncOpenAI

from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.domain.llm import LLMTaskKind


class OpenRouterLLMClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        model: str = "openai/gpt-4o-mini",
        drafting_model: str | None = None,
        classification_model: str | None = None,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._drafting_model = drafting_model or model
        self._classification_model = classification_model or model

    def _default_model_for_task(self, task: LLMTaskKind | None) -> str:
        if task is LLMTaskKind.DRAFTING:
            return self._drafting_model
        if task is LLMTaskKind.CLASSIFICATION:
            return self._classification_model
        return self._model

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        model = request.model or self._default_model_for_task(request.task)
        start = time.monotonic()
        response = await self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": request.prompt}],
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        text = response.choices[0].message.content or ""
        usage_tokens = response.usage.total_tokens if response.usage else None
        return LLMResult(
            text=text,
            model=response.model or model,
            prompt_version=request.prompt_version,
            latency_ms=latency_ms,
            usage_tokens=usage_tokens,
        )

    async def aclose(self) -> None:
        await self._client.close()
