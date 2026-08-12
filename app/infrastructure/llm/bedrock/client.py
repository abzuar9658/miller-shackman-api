import asyncio
import time
from typing import Any

import boto3

from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.domain.llm import LLMTaskKind


class BedrockLLMClient:
    def __init__(
        self,
        *,
        region: str,
        drafting_model: str,
        classification_model: str,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_session_token: str | None = None,
    ) -> None:
        self._drafting_model = drafting_model
        self._classification_model = classification_model
        kwargs: dict[str, Any] = {}
        if aws_access_key_id:
            kwargs["aws_access_key_id"] = aws_access_key_id
        if aws_secret_access_key:
            kwargs["aws_secret_access_key"] = aws_secret_access_key
        if aws_session_token:
            kwargs["aws_session_token"] = aws_session_token
        self._client = boto3.client("bedrock-runtime", region_name=region, **kwargs)

    def _default_model_for_task(self, task: LLMTaskKind | None) -> str:
        if task is LLMTaskKind.CLASSIFICATION:
            return self._classification_model
        return self._drafting_model

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        model = request.model or self._default_model_for_task(request.task)
        inference_config: dict[str, Any] = {}
        if request.temperature is not None:
            inference_config["temperature"] = request.temperature
        if request.max_tokens is not None:
            inference_config["maxTokens"] = request.max_tokens

        start = time.monotonic()
        response = await asyncio.to_thread(
            self._client.converse,
            modelId=model,
            messages=[{"role": "user", "content": [{"text": request.prompt}]}],
            inferenceConfig=inference_config,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        content_blocks = response.get("output", {}).get("message", {}).get("content", [])
        text = "".join(block.get("text", "") for block in content_blocks)
        usage = response.get("usage", {})
        usage_tokens = usage.get("totalTokens")
        return LLMResult(
            text=text,
            model=model,
            prompt_version=request.prompt_version,
            latency_ms=latency_ms,
            usage_tokens=usage_tokens,
        )

    async def aclose(self) -> None:
        await asyncio.to_thread(self._client.close)
