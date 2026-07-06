import time

from openai import AsyncOpenAI

from app.application.ports.llm import LLMCompletionRequest, LLMResult


class OpenRouterLLMClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        model: str = "openai/gpt-4o-mini",
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        start = time.monotonic()
        response = await self._client.chat.completions.create(
            model=request.model or self._model,
            messages=[{"role": "user", "content": request.prompt}],
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        text = response.choices[0].message.content or ""
        usage_tokens = response.usage.total_tokens if response.usage else None
        return LLMResult(
            text=text,
            model=response.model or request.model or self._model,
            prompt_version=request.prompt_version,
            latency_ms=latency_ms,
            usage_tokens=usage_tokens,
        )
