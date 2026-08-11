import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.application.ports.llm import LLMClient, LLMCompletionRequest, LLMResult
from app.application.services.llm.structured_json import (
    coerce_llm_confidence,
    normalize_llm_json_text,
)
from app.domain.campaigns import PausedSearchTrackCatalogEntry
from app.domain.conversations import (
    CrmConversationEvent,
    CrmConversationEventDirection,
    HandoffReasonCode,
)
from app.domain.leads import (
    CanonicalLeadRecord,
    LeadStateClassificationOutcome,
    PausedSearchTrackSelectionStatus,
)

LEAD_STATE_CLASSIFICATION_PROMPT_VERSION = "lead_state_classification:v6"
STRICT_RETRY_PROMPT_VERSION = f"{LEAD_STATE_CLASSIFICATION_PROMPT_VERSION}:strict_retry"
MIN_LEAD_STATE_CLASSIFICATION_CONFIDENCE = 0.70


class LeadStateClassificationStatus(StrEnum):
    CLASSIFIED = "classified"
    REJECTED = "rejected"


class LeadStateClassificationReasonCode(StrEnum):
    INVALID_LLM_RESPONSE = "invalid_llm_response"
    LOW_CONFIDENCE = "low_confidence"
    UNSUPPORTED_OUTCOME = "unsupported_outcome"
    INVALID_TRACK_SELECTION = "invalid_track_selection"


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
    selected_track_key: str | None = None
    track_selection_status: PausedSearchTrackSelectionStatus | None = None
    track_version_id: UUID | None = None
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
    selected_track_key: str | None = None
    track_selection_status: PausedSearchTrackSelectionStatus | None = None
    reengagement_not_before: str | None = None
    reengagement_window_label: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    evidence_event_ids: list[str] = Field(default_factory=list)
    lead_goal: str | None = None
    last_known_intent: str | None = None
    intent_freshness: str | None = None
    conversation_waiting_on: str | None = None
    summary: str = Field(min_length=1, max_length=600)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> object:
        return coerce_llm_confidence(value)

    @model_validator(mode="after")
    def _validate_reason_codes(self) -> "_LLMLeadStateClassification":
        if self.outcome == _LLMLeadStateClassificationOutcome.PAUSED_SEARCH:
            if self.track_selection_status is None:
                raise ValueError("track_selection_status is required when outcome is paused_search")
            if (
                self.track_selection_status is PausedSearchTrackSelectionStatus.SELECTED
                and not self.selected_track_key
            ):
                raise ValueError("selected_track_key is required when a track is selected")
            if (
                self.track_selection_status is not PausedSearchTrackSelectionStatus.SELECTED
                and self.selected_track_key is not None
            ):
                raise ValueError("selected_track_key is only allowed for selected status")
        elif self.selected_track_key is not None or self.track_selection_status is not None:
            raise ValueError("track selection is only allowed when outcome is paused_search")

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
    paused_search_catalog: tuple[PausedSearchTrackCatalogEntry, ...] = (),
) -> LeadStateClassificationResult:
    normalized_events = _normalize_conversation_events(crm_conversation_events)
    input_context = _approved_context_payload(
        lead=lead,
        now=now,
        conversation_summary=conversation_summary,
        crm_conversation_events=normalized_events,
        dormant_threshold_days=dormant_threshold_days,
        paused_search_catalog=paused_search_catalog,
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
    reasons = _validation_reasons(
        classification,
        min_confidence=min_confidence,
        catalog_keys={entry.track_key for entry in paused_search_catalog},
    )
    classification, policy_trace = _apply_route_policy(
        classification=classification,
        input_context=input_context,
    )
    input_context["classifier_policy"] = policy_trace
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
            outcome=_mapped_outcome(classification.outcome),
            selected_track_key=classification.selected_track_key,
            track_selection_status=classification.track_selection_status,
            track_version_id=_selected_track_version_id(classification, paused_search_catalog),
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
        selected_track_key=classification.selected_track_key,
        track_selection_status=classification.track_selection_status,
        track_version_id=_selected_track_version_id(classification, paused_search_catalog),
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
    catalog_keys: set[str],
) -> list[LeadStateClassificationReasonCode]:
    reasons: list[LeadStateClassificationReasonCode] = []
    if classification.confidence < min_confidence:
        reasons.append(LeadStateClassificationReasonCode.LOW_CONFIDENCE)
    if (
        classification.track_selection_status is PausedSearchTrackSelectionStatus.SELECTED
        and classification.selected_track_key not in catalog_keys
    ):
        reasons.append(LeadStateClassificationReasonCode.INVALID_TRACK_SELECTION)
    return reasons


def _selected_track_version_id(
    classification: _LLMLeadStateClassification,
    catalog: tuple[PausedSearchTrackCatalogEntry, ...],
) -> UUID | None:
    if classification.track_selection_status is not PausedSearchTrackSelectionStatus.SELECTED:
        return None
    return next(
        (
            entry.track_version_id
            for entry in catalog
            if entry.track_key == classification.selected_track_key
        ),
        None,
    )


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
        "selected_track_key": "waiting-for-rates",
        "track_selection_status": "selected",
        "reengagement_not_before": "2026-09-01",
        "reengagement_window_label": "after summer",
        "confidence": 0.88,
        "evidence": ["Lead said rates are too high", "Lead wants to wait until fall"],
        "evidence_event_ids": ["text_message:123"],
        "lead_goal": "buyer",
        "last_known_intent": "wants to buy after rates improve",
        "intent_freshness": "current",
        "conversation_waiting_on": "lead",
        "summary": "Lead is waiting for lower mortgage rates before buying.",
    }
    return (
        f"{_base_prompt_instructions()}\n"
        "Use these outcome values only: paused_search, dormant, "
        "human_handoff, review_hold, blocked, unknown.\n"
        "Use these handoff_reason_code values only when outcome is human_handoff: "
        f"{', '.join(code.value for code in HandoffReasonCode)}.\n"
        "For paused_search, select exactly one track_key from paused_search_catalog, or return "
        "track_selection_status no_match/ambiguous with selected_track_key null.\n"
        "If no route is clearly safe, set outcome to unknown. Unknown maps to review hold.\n"
        "Required JSON schema:\n"
        "- outcome: string enum\n"
        "- handoff_reason_code: string enum or null\n"
        "- selected_track_key: catalog track_key or null\n"
        "- track_selection_status: selected, no_match, ambiguous, or null\n"
        "- reengagement_not_before: ISO date string or null\n"
        "- reengagement_window_label: short string or null\n"
        "- confidence: number between 0 and 1\n"
        "- evidence: list of short strings\n"
        "- evidence_event_ids: list of event_id values from lead-authored events only\n"
        "- lead_goal: short profile label or null\n"
        "- last_known_intent: short semantic description or null\n"
        "- intent_freshness: current, historical, or unknown\n"
        "- conversation_waiting_on: lead, agent, or unknown\n"
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
    paused_search_catalog: tuple[PausedSearchTrackCatalogEntry, ...],
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
        "paused_search_catalog": [
            {
                "track_key": entry.track_key,
                "display_name": entry.display_name,
                "selection_guidance": entry.selection_guidance,
            }
            for entry in paused_search_catalog
        ],
        "recent_messages": [_message_context(event) for event in crm_conversation_events[-20:]],
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
    latest_lead_signal_at = latest_inbound_at
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
    latest_lead_signal_older_than_dormant_threshold = _is_stale_by_threshold(
        value=latest_lead_signal_at,
        now=now,
        dormant_threshold_days=dormant_threshold_days,
    )
    events_after_latest_lead_signal = (
        [
            event
            for event in crm_conversation_events
            if latest_lead_signal_at is not None and event.occurred_at > latest_lead_signal_at
        ]
        if latest_lead_signal_at is not None
        else []
    )
    outbound_only_since_latest_lead_signal = (
        all(
            event.direction != CrmConversationEventDirection.INBOUND
            for event in events_after_latest_lead_signal
        )
        if latest_lead_signal_at is not None
        else None
    )
    has_current_inbound_engagement = (
        latest_lead_signal_older_than_dormant_threshold is False
        if latest_lead_signal_older_than_dormant_threshold is not None
        else (latest_lead_signal_at is not None if dormant_threshold_days is None else False)
    )
    conversation_waiting_on = _conversation_waiting_on(crm_conversation_events)
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
        "latest_lead_signal_at": _iso_datetime(latest_lead_signal_at),
        "days_since_last_meaningful_communication": _days_since(
            now, lead.last_meaningful_communication_at
        ),
        "days_since_latest_observed_message": _days_since(now, latest_message_at),
        "days_since_latest_property_event": _days_since(now, latest_property_event_at),
        "days_since_latest_observed_inbound_message": _days_since(now, latest_inbound_at),
        "days_since_latest_lead_signal": _days_since(now, latest_lead_signal_at),
        "latest_observed_message_older_than_dormant_threshold": (
            latest_observed_message_older_than_dormant_threshold
        ),
        "latest_lead_signal_older_than_dormant_threshold": (
            latest_lead_signal_older_than_dormant_threshold
        ),
        "outbound_only_since_latest_lead_signal": outbound_only_since_latest_lead_signal,
        "has_current_inbound_engagement": has_current_inbound_engagement,
        "conversation_waiting_on": conversation_waiting_on,
        "days_waiting_on_lead": (
            _days_since(now, latest_lead_signal_at)
            if conversation_waiting_on == "lead"
            else None
        ),
        "lead_signal_event_ids": [
            event.crm_activity_id
            for event in crm_conversation_events
            if event.direction == CrmConversationEventDirection.INBOUND
        ],
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


def _normalize_conversation_events(
    crm_conversation_events: tuple[CrmConversationEvent, ...],
) -> tuple[CrmConversationEvent, ...]:
    """Collapse duplicate CRM records before deriving conversation state."""
    seen_activity_ids: set[str] = set()
    seen_fingerprints: set[tuple[str | None, str, str | None]] = set()
    normalized: list[CrmConversationEvent] = []
    for event in sorted(
        crm_conversation_events,
        key=lambda item: (item.occurred_at, item.created_at, item.crm_activity_id),
    ):
        if event.crm_activity_id in seen_activity_ids:
            continue
        fingerprint = (
            event.direction.value if event.direction else None,
            event.occurred_at.isoformat(),
            " ".join(event.content.split()) if event.content else None,
        )
        if fingerprint in seen_fingerprints:
            continue
        seen_activity_ids.add(event.crm_activity_id)
        seen_fingerprints.add(fingerprint)
        normalized.append(event)
    return tuple(normalized)


def _message_context(event: CrmConversationEvent) -> dict[str, object]:
    return {
        "event_id": event.crm_activity_id,
        "direction": event.direction.value if event.direction else None,
        "actor_role": _actor_role(event),
        "is_lead_authored": event.direction == CrmConversationEventDirection.INBOUND,
        "activity_type": event.activity_type,
        "actor_name": event.actor_name,
        "content": event.content,
        "occurred_at": event.occurred_at.isoformat(),
    }


def _actor_role(event: CrmConversationEvent) -> str:
    if event.direction == CrmConversationEventDirection.INBOUND:
        return "lead"
    if event.direction == CrmConversationEventDirection.OUTBOUND:
        return "agent" if event.actor_agent_id or event.actor_name else "automation"
    if event.direction == CrmConversationEventDirection.INTERNAL:
        return "system"
    return "unknown"


def _conversation_waiting_on(
    crm_conversation_events: tuple[CrmConversationEvent, ...],
) -> str:
    if not crm_conversation_events:
        return "unknown"
    latest = crm_conversation_events[-1]
    if latest.direction == CrmConversationEventDirection.INBOUND:
        return "agent"
    if latest.direction in {
        CrmConversationEventDirection.OUTBOUND,
        CrmConversationEventDirection.INTERNAL,
    }:
        return "lead"
    return "unknown"


def _apply_route_policy(
    *,
    classification: _LLMLeadStateClassification,
    input_context: dict[str, object],
) -> tuple[_LLMLeadStateClassification, dict[str, object]]:
    freshness = input_context.get("freshness_context", {})
    if not isinstance(freshness, dict):
        freshness = {}
    proposed_outcome = classification.outcome.value
    evidence_ids = list(classification.evidence_event_ids)
    lead_signal_ids = set(str(value) for value in freshness.get("lead_signal_event_ids", []))
    invalid_evidence_ids = sorted(set(evidence_ids) - lead_signal_ids)
    has_current_inbound = freshness.get("has_current_inbound_engagement")
    policy_reasons: list[str] = []
    applied = classification

    if proposed_outcome == _LLMLeadStateClassificationOutcome.HUMAN_HANDOFF.value:
        if invalid_evidence_ids:
            policy_reasons.append("evidence_event_not_lead_authored")
        if has_current_inbound is False:
            policy_reasons.append("no_fresh_lead_signal_for_handoff")
        if policy_reasons:
            applied = classification.model_copy(
                update={
                    "outcome": _LLMLeadStateClassificationOutcome.DORMANT,
                    "handoff_reason_code": None,
                    "selected_track_key": None,
                    "track_selection_status": None,
                    "evidence": _dormant_policy_evidence(freshness),
                    "summary": _dormant_policy_summary(freshness),
                }
            )

    if proposed_outcome == _LLMLeadStateClassificationOutcome.PAUSED_SEARCH.value:
        if invalid_evidence_ids:
            policy_reasons.append("evidence_event_not_lead_authored")
            applied = classification.model_copy(
                update={
                    "outcome": _LLMLeadStateClassificationOutcome.REVIEW_HOLD,
                    "selected_track_key": None,
                    "track_selection_status": None,
                }
            )

    policy_trace: dict[str, object] = {
        "proposed_outcome": proposed_outcome,
        "applied_outcome": applied.outcome.value,
        "decision": "overridden" if applied.outcome != classification.outcome else "accepted",
        "reason_codes": policy_reasons,
        "proposed_evidence_event_ids": evidence_ids,
        "valid_lead_signal_event_ids": sorted(lead_signal_ids),
        "invalid_evidence_event_ids": invalid_evidence_ids,
        "freshness_gate": "current_inbound_required_for_handoff",
        "authoritative": True,
    }
    return applied, policy_trace


def _dormant_policy_evidence(freshness: dict[str, object]) -> list[str]:
    evidence = []
    days = freshness.get("days_since_latest_lead_signal")
    if isinstance(days, int):
        evidence.append(f"Latest lead-authored signal was {days} days ago.")
    evidence.append("No fresh lead-authored reply was observed after the outbound follow-ups.")
    return evidence


def _dormant_policy_summary(freshness: dict[str, object]) -> str:
    days = freshness.get("days_since_latest_lead_signal")
    if isinstance(days, int):
        return (
            f"Historical lead interest is stale after {days} days without a fresh inbound reply; "
            "route is dormant."
        )
    return "No fresh lead-authored engagement was observed; route is dormant."


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
        "You analyze a real estate lead's conversation and propose a safe state. "
        "Return exactly one valid JSON object and nothing else. "
        "Do not include markdown fences, prose, comments, or trailing text.\n"
        "You must use only the exact enum values provided below. Never invent or shorten "
        "an outcome or reason code.\n"
        "Use freshness_context as authoritative derived timing facts from the lead record "
        "and the recent CRM context window. Only events with actor_role=lead and "
        "is_lead_authored=true are evidence of lead intent. Outbound agent, automation, "
        "internal, and unknown events are context only and must never support a handoff. "
        "Historical interest alone is not enough for human_handoff.\n"
        "Choose exactly one outcome using these rules, in priority order:\n"
        "1. human_handoff — propose this only when a lead-authored event is current and "
        "unresolved, and the lead shows active buying/selling "
        "interest now, asks for a person now, requests a showing/call now, or asks for "
        "property/pricing/financing/market/legal/tax advice that still needs a human follow-up. "
        "Do not choose human_handoff from a stale property inquiry alone.\n"
        "2. blocked — the lead opted out, is not interested, or should not be nurtured.\n"
        "3. paused_search — the lead is not buying/selling right now but gave a clear reason "
        "such as timing, rates, inventory, renting, financial prep, or life timing.\n"
        "4. dormant — the lead went quiet and there is no known current reason to pause or "
        "handoff. If freshness_context.stale_property_interest_without_observed_reply is "
        "true, prefer dormant unless the context clearly supports blocked, paused_search, "
        "or review_hold. If freshness_context.latest_lead_signal_older_than_dormant_threshold "
        "is true, also treat old showing requests, old property interest, and old "
        "internal-only context as historical unless there is a newer current lead-authored "
        "signal.\n"
        "5. review_hold — use this only when the conversation clearly requires human review.\n"
        "6. unknown — use this when no route is a clear safe winner. Unknown maps to review hold.\n"
        "If a property inquiry is older than the configured dormant threshold and there is no "
        "observed later inbound reply, treat that inquiry as historical context rather than "
        "current handoff urgency.\n"
        "If the newest lead-authored signal is older than the configured dormant threshold, "
        "prefer dormant over human_handoff unless the context clearly supports blocked, "
        "paused_search, or review_hold.\n"
        "When stale timing facts strongly support dormant, do not assign low confidence just "
        "because the historical message text sounds urgent or high-intent. In those stale-only "
        "cases, confidence should usually be high unless there is a real newer conflicting "
        "signal in the context.\n"
        "A recent lead-authored request for help, a fresh showing request, or a fresh ask "
        "for advice can still be human_handoff even if older dormant history exists.\n"
        "For paused_search, classify against paused_search_catalog only. Choose one exact "
        "track_key, or report no_match/ambiguous. The catalog is a closed set: never invent, "
        "normalize, translate, or substitute a track_key. selected_track_key must be null "
        "unless it exactly equals one catalog track_key.\n"
        "For human_handoff, handoff_reason_code must be exactly one of: "
        f"{', '.join(code.value for code in HandoffReasonCode)}.\n"
        "For outcomes other than paused_search, selected_track_key and "
        "track_selection_status must be null.\n"
        "For outcomes other than human_handoff, handoff_reason_code must be null.\n"
        "Set reengagement_not_before to an ISO date only if the lead mentioned a concrete date.\n"
        "Set reengagement_window_label to a short human phrase such as "
        "'after lease ends' or 'next quarter'.\n"
        "evidence is a list of short phrases from lead-authored events that support your "
        "proposal. evidence_event_ids must contain only the exact event_id values of those "
        "lead-authored events; never cite outbound or internal event IDs.\n"
        "Also report lead_goal, last_known_intent, intent_freshness, and "
        "conversation_waiting_on as semantic context. The backend route policy is "
        "authoritative and may override your proposal when freshness or evidence rules fail.\n"
        "summary is a concise explanation under 600 characters.\n"
        "Return only JSON with keys: outcome, handoff_reason_code, selected_track_key, "
        "track_selection_status, "
        "reengagement_not_before, reengagement_window_label, confidence, evidence, "
        "evidence_event_ids, lead_goal, last_known_intent, intent_freshness, "
        "conversation_waiting_on, summary."
    )
