"""Journey-aware reply route classification.

For every inbound reply the model is shown the lead's *current* journey — the
dormant cadence and its next planned step, or the exact paused-search track
with its re-engagement date and the step that had just run — and asked one
question: should the lead continue along the planned path, go to a human, or
be suppressed? The model scores all three options with distinct percentages
summing to 100; deterministic rules in ``domain.conversations.reply_routing``
decide from the winner.
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.application.ports.llm import LLMClient, LLMCompletionRequest
from app.application.services.llm.structured_json import (
    coerce_llm_confidence,
    normalize_llm_json_text,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.conversations.reply_routing import ReplyRouteOption
from app.domain.llm import LLMProviderKind

REPLY_ROUTE_CLASSIFICATION_PROMPT_VERSION = "reply_route_classification/v1"
STRICT_RETRY_PROMPT_VERSION = f"{REPLY_ROUTE_CLASSIFICATION_PROMPT_VERSION}:strict_retry"


class ReplyRouteJourneyKind(StrEnum):
    DORMANT = "dormant"
    PAUSED_SEARCH = "paused_search"


@dataclass(frozen=True)
class ReplyRouteJourneyContext:
    """The current journey snapshot shown to the classifier."""

    journey: ReplyRouteJourneyKind
    # Paused search: the exact track and its timing contract.
    track_key: str | None = None
    track_name: str | None = None
    reengagement_not_before: date | None = None
    reengagement_window_label: str | None = None
    # The step that had just run when the reply arrived, and the next touch.
    last_completed_step_goal: str | None = None
    next_step_goal: str | None = None
    next_touch_scheduled_for: str | None = None  # ISO datetime, display-ready


@dataclass(frozen=True)
class ReplyRouteClassificationResult:
    status: "ReplyRouteClassificationStatus"
    prompt_version: str
    workspace_id: WorkspaceId
    lead_id: LeadId
    model: str | None = None
    latency_ms: int | None = None
    usage_tokens: int | None = None
    decision: ReplyRouteOption | None = None
    option_percentages: dict[ReplyRouteOption, int] = field(default_factory=dict)
    adjusted_reengagement_date: date | None = None
    adjusted_reengagement_window_label: str | None = None
    confidence: float | None = None
    summary: str | None = None
    prompt_text: str | None = None
    input_context: dict[str, object] = field(default_factory=dict)
    raw_llm_response_text: str | None = None
    parsed_llm_response: dict[str, object] = field(default_factory=dict)
    validation_error: str | None = None


class ReplyRouteClassificationStatus(StrEnum):
    CLASSIFIED = "classified"
    REJECTED = "rejected"


class _LLMReplyRouteClassification(BaseModel):
    decision: ReplyRouteOption
    continue_percent: int = Field(ge=0, le=100)
    human_handoff_percent: int = Field(ge=0, le=100)
    suppressed_percent: int = Field(ge=0, le=100)
    adjusted_reengagement_date: str | None = None
    adjusted_reengagement_window_label: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str = Field(min_length=1, max_length=600)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> object:
        return coerce_llm_confidence(value)

    @field_validator("adjusted_reengagement_date")
    @classmethod
    def _validate_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            date.fromisoformat(value.strip())
        except (ValueError, AttributeError) as exc:
            raise ValueError(
                "adjusted_reengagement_date must be an ISO date (YYYY-MM-DD)"
            ) from exc
        return value.strip()

    @model_validator(mode="after")
    def _validate_percentages(self) -> "_LLMReplyRouteClassification":
        percentages = (
            self.continue_percent,
            self.human_handoff_percent,
            self.suppressed_percent,
        )
        if sum(percentages) != 100:
            raise ValueError("option percentages must sum to exactly 100")
        if len(set(percentages)) != 3:
            raise ValueError("option percentages must all be different; no ties allowed")
        winner = max(
            (
                (ReplyRouteOption.CONTINUE, self.continue_percent),
                (ReplyRouteOption.HUMAN_HANDOFF, self.human_handoff_percent),
                (ReplyRouteOption.SUPPRESSED, self.suppressed_percent),
            ),
            key=lambda item: item[1],
        )[0]
        if self.decision is not winner:
            raise ValueError("decision must be the option with the highest percentage")
        if self.decision is not ReplyRouteOption.CONTINUE and (
            self.adjusted_reengagement_date is not None
            or self.adjusted_reengagement_window_label is not None
        ):
            raise ValueError("adjusted re-engagement is only allowed when continuing")
        return self



def _base_prompt_instructions(*, journey: ReplyRouteJourneyKind) -> str:
    paused_search_timing_rule = (
        "If, and only if, the reply states a concrete date or timeframe when the lead "
        "will be ready (e.g. 'November', 'early next year', 'after my lease ends in May'), "
        "return it as adjusted_reengagement_date (ISO date, YYYY-MM-DD, the earliest date "
        "in a stated window) and a human-readable adjusted_reengagement_window_label. "
        "If the reply has no concrete timing, return null for both.\n"
        if journey is ReplyRouteJourneyKind.PAUSED_SEARCH
        else "Always return null for adjusted_reengagement_date and "
        "adjusted_reengagement_window_label.\n"
    )
    return (
        "You decide what happens next when a real estate lead replies to an automated "
        "nurture message. You are shown the lead's current journey — the plan that is "
        "already running — the latest reply, and the recent conversation.\n"
        "Choose exactly one of three options:\n"
        "1. continue — the reply is consistent with the current plan: the lead is still "
        "waiting, gave a neutral or uncertain update, or simply responded. The planned "
        "journey continues unchanged.\n"
        "2. human_handoff — the reply shows the lead wants to act now (wants listings, a "
        "showing, to make an offer, asks for pricing/financing/market advice) or asks "
        "for a person. Waiting longer or being unsure is NEVER a handoff.\n"
        "3. suppressed — the lead wants contact to stop or is no longer interested at all.\n"
        "Score every option with continue_percent, human_handoff_percent, and "
        "suppressed_percent: integers from 0 to 100 that sum to exactly 100 and are all "
        "different from each other — ties are not allowed. decision must be the option "
        "with the highest percentage.\n"
        f"{paused_search_timing_rule}"
        "Return only JSON with keys: decision, continue_percent, human_handoff_percent, "
        "suppressed_percent, adjusted_reengagement_date, adjusted_reengagement_window_label, "
        "confidence, summary.\n"
        "confidence must be a number from 0 to 1.\n"
        "summary must be a concise explanation under 600 characters."
    )


def _approved_context_payload(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    channel: ContactChannel,
    inbound_text: str,
    journey: ReplyRouteJourneyContext,
    conversation_summary: str | None,
    recent_events: tuple[dict[str, object], ...],
    now: datetime,
) -> dict[str, object]:
    journey_payload: dict[str, object] = {"kind": journey.journey.value}
    if journey.journey is ReplyRouteJourneyKind.PAUSED_SEARCH:
        journey_payload.update(
            {
                "track_key": journey.track_key,
                "track_name": journey.track_name,
                "reengagement_not_before": (
                    journey.reengagement_not_before.isoformat()
                    if journey.reengagement_not_before is not None
                    else None
                ),
                "reengagement_window_label": journey.reengagement_window_label,
                "last_completed_step_goal": journey.last_completed_step_goal,
                "next_touch_scheduled_for": journey.next_touch_scheduled_for,
            }
        )
    else:
        journey_payload.update(
            {
                "next_step_goal": journey.next_step_goal,
                "next_touch_scheduled_for": journey.next_touch_scheduled_for,
            }
        )
    return {
        "task": "route_inbound_reply_for_current_journey",
        "workspace_id": str(workspace_id),
        "lead_id": str(lead_id),
        "channel": channel.value,
        "current_journey": journey_payload,
        "conversation_summary": conversation_summary,
        "recent_conversation": list(recent_events),
        "latest_reply": inbound_text,
        # Lets the model resolve relative timing ("next year", "in December").
        "today": now.date().isoformat(),
    }


def _build_prompt(payload: dict[str, object], *, journey: ReplyRouteJourneyKind) -> str:
    return (
        f"{_base_prompt_instructions(journey=journey)}\n"
        f"Approved context: {json.dumps(payload, sort_keys=True)}"
    )


def _build_strict_retry_prompt(
    payload: dict[str, object], *, journey: ReplyRouteJourneyKind
) -> str:
    example = {
        "decision": "continue",
        "continue_percent": 70,
        "human_handoff_percent": 20,
        "suppressed_percent": 10,
        "adjusted_reengagement_date": None,
        "adjusted_reengagement_window_label": None,
        "confidence": 0.9,
        "summary": "Lead confirmed they are still waiting; the current plan stands.",
    }
    return (
        f"{_base_prompt_instructions(journey=journey)}\n"
        "Required JSON schema:\n"
        "- decision: one of continue, human_handoff, suppressed\n"
        "- continue_percent, human_handoff_percent, suppressed_percent: integers 0-100, "
        "sum exactly 100, all three different\n"
        "- adjusted_reengagement_date: ISO date string or null\n"
        "- adjusted_reengagement_window_label: string or null\n"
        "- confidence: number between 0 and 1\n"
        "- summary: non-empty string under 600 characters\n"
        "If unsure, still return every required key with your best structured judgment.\n"
        f"Example valid response: {json.dumps(example, sort_keys=True)}\n"
        f"Approved context: {json.dumps(payload, sort_keys=True)}"
    )


def _parse_classification_result(raw_text: str) -> _LLMReplyRouteClassification:
    return _LLMReplyRouteClassification.model_validate_json(normalize_llm_json_text(raw_text))


async def classify_reply_route(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    channel: ContactChannel,
    inbound_text: str,
    journey: ReplyRouteJourneyContext,
    now: datetime,
    conversation_summary: str | None = None,
    recent_events: tuple[dict[str, object], ...] = (),
    llm_client: LLMClient,
    model: str | None = None,
    provider: LLMProviderKind | None = None,
) -> ReplyRouteClassificationResult:
    input_context = _approved_context_payload(
        workspace_id=workspace_id,
        lead_id=lead_id,
        channel=channel,
        inbound_text=inbound_text,
        journey=journey,
        conversation_summary=conversation_summary,
        recent_events=recent_events,
        now=now,
    )
    prompt_text = _build_prompt(input_context, journey=journey.journey)
    llm_result = await llm_client.complete(
        LLMCompletionRequest(
            prompt=prompt_text,
            prompt_version=REPLY_ROUTE_CLASSIFICATION_PROMPT_VERSION,
            model=model,
            provider=provider,
        )
    )

    try:
        classification = _parse_classification_result(llm_result.text)
    except ValidationError:
        prompt_text = _build_strict_retry_prompt(input_context, journey=journey.journey)
        retry_result = await llm_client.complete(
            LLMCompletionRequest(
                prompt=prompt_text,
                prompt_version=STRICT_RETRY_PROMPT_VERSION,
                model=model,
                provider=provider,
            )
        )
        try:
            classification = _parse_classification_result(retry_result.text)
        except ValidationError as exc:
            return ReplyRouteClassificationResult(
                status=ReplyRouteClassificationStatus.REJECTED,
                prompt_version=retry_result.prompt_version,
                workspace_id=workspace_id,
                lead_id=lead_id,
                model=retry_result.model,
                latency_ms=(llm_result.latency_ms or 0) + (retry_result.latency_ms or 0),
                usage_tokens=_aggregate_usage_tokens(
                    llm_result.usage_tokens, retry_result.usage_tokens
                ),
                prompt_text=prompt_text,
                input_context=input_context,
                raw_llm_response_text=retry_result.text,
                validation_error=str(exc),
            )
        llm_result = retry_result

    parsed = classification.model_dump(mode="json")
    return ReplyRouteClassificationResult(
        status=ReplyRouteClassificationStatus.CLASSIFIED,
        prompt_version=llm_result.prompt_version,
        workspace_id=workspace_id,
        lead_id=lead_id,
        model=llm_result.model,
        latency_ms=llm_result.latency_ms,
        usage_tokens=llm_result.usage_tokens,
        decision=classification.decision,
        option_percentages={
            ReplyRouteOption.CONTINUE: classification.continue_percent,
            ReplyRouteOption.HUMAN_HANDOFF: classification.human_handoff_percent,
            ReplyRouteOption.SUPPRESSED: classification.suppressed_percent,
        },
        adjusted_reengagement_date=(
            date.fromisoformat(classification.adjusted_reengagement_date)
            if classification.adjusted_reengagement_date
            else None
        ),
        adjusted_reengagement_window_label=classification.adjusted_reengagement_window_label,
        confidence=classification.confidence,
        summary=classification.summary,
        prompt_text=prompt_text,
        input_context=input_context,
        raw_llm_response_text=llm_result.text,
        parsed_llm_response=parsed,
    )


def _aggregate_usage_tokens(*usage_tokens: int | None) -> int | None:
    present = [tokens for tokens in usage_tokens if tokens is not None]
    if not present:
        return None
    return sum(present)
