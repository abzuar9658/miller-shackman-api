"""Compare production and stricter inbound reply prompts against LLM output.

Usage:
    arch -arm64 uv run python scripts/debug_inbound_reply_classification.py
    arch -arm64 uv run python scripts/debug_inbound_reply_classification.py --mode live
    arch -arm64 uv run python scripts/debug_inbound_reply_classification.py \
        --mode live --model openai/gpt-4o --show-prompt
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.application.ports.llm import LLMClient, LLMCompletionRequest, LLMResult
from app.application.services.llm.reply_classification import (  # noqa: PLC2701
    INBOUND_REPLY_CLASSIFICATION_PROMPT_VERSION,
    _build_prompt,
    _build_strict_retry_prompt,
    _LLMReplyClassification,
    _normalize_classification_json_text,
)
from app.core.config import get_settings
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.infrastructure.providers import build_llm_client

DEFAULT_MESSAGE = "Can someone call me today?"
STRICT_PROMPT_VERSION = f"{INBOUND_REPLY_CLASSIFICATION_PROMPT_VERSION}:strict_debug"


@dataclass(frozen=True)
class PromptScenario:
    label: str
    prompt_version: str
    prompt: str


@dataclass(frozen=True)
class OutputInspection:
    normalized_text: str
    validation_ok: bool
    validation_error: str | None
    parsed: dict[str, object] | None


@dataclass(frozen=True)
class PromptRunResult:
    scenario: PromptScenario
    raw_text: str
    model: str
    latency_ms: int
    usage_tokens: int | None
    inspection: OutputInspection


class _StubLLMClient:
    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        text = (
            json.dumps(
                {
                    "intent": "human_requested",
                    "confidence": 0.93,
                    "asks_for_human": True,
                    "shows_buying_interest": False,
                    "shows_selling_interest": False,
                    "asks_property_or_advice": False,
                    "opt_out_detected": False,
                    "summary_text": "Lead asked for a phone call today.",
                    "preferences": {"timeline": "today"},
                }
            )
            if request.prompt_version == STRICT_PROMPT_VERSION
            else json.dumps(
                {
                    "intent": "human_requested",
                    "confidence": 0.93,
                    "handoff_required": True,
                    "handoff_reason": "human_requested",
                    "summary_text": "Lead asked for a phone call today.",
                    "preferences": {"timeline": "today"},
                }
            )
        )
        return LLMResult(
            text=text,
            model=request.model or "stub",
            prompt_version=request.prompt_version,
            latency_ms=1,
            usage_tokens=42,
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect raw LLM output for inbound reply classification prompts."
    )
    parser.add_argument(
        "--message",
        default=DEFAULT_MESSAGE,
        help="Inbound lead message to classify.",
    )
    parser.add_argument(
        "--mode",
        choices=("live", "stub"),
        default="stub",
        help="Use the configured OpenRouter client or a local stub response.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the model for this run without changing app configuration.",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print the exact prompt text before each request.",
    )
    parser.add_argument(
        "--prod-only",
        action="store_true",
        help="Run only the current production prompt.",
    )
    return parser.parse_args(argv)


def _build_lead(now: datetime) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=uuid4(),
        lead_id=uuid4(),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="123",
        facts_derived_at=now,
        source_payload_version="debug:v1",
        lead_source="website",
        lead_stage="long_term_nurture",
    )


def _build_strict_prompt(*, lead: CanonicalLeadRecord, inbound_text: str) -> str:
    return _build_strict_retry_prompt(lead=lead, inbound_text=inbound_text)


def _build_scenarios(
    *,
    lead: CanonicalLeadRecord,
    inbound_text: str,
    prod_only: bool,
) -> tuple[PromptScenario, ...]:
    scenarios = [
        PromptScenario(
            label="production_prompt",
            prompt_version=INBOUND_REPLY_CLASSIFICATION_PROMPT_VERSION,
            prompt=_build_prompt(lead=lead, inbound_text=inbound_text),
        )
    ]
    if not prod_only:
        scenarios.append(
            PromptScenario(
                label="strict_debug_prompt",
                prompt_version=STRICT_PROMPT_VERSION,
                prompt=_build_strict_prompt(lead=lead, inbound_text=inbound_text),
            )
        )
    return tuple(scenarios)


def inspect_llm_output(raw_text: str) -> OutputInspection:
    normalized_text = _normalize_classification_json_text(raw_text)
    try:
        classification = _LLMReplyClassification.model_validate_json(normalized_text)
    except ValidationError as exc:
        return OutputInspection(
            normalized_text=normalized_text,
            validation_ok=False,
            validation_error=exc.json(include_url=False),
            parsed=None,
        )
    return OutputInspection(
        normalized_text=normalized_text,
        validation_ok=True,
        validation_error=None,
        parsed=cast(dict[str, object], classification.model_dump()),
    )


async def _run_scenario(
    *,
    llm_client: LLMClient,
    scenario: PromptScenario,
    model: str | None,
) -> PromptRunResult:
    llm_result = await llm_client.complete(
        LLMCompletionRequest(
            prompt=scenario.prompt,
            prompt_version=scenario.prompt_version,
            model=model,
            temperature=0.1,
            max_tokens=500,
        )
    )
    return PromptRunResult(
        scenario=scenario,
        raw_text=llm_result.text,
        model=llm_result.model,
        latency_ms=llm_result.latency_ms,
        usage_tokens=llm_result.usage_tokens,
        inspection=inspect_llm_output(llm_result.text),
    )


def _print_run(result: PromptRunResult, *, show_prompt: bool) -> None:
    print("=" * 80)
    print(f"Scenario: {result.scenario.label}")
    print(f"Prompt version: {result.scenario.prompt_version}")
    print(f"Model: {result.model}")
    print(f"Latency ms: {result.latency_ms}")
    print(f"Usage tokens: {result.usage_tokens}")
    if show_prompt:
        print("Prompt:")
        print(result.scenario.prompt)
    print("Raw response:")
    print(result.raw_text or "<empty>")
    print("Normalized JSON candidate:")
    print(result.inspection.normalized_text or "<empty>")
    print(f"Validation: {'PASS' if result.inspection.validation_ok else 'FAIL'}")
    if result.inspection.parsed is not None:
        print("Parsed object:")
        print(json.dumps(result.inspection.parsed, indent=2, sort_keys=True))
    if result.inspection.validation_error is not None:
        print("Validation error:")
        print(result.inspection.validation_error)


async def _main() -> int:
    args = parse_args()
    settings = get_settings()
    llm = build_llm_client(settings) if args.mode == "live" else _StubLLMClient()
    lead = _build_lead(datetime.now(UTC))
    scenarios = _build_scenarios(
        lead=lead,
        inbound_text=args.message,
        prod_only=args.prod_only,
    )
    effective_model = args.model or (settings.openrouter_model if args.mode == "live" else "stub")
    print(f"Mode: {args.mode}")
    print(f"Requested model: {effective_model}")
    print(f"Inbound message: {args.message}")
    for scenario in scenarios:
        result = await _run_scenario(llm_client=llm, scenario=scenario, model=args.model)
        _print_run(result, show_prompt=args.show_prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))