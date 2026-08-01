import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.application.ports.llm import LLMClient, LLMCompletionRequest, LLMResult
from app.application.services.llm.structured_json import (
    coerce_llm_confidence,
    normalize_llm_json_text,
)
from app.domain.conversations import CrmConversationEvent, HandoffReasonCode
from app.domain.leads import (
    CanonicalLeadRecord,
    LeadStateClassificationOutcome,
    PausedSearchReasonCode,
)

LEAD_STATE_CLASSIFICATION_PROMPT_VERSION = "lead_state_classification:v4"
STRICT_RETRY_PROMPT_VERSION = f"{LEAD_STATE_CLASSIFICATION_PROMPT_VERSION}:strict_retry"
MIN_LEAD_STATE_CLASSIFICATION_CONFIDENCE = 0.70


class LeadStateClassificationStatus(StrEnum):
    CLASSIFIED = "classified"
    REJECTED = "rejected"


class LeadStateClassificationReasonCode(StrEnum):
    INVALID_LLM_RESPONSE = "invalid_llm_response"
    LOW_CONFIDENCE = "low_confidence"
    UNSUPPORTED_OUTCOME = "unsupported_outcome"
    UNSUPPORTED_REASON_CODE = "unsupported_reason_code"


class _LLMLeadStateClassificationOutcome(StrEnum):
    PAUSED_SEARCH = "paused_search"
    DORMANT = "dormant"
    HUMAN_HANDOFF = "human_handoff"
    REVIEW_HOLD = "review_hold"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LeadStateClassificationResult:
    status: LeadStateClassificationStatus
    prompt_version: str
    model: str | None = None
    latency_ms: int | None = None
    usage_tokens: int | None = None
    outcome: LeadStateClassificationOutcome | None = None
    handoff_reason_code: HandoffReasonCode | None = None
    pause_reason_code: PausedSearchReasonCode | None = None
    reengagement_not_before: datetime | None = None
    reengagement_window_label: str | None = None
    confidence: float | None = None
    evidence: tuple[str, ...] = ()
    summary: str | None = None
    prompt_text: str | None = None
    input_context: dict[str, object] = field(default_factory=dict)
    raw_llm_response_text: str | None = None
    parsed_llm_response: dict[str, object] = field(default_factory=dict)
    validation_error: str | None = None
    reasons: tuple[LeadStateClassificationReasonCode, ...] = ()


class _LLMLeadStateClassification(BaseModel):
    outcome: _LLMLeadStateClassificationOutcome
    handoff_reason_code: HandoffReasonCode | None = None
    pause_reason_code: PausedSearchReasonCode | None = None
    reengagement_not_before: str | None = None
    reengagement_window_label: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1, max_length=600)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> object:
        return coerce_llm_confidence(value)

    @model_validator(mode="after")
    def _validate_reason_codes(self) -> "_LLMLeadStateClassification":
        if self.outcome == _LLMLeadStateClassificationOutcome.PAUSED_SEARCH:
            if self.pause_reason_code is None:
                raise ValueError("pause_reason_code is required when outcome is paused_search")
        elif self.pause_reason_code is not None:
            raise ValueError("pause_reason_code is only allowed when outcome is paused_search")

        if self.outcome == _LLMLeadStateClassificationOutcome.HUMAN_HANDOFF:
            if self.handoff_reason_code is None:
                raise ValueError("handoff_reason_code is required when outcome is human_handoff")
        elif self.handoff_reason_code is not None:
            raise ValueError("handoff_reason_code is only allowed when outcome is human_handoff")

        return self


async def classify_lead_from_conversation(
    *,
    lead: CanonicalLeadRecord,
    now: datetime,
    conversation_summary: str | None = None,
    crm_conversation_events: tuple[CrmConversationEvent, ...] = (),
    llm_client: LLMClient,
    dormant_threshold_days: int | None = None,
    model: str | None = None,
    min_confidence: float = MIN_LEAD_STATE_CLASSIFICATION_CONFIDENCE,
) -> LeadStateClassificationResult:
    input_context = _approved_context_payload(
        lead=lead,
        now=now,
        conversation_summary=conversation_summary,
        crm_conversation_events=crm_conversation_events,
        dormant_threshold_days=dormant_threshold_days,
    )
    prompt_text = _build_prompt(input_context)
    llm_result = await _complete_classification_request(
        llm_client=llm_client,
        prompt=prompt_text,
        prompt_version=LEAD_STATE_CLASSIFICATION_PROMPT_VERSION,
        model=model,
    )

    try:
        classification = _parse_classification_result(llm_result.text)
    except ValidationError:
        prompt_text = _build_strict_retry_prompt(input_context)
        retry_result = await _complete_classification_request(
            llm_client=llm_client,
            prompt=prompt_text,
            prompt_version=STRICT_RETRY_PROMPT_VERSION,
            model=model,
        )
        try:
            classification = _parse_classification_result(retry_result.text)
        except ValidationError as exc:
            return _build_rejected_result(
                llm_result=retry_result,
                latency_ms=llm_result.latency_ms + retry_result.latency_ms,
                usage_tokens=_aggregate_usage_tokens(
                    llm_result.usage_tokens,
                    retry_result.usage_tokens,
                ),
                prompt_text=prompt_text,
                input_context=input_context,
                validation_error=str(exc),
            )
        llm_result = _combine_retry_metadata(initial_result=llm_result, retry_result=retry_result)

    parsed_llm_response = _parsed_llm_response_payload(classification)
    reasons = _validation_reasons(classification, min_confidence=min_confidence)
    if reasons:
        return LeadStateClassificationResult(
            status=LeadStateClassificationStatus.REJECTED,
            prompt_version=llm_result.prompt_version,
            model=llm_result.model,
            latency_ms=llm_result.latency_ms,
            usage_tokens=llm_result.usage_tokens,
            prompt_text=prompt_text,
            input_context=input_context,
            raw_llm_response_text=llm_result.text,
            parsed_llm_response=parsed_llm_response,
            reasons=tuple(reasons),
        )
    return LeadStateClassificationResult(
        status=LeadStateClassificationStatus.CLASSIFIED,
        prompt_version=llm_result.prompt_version,
        model=llm_result.model,
        latency_ms=llm_result.latency_ms,
        usage_tokens=llm_result.usage_tokens,
        outcome=_mapped_outcome(classification.outcome),
        handoff_reason_code=classification.handoff_reason_code,
        pause_reason_code=classification.pause_reason_code,
        reengagement_not_before=_parse_iso_datetime(classification.reengagement_not_before),
        reengagement_window_label=_normalized_optional_text(
            classification.reengagement_window_label
        ),
        confidence=classification.confidence,
        evidence=tuple(classification.evidence),
        summary=classification.summary,
        prompt_text=prompt_text,
        input_context=input_context,
        raw_llm_response_text=llm_result.text,
        parsed_llm_response=parsed_llm_response,
    )


async def _complete_classification_request(
    *,
    llm_client: LLMClient,
    prompt: str,
    prompt_version: str,
    model: str | None,
) -> LLMResult:
    return await llm_client.complete(
        LLMCompletionRequest(
            prompt=prompt,
            prompt_version=prompt_version,
            model=model,
            temperature=0.1,
            max_tokens=800,
        )
    )


def _parse_classification_result(raw_text: str) -> _LLMLeadStateClassification:
    return _LLMLeadStateClassification.model_validate_json(normalize_llm_json_text(raw_text))


def _build_rejected_result(
    *,
    llm_result: LLMResult,
    prompt_text: str,
    input_context: dict[str, object],
    latency_ms: int | None = None,
    usage_tokens: int | None = None,
    validation_error: str | None = None,
) -> LeadStateClassificationResult:
    return LeadStateClassificationResult(
        status=LeadStateClassificationStatus.REJECTED,
        prompt_version=llm_result.prompt_version,
        model=llm_result.model,
        latency_ms=llm_result.latency_ms if latency_ms is None else latency_ms,
        usage_tokens=llm_result.usage_tokens if usage_tokens is None else usage_tokens,
        prompt_text=prompt_text,
        input_context=input_context,
        raw_llm_response_text=llm_result.text,
        validation_error=validation_error,
        reasons=(LeadStateClassificationReasonCode.INVALID_LLM_RESPONSE,),
    )


def _combine_retry_metadata(*, initial_result: LLMResult, retry_result: LLMResult) -> LLMResult:
    return LLMResult(
        text=retry_result.text,
        model=retry_result.model,
        prompt_version=retry_result.prompt_version,
        latency_ms=initial_result.latency_ms + retry_result.latency_ms,
        usage_tokens=_aggregate_usage_tokens(
            initial_result.usage_tokens,
            retry_result.usage_tokens,
        ),
    )


def _aggregate_usage_tokens(*usage_tokens: int | None) -> int | None:
    known_usage = [value for value in usage_tokens if value is not None]
    return sum(known_usage) if known_usage else None


def _validation_reasons(
    classification: _LLMLeadStateClassification,
    *,
    min_confidence: float,
) -> list[LeadStateClassificationReasonCode]:
    reasons: list[LeadStateClassificationReasonCode] = []
    if classification.confidence < min_confidence:
        reasons.append(LeadStateClassificationReasonCode.LOW_CONFIDENCE)
    return reasons


def _mapped_outcome(
    value: _LLMLeadStateClassificationOutcome,
) -> LeadStateClassificationOutcome:
    if value == _LLMLeadStateClassificationOutcome.UNKNOWN:
        return LeadStateClassificationOutcome.REVIEW_HOLD
    return LeadStateClassificationOutcome(value.value)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def _normalized_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _build_prompt(payload: dict[str, object]) -> str:
    return f"{_base_prompt_instructions()}\nApproved context: {json.dumps(payload, sort_keys=True)}"


def _build_strict_retry_prompt(payload: dict[str, object]) -> str:
    example = {
        "outcome": "paused_search",
        "handoff_reason_code": None,
        "pause_reason_code": "waiting_for_rates",
        "reengagement_not_before": "2026-09-01",
        "reengagement_window_label": "after summer",
        "confidence": 0.88,
        "evidence": ["Lead said rates are too high", "Lead wants to wait until fall"],
        "summary": "Lead is waiting for lower mortgage rates before buying.",
    }
    return (
        f"{_base_prompt_instructions()}\n"
        "Use these outcome values only: paused_search, dormant, "
        "human_handoff, review_hold, blocked, unknown.\n"
        "Use these handoff_reason_code values only when outcome is human_handoff: "
        f"{', '.join(code.value for code in HandoffReasonCode)}.\n"
        "Use these pause_reason_code values only when outcome is paused_search: "
        f"{', '.join(code.value for code in PausedSearchReasonCode)}.\n"
        "If no route is clearly safe, set outcome to unknown. Unknown maps to review hold.\n"
        "Required JSON schema:\n"
        "- outcome: string enum\n"
        "- handoff_reason_code: string enum or null\n"
        "- pause_reason_code: string enum or null\n"
        "- reengagement_not_before: ISO date string or null\n"
        "- reengagement_window_label: short string or null\n"
        "- confidence: number between 0 and 1\n"
        "- evidence: list of short strings\n"
        "- summary: non-empty string under 600 chars\n"
        "If unsure, still return every required key with your best structured judgment.\n"
        f"Example valid response: {json.dumps(example, sort_keys=True)}\n"
        f"Approved context: {json.dumps(payload, sort_keys=True)}"
    )


def _parsed_llm_response_payload(
    classification: _LLMLeadStateClassification,
) -> dict[str, object]:
    return dict(classification.model_dump(mode="json"))


def _approved_context_payload(
    *,
    lead: CanonicalLeadRecord,
    now: datetime,
    conversation_summary: str | None,
    crm_conversation_events: tuple[CrmConversationEvent, ...],
    dormant_threshold_days: int | None,
) -> dict[str, object]:
    return {
        "task": "classify_lead_state_from_conversation",
        "lead": {
            "lead_type": lead.lead_type.value,
            "lead_stage": lead.lead_stage,
            "lead_source": lead.lead_source,
            "activity_reliability": lead.activity_reliability.value,
            "last_meaningful_communication_at": _iso_datetime(
                lead.last_meaningful_communication_at
            ),
            "last_agent_activity_at": _iso_datetime(lead.last_agent_activity_at),
            "latest_property_event_type": lead.latest_property_event_type.value
            if lead.latest_property_event_type
            else None,
            "latest_property_event_at": _iso_datetime(lead.latest_property_event_at),
            "latest_property_price_band": lead.latest_property_price_band,
            "latest_property_context_present": lead.latest_property_context_present,
        },
        "freshness_context": _freshness_context(
            lead=lead,
            now=now,
            crm_conversation_events=crm_conversation_events,
            dormant_threshold_days=dormant_threshold_days,
        ),
        "conversation_summary": conversation_summary,
        "recent_messages": [
            {
                "direction": event.direction.value if event.direction else None,
                "actor_name": event.actor_name,
                "content": event.content,
                "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
            }
            for event in crm_conversation_events[:20]
            if event.content
        ],
    }


def _freshness_context(
    *,
    lead: CanonicalLeadRecord,
    now: datetime,
    crm_conversation_events: tuple[CrmConversationEvent, ...],
    dormant_threshold_days: int | None,
) -> dict[str, object]:
    latest_message_at = max(
        (event.occurred_at for event in crm_conversation_events),
        default=None,
    )
    latest_inbound_at = _latest_event_at(crm_conversation_events, direction="inbound")
    latest_outbound_at = _latest_event_at(crm_conversation_events, direction="outbound")
    latest_internal_at = _latest_event_at(crm_conversation_events, direction="internal")
    latest_property_event_at = lead.latest_property_event_at
    has_observed_inbound_reply_after_latest_property_event = _has_observed_inbound_reply_after(
        crm_conversation_events,
        latest_property_event_at,
    )
    property_interest_is_stale_by_threshold = _is_stale_by_threshold(
        value=latest_property_event_at,
        now=now,
        dormant_threshold_days=dormant_threshold_days,
    )
    latest_observed_message_older_than_dormant_threshold = _is_stale_by_threshold(
        value=latest_message_at,
        now=now,
        dormant_threshold_days=dormant_threshold_days,
    )
    stale_property_interest_without_observed_reply: bool | None = None
    if (
        property_interest_is_stale_by_threshold is not None
        and has_observed_inbound_reply_after_latest_property_event is not None
    ):
        stale_property_interest_without_observed_reply = (
            property_interest_is_stale_by_threshold is True
            and has_observed_inbound_reply_after_latest_property_event is False
        )
    return {
        "evaluated_at": _iso_datetime(now),
        "dormant_threshold_days": dormant_threshold_days,
        "recent_message_window_count": len(crm_conversation_events),
        "recent_message_window_oldest_at": _iso_datetime(
            min((event.occurred_at for event in crm_conversation_events), default=None)
        ),
        "recent_message_window_newest_at": _iso_datetime(
            max((event.occurred_at for event in crm_conversation_events), default=None)
        ),
        "latest_observed_message_at": _iso_datetime(latest_message_at),
        "latest_observed_inbound_message_at": _iso_datetime(latest_inbound_at),
        "latest_observed_outbound_message_at": _iso_datetime(latest_outbound_at),
        "latest_observed_internal_message_at": _iso_datetime(latest_internal_at),
        "days_since_last_meaningful_communication": _days_since(
            now, lead.last_meaningful_communication_at
        ),
        "days_since_latest_observed_message": _days_since(now, latest_message_at),
        "days_since_latest_property_event": _days_since(now, latest_property_event_at),
        "days_since_latest_observed_inbound_message": _days_since(now, latest_inbound_at),
        "latest_observed_message_older_than_dormant_threshold": (
            latest_observed_message_older_than_dormant_threshold
        ),
        "has_observed_inbound_reply_after_latest_property_event": (
            has_observed_inbound_reply_after_latest_property_event
        ),
        "property_interest_is_stale_by_threshold": property_interest_is_stale_by_threshold,
        "stale_property_interest_without_observed_reply": (
            stale_property_interest_without_observed_reply
        ),
    }


def _latest_event_at(
    crm_conversation_events: tuple[CrmConversationEvent, ...],
    *,
    direction: str,
) -> datetime | None:
    matches = [
        event.occurred_at
        for event in crm_conversation_events
        if event.direction is not None and event.direction.value == direction
    ]
    return max(matches, default=None)


def _has_observed_inbound_reply_after(
    crm_conversation_events: tuple[CrmConversationEvent, ...],
    occurred_after: datetime | None,
) -> bool | None:
    if occurred_after is None:
        return None
    return any(
        event.direction is not None
        and event.direction.value == "inbound"
        and event.occurred_at > occurred_after
        for event in crm_conversation_events
    )


def _is_stale_by_threshold(
    *,
    value: datetime | None,
    now: datetime,
    dormant_threshold_days: int | None,
) -> bool | None:
    if value is None or dormant_threshold_days is None:
        return None
    return now - value >= timedelta(days=dormant_threshold_days)


def _days_since(now: datetime, value: datetime | None) -> int | None:
    if value is None:
        return None
    delta = now - value
    return max(int(delta.total_seconds() // 86400), 0)


def _iso_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _base_prompt_instructions() -> str:
    return (
        "You classify a real estate lead's overall state from conversation context. "
        "Return exactly one valid JSON object and nothing else. "
        "Do not include markdown fences, prose, comments, or trailing text.\n"
        "You must use only the exact enum values provided below. Never invent or shorten "
        "an outcome or reason code.\n"
        "Use freshness_context as authoritative derived timing facts from the lead record "
        "and the recent CRM context window. Historical interest alone is not enough for "
        "human_handoff.\n"
        "Choose exactly one outcome using these rules, in priority order:\n"
        "1. human_handoff — use this only when the lead shows current active buying/selling "
        "interest now, asks for a person now, requests a showing/call now, or asks for "
        "property/pricing/financing/market/legal/tax advice that still needs a human follow-up. "
        "Do not choose human_handoff from a stale property inquiry alone.\n"
        "2. blocked — the lead opted out, is not interested, or should not be nurtured.\n"
        "3. paused_search — the lead is not buying/selling right now but gave a clear reason "
        "such as timing, rates, inventory, renting, financial prep, or life timing.\n"
        "4. dormant — the lead went quiet and there is no known current reason to pause or "
        "handoff. If freshness_context.stale_property_interest_without_observed_reply is "
        "true, prefer dormant unless the context clearly supports blocked, paused_search, "
        "or review_hold. If freshness_context.latest_observed_message_older_than_"
        "dormant_threshold is true, also treat old showing requests, old property "
        "interest, and old internal-only context as historical unless there is a newer "
        "current-engagement signal.\n"
        "5. review_hold — use this only when the conversation clearly requires human review.\n"
        "6. unknown — use this when no route is a clear safe winner. Unknown maps to review hold.\n"
        "If a property inquiry is older than the configured dormant threshold and there is no "
        "observed later inbound reply, treat that inquiry as historical context rather than "
        "current handoff urgency.\n"
        "If the newest observed message in the available context window is older than the "
        "configured dormant threshold, prefer dormant over human_handoff unless the context "
        "clearly supports blocked, paused_search, or review_hold.\n"
        "When stale timing facts strongly support dormant, do not assign low confidence just "
        "because the historical message text sounds urgent or high-intent. In those stale-only "
        "cases, confidence should usually be high unless there is a real newer conflicting "
        "signal in the context.\n"
        "A recent inbound request for help, a fresh showing request, or a fresh ask for advice "
        "can still be human_handoff even if older dormant history exists.\n"
        "For paused_search, pause_reason_code must be exactly one of: "
        f"{', '.join(code.value for code in PausedSearchReasonCode)}.\n"
        "For human_handoff, handoff_reason_code must be exactly one of: "
        f"{', '.join(code.value for code in HandoffReasonCode)}.\n"
        "For outcomes other than paused_search, pause_reason_code must be null.\n"
        "For outcomes other than human_handoff, handoff_reason_code must be null.\n"
        "Set reengagement_not_before to an ISO date only if the lead mentioned a concrete date.\n"
        "Set reengagement_window_label to a short human phrase such as "
        "'after lease ends' or 'next quarter'.\n"
        "evidence is a list of short phrases from the conversation that support your outcome.\n"
        "summary is a concise explanation under 600 characters.\n"
        "Return only JSON with keys: outcome, handoff_reason_code, pause_reason_code, "
        "reengagement_not_before, reengagement_window_label, confidence, evidence, summary."
    )
