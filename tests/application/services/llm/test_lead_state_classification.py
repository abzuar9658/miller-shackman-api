import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4, uuid5

import pytest

from app.application.ports.llm import LLMClient, LLMCompletionRequest, LLMResult
from app.application.services.llm.lead_state_classification import (
    LeadStateClassificationReasonCode,
    LeadStateClassificationStatus,
    classify_lead_from_conversation,
)
from app.domain.campaigns import PausedSearchTrackCatalogEntry
from app.domain.conversations import (
    CrmConversationEvent,
    CrmConversationEventDirection,
    HandoffReasonCode,
)
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
    LeadStateClassificationOutcome,
    PausedSearchTrackSelectionStatus,
    PropertyEventType,
)
from app.domain.llm import LLMProviderKind, LLMTaskKind
from scripts.seed_paused_search_tracks import TRACK_DEFINITIONS

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


class _StubLLMClient(LLMClient):
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[LLMCompletionRequest] = []

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        return LLMResult(
            text=self.text,
            model="openai/gpt-4o-mini",
            prompt_version=request.prompt_version,
            latency_ms=10,
            usage_tokens=20,
        )


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
    )


def _event(
    content: str,
    *,
    direction: CrmConversationEventDirection = CrmConversationEventDirection.INBOUND,
    occurred_at: datetime = NOW,
) -> CrmConversationEvent:
    return CrmConversationEvent(
        crm_conversation_event_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        crm_activity_id=f"act-{content[:20]}",
        activity_type="Note",
        direction=direction,
        content=content,
        occurred_at=occurred_at,
        created_at=occurred_at,
        updated_at=occurred_at,
    )


def _classification_json(**kwargs: object) -> str:
    explicit_selection_status = kwargs.pop("track_selection_status", None)
    explicit_track_key = kwargs.pop("selected_track_key", None)
    if kwargs.get("outcome") == "paused_search":
        kwargs["selected_track_key"] = explicit_track_key
        kwargs["track_selection_status"] = explicit_selection_status or (
            "selected" if explicit_track_key is not None else None
        )
    else:
        kwargs["selected_track_key"] = None
        kwargs["track_selection_status"] = None
    return json.dumps(kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("selection_status", ["no_match", "ambiguous"])
async def test_preserves_uncertain_catalog_selection_for_review(
    selection_status: str,
) -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            selected_track_key=None,
            track_selection_status=selection_status,
            confidence=0.9,
            evidence=["The pause does not clearly fit one category"],
            summary="Track selection needs human review.",
        )
    )

    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(_event("Please pause for now"),),
        llm_client=client,
        paused_search_catalog=_catalog(),
    )

    assert result.status is LeadStateClassificationStatus.CLASSIFIED
    assert result.track_selection_status is PausedSearchTrackSelectionStatus(selection_status)
    assert result.track_version_id is None


def _catalog() -> tuple[PausedSearchTrackCatalogEntry, ...]:
    return (
        PausedSearchTrackCatalogEntry(
            track_key="waiting-for-rates",
            display_name="Waiting for rates",
            selection_guidance="Use when a lead explicitly waits for borrowing rates to improve.",
            track_id=UUID("00000000-0000-0000-0000-000000000003"),
            track_version_id=UUID("00000000-0000-0000-0000-000000000004"),
        ),
    )


def _seeded_track_catalog() -> tuple[PausedSearchTrackCatalogEntry, ...]:
    namespace = UUID("00000000-0000-0000-0000-000000000100")
    return tuple(
        PausedSearchTrackCatalogEntry(
            track_key=definition.key,
            display_name=definition.display_name,
            selection_guidance=definition.selection_guidance,
            track_id=uuid5(namespace, f"track:{definition.key}"),
            track_version_id=uuid5(namespace, f"version:{definition.key}"),
        )
        for definition in TRACK_DEFINITIONS
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("track_key", "conversation"),
    (
        (
            "specific_property_only",
            "We still only want that specific home, but we are not ready for a showing "
            "or agent call; please do not send alternatives.",
        ),
        (
            "waiting_for_inventory",
            "Nothing available fits, so please check back when more inventory appears.",
        ),
        (
            "renter_now_future_buyer",
            "We are renting for now but may buy after our rental timeline changes.",
        ),
        (
            "lease_expiration",
            "We want to revisit buying when our lease expires and we move out.",
        ),
        (
            "recently_renewed_lease",
            "We just renewed our lease, so buying needs to wait until the new timing.",
        ),
        (
            "search_fit_reassessment",
            "Our criteria and timing no longer fit, and we need to reassess the search.",
        ),
    ),
)
async def test_seeded_track_keys_resolve_against_the_full_catalog(
    track_key: str,
    conversation: str,
) -> None:
    catalog = _seeded_track_catalog()
    client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            selected_track_key=track_key,
            confidence=0.93,
            evidence=[conversation],
            summary=f"Paused-search classification for {track_key}.",
        )
    )

    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(_event(conversation),),
        llm_client=client,
        paused_search_catalog=catalog,
    )

    expected = next(entry for entry in catalog if entry.track_key == track_key)
    assert result.status is LeadStateClassificationStatus.CLASSIFIED
    assert result.outcome is LeadStateClassificationOutcome.PAUSED_SEARCH
    assert result.selected_track_key == track_key
    assert result.track_selection_status is PausedSearchTrackSelectionStatus.SELECTED
    assert result.track_version_id == expected.track_version_id
    assert result.evidence == (conversation,)
    recent_messages = result.input_context["recent_messages"]
    assert isinstance(recent_messages, list)
    assert recent_messages
    first_message = recent_messages[0]
    assert isinstance(first_message, dict)
    assert first_message["content"] == conversation
    assert all(entry.track_key in client.requests[0].prompt for entry in catalog)
    assert all(entry.selection_guidance in client.requests[0].prompt for entry in catalog)


async def test_classifies_paused_search_with_reason_and_timing() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            selected_track_key="waiting-for-rates",
            reengagement_not_before="2026-09-01",
            reengagement_window_label="after summer",
            confidence=0.88,
            evidence=["Lead said rates are too high"],
            summary="Lead is waiting for lower rates.",
        )
    )
    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(_event("I'm waiting for rates to drop"),),
        llm_client=client,
        paused_search_catalog=_catalog(),
    )
    assert result.status == LeadStateClassificationStatus.CLASSIFIED
    assert result.outcome == LeadStateClassificationOutcome.PAUSED_SEARCH
    assert result.selected_track_key == "waiting-for-rates"
    assert result.track_selection_status is PausedSearchTrackSelectionStatus.SELECTED
    assert result.track_version_id == _catalog()[0].track_version_id
    assert result.reengagement_not_before == datetime(2026, 9, 1, tzinfo=UTC)
    assert result.reengagement_window_label == "after summer"
    assert result.confidence == 0.88
    assert result.evidence == ("Lead said rates are too high",)
    assert result.summary == "Lead is waiting for lower rates."
    assert result.prompt_text == client.requests[0].prompt
    assert result.input_context["conversation_summary"] is None
    recent_messages = result.input_context["recent_messages"]
    assert isinstance(recent_messages, list)
    assert recent_messages[0]["content"] == "I'm waiting for rates to drop"
    assert result.raw_llm_response_text == client.text
    assert result.parsed_llm_response["outcome"] == "paused_search"
    assert client.requests[0].task is LLMTaskKind.CLASSIFICATION
    assert client.requests[0].provider is None


async def test_threads_provider_through_classification_request() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="dormant",
            confidence=0.9,
            evidence=["Lead has gone quiet"],
            summary="Lead is dormant.",
        )
    )
    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(_event("Not right now"),),
        llm_client=client,
        provider=LLMProviderKind.BEDROCK,
    )
    assert result.status == LeadStateClassificationStatus.CLASSIFIED
    assert client.requests[0].provider is LLMProviderKind.BEDROCK
    assert client.requests[0].task is LLMTaskKind.CLASSIFICATION


async def test_classifies_human_handoff_with_reason_code() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="human_handoff",
            handoff_reason_code="specific_property_or_advice",
            reengagement_not_before=None,
            reengagement_window_label=None,
            confidence=0.93,
            evidence=["Lead asked for pricing advice on a listing"],
            summary="Lead needs an agent for pricing advice.",
        )
    )
    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(_event("Can you advise me on pricing for this listing?"),),
        llm_client=client,
        paused_search_catalog=_catalog(),
    )
    assert result.status == LeadStateClassificationStatus.CLASSIFIED
    assert result.outcome == LeadStateClassificationOutcome.HUMAN_HANDOFF
    assert result.handoff_reason_code == HandoffReasonCode.SPECIFIC_PROPERTY_OR_ADVICE


async def test_rejects_human_handoff_without_reason_code() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="human_handoff",
            reengagement_not_before=None,
            reengagement_window_label=None,
            confidence=0.90,
            evidence=["Lead asked to speak with someone"],
            summary="Lead needs a person.",
        )
    )
    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(_event("Can I speak with an agent?"),),
        llm_client=client,
    )
    assert result.status == LeadStateClassificationStatus.REJECTED
    assert LeadStateClassificationReasonCode.INVALID_LLM_RESPONSE in result.reasons


async def test_maps_unknown_outcome_to_review_hold() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="unknown",
            handoff_reason_code=None,
            confidence=0.91,
            evidence=["Conversation mixed timing and interest signals."],
            summary="No route is a clear safe winner.",
        )
    )
    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(_event("Maybe next year, not sure yet."),),
        llm_client=client,
        paused_search_catalog=_catalog(),
    )
    assert result.status == LeadStateClassificationStatus.CLASSIFIED
    assert result.outcome == LeadStateClassificationOutcome.REVIEW_HOLD
    assert result.parsed_llm_response["outcome"] == "unknown"


async def test_rejects_low_confidence() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            selected_track_key="waiting-for-rates",
            confidence=0.45,
            evidence=["Maybe waiting"],
            summary="Low confidence.",
        )
    )
    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(),
        llm_client=client,
        paused_search_catalog=_catalog(),
    )
    assert result.status == LeadStateClassificationStatus.REJECTED
    assert LeadStateClassificationReasonCode.LOW_CONFIDENCE in result.reasons
    assert result.raw_llm_response_text == client.text
    assert result.parsed_llm_response["confidence"] == 0.45


async def test_rejects_invalid_response() -> None:
    client = _StubLLMClient("this is not valid json")
    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(),
        llm_client=client,
    )
    assert result.status == LeadStateClassificationStatus.REJECTED
    assert LeadStateClassificationReasonCode.INVALID_LLM_RESPONSE in result.reasons
    assert result.prompt_text == client.requests[-1].prompt
    assert result.raw_llm_response_text == client.text
    assert result.validation_error is not None


async def test_rejects_unknown_outcome() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="unknown_outcome",
            confidence=0.95,
            evidence=["Something"],
            summary="Unknown.",
        )
    )
    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(),
        llm_client=client,
    )
    assert result.status == LeadStateClassificationStatus.REJECTED
    assert LeadStateClassificationReasonCode.INVALID_LLM_RESPONSE in result.reasons


async def test_rejects_unknown_selected_track_key() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            selected_track_key="aliens_are_landin",
            confidence=0.95,
            evidence=["Lead said something"],
            summary="Unknown reason code.",
        )
    )
    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(),
        llm_client=client,
    )
    assert result.status == LeadStateClassificationStatus.REJECTED
    assert LeadStateClassificationReasonCode.INVALID_TRACK_SELECTION in result.reasons


async def test_prompt_requires_exact_catalog_keys_for_paused_search() -> None:
    catalog = _catalog()
    client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            selected_track_key="waiting-for-rates",
            confidence=0.95,
            evidence=["Lead is waiting for rates."],
            summary="The lead is waiting for rates.",
        )
    )

    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(),
        llm_client=client,
        paused_search_catalog=catalog,
    )

    assert result.status is LeadStateClassificationStatus.CLASSIFIED
    assert "The catalog is a closed set" in client.requests[0].prompt
    assert "selected_track_key must be null unless it exactly equals" in (
        client.requests[0].prompt
    )


async def test_includes_freshness_context_for_stale_property_interest_without_reply() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="dormant",
            handoff_reason_code=None,
            selected_track_key=None,
            confidence=0.91,
            evidence=["Inquiry is stale"],
            summary="Historical property inquiry with no later reply.",
        )
    )
    property_inquiry_at = NOW - timedelta(days=95)
    lead = replace(
        _lead(),
        latest_property_event_type=PropertyEventType.PROPERTY_INQUIRY,
        latest_property_event_at=property_inquiry_at,
        latest_property_context_present=True,
        last_meaningful_communication_at=property_inquiry_at,
    )

    result = await classify_lead_from_conversation(
        lead=lead,
        now=NOW,
        crm_conversation_events=(
            _event(
                "I am interested in 343 East 74th Street.",
                occurred_at=property_inquiry_at,
            ),
        ),
        llm_client=client,
        dormant_threshold_days=60,
    )

    freshness_context = result.input_context["freshness_context"]
    assert isinstance(freshness_context, dict)
    assert result.prompt_text is not None
    assert freshness_context["dormant_threshold_days"] == 60
    assert freshness_context["latest_observed_message_at"] == property_inquiry_at.isoformat()
    assert freshness_context["days_since_latest_observed_message"] == 95
    assert freshness_context["latest_observed_message_older_than_dormant_threshold"] is True
    assert freshness_context["days_since_latest_property_event"] == 95
    assert freshness_context["has_observed_inbound_reply_after_latest_property_event"] is False
    assert freshness_context["property_interest_is_stale_by_threshold"] is True
    assert freshness_context["stale_property_interest_without_observed_reply"] is True
    assert "Do not choose human_handoff from a stale property inquiry alone." in result.prompt_text
    assert (
        "If a property inquiry is older than the configured dormant threshold" in result.prompt_text
    )
    assert "If the newest lead-authored signal is older" in result.prompt_text
    assert (
        "do not assign low confidence just because the historical message text sounds urgent"
        in result.prompt_text
    )


async def test_uses_latest_observed_message_freshness_when_property_fields_are_missing() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="dormant",
            handoff_reason_code=None,
            confidence=0.9,
            evidence=["No fresh engagement after old tour request"],
            summary="Old conversation window should be treated as dormant.",
        )
    )
    outbound_at = NOW - timedelta(days=74)
    internal_at = NOW - timedelta(days=60)

    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(
            _event(
                "I am interested in 425 W 24th St and want a tour.",
                direction=CrmConversationEventDirection.OUTBOUND,
                occurred_at=outbound_at,
            ),
            _event(
                "AI has been disabled until ai_on is added.",
                direction=CrmConversationEventDirection.INTERNAL,
                occurred_at=internal_at,
            ),
        ),
        llm_client=client,
        dormant_threshold_days=10,
    )

    freshness_context = result.input_context["freshness_context"]
    assert isinstance(freshness_context, dict)
    assert result.prompt_text is not None
    assert freshness_context["latest_observed_message_at"] == internal_at.isoformat()
    assert freshness_context["days_since_latest_observed_message"] == 60
    assert freshness_context["latest_observed_message_older_than_dormant_threshold"] is True
    assert freshness_context["latest_observed_inbound_message_at"] is None
    assert freshness_context["days_since_last_meaningful_communication"] is None
    assert freshness_context["property_interest_is_stale_by_threshold"] is None
    assert freshness_context["stale_property_interest_without_observed_reply"] is None
    assert "prefer dormant over human_handoff" in result.prompt_text
    assert "confidence should usually be high" in result.prompt_text


async def test_marks_recent_property_interest_with_reply_as_not_stale() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="human_handoff",
            handoff_reason_code="specific_property_or_advice",
            confidence=0.95,
            evidence=["Lead asked for help on a specific property"],
            summary="Fresh property help request needs an agent.",
        )
    )
    property_inquiry_at = NOW - timedelta(days=4)
    lead = replace(
        _lead(),
        latest_property_event_type=PropertyEventType.PROPERTY_INQUIRY,
        latest_property_event_at=property_inquiry_at,
        latest_property_context_present=True,
        last_meaningful_communication_at=NOW - timedelta(days=1),
    )

    result = await classify_lead_from_conversation(
        lead=lead,
        now=NOW,
        crm_conversation_events=(
            _event(
                "I am interested in 343 East 74th Street.",
                occurred_at=property_inquiry_at,
            ),
            _event(
                "Can someone help me with this property today?",
                occurred_at=NOW - timedelta(days=1),
            ),
        ),
        llm_client=client,
        dormant_threshold_days=60,
    )

    freshness_context = result.input_context["freshness_context"]
    assert isinstance(freshness_context, dict)
    assert result.prompt_text is not None
    assert freshness_context["latest_observed_message_at"] == (NOW - timedelta(days=1)).isoformat()
    assert freshness_context["days_since_latest_observed_message"] == 1
    assert freshness_context["latest_observed_message_older_than_dormant_threshold"] is False
    assert freshness_context["property_interest_is_stale_by_threshold"] is False
    assert freshness_context["has_observed_inbound_reply_after_latest_property_event"] is True
    assert freshness_context["stale_property_interest_without_observed_reply"] is False


async def test_overrides_stale_handoff_after_outbound_followups() -> None:
    stale_inbound = _event(
        "I'm interested in 309 East Houston Street #4E. This will be a cash purchase for us.",
        occurred_at=NOW - timedelta(days=14),
    )
    outbound_follow_up = _event(
        "When are you available for a showing?",
        direction=CrmConversationEventDirection.OUTBOUND,
        occurred_at=NOW - timedelta(days=3),
    )
    client = _StubLLMClient(
        _classification_json(
            outcome="human_handoff",
            handoff_reason_code="specific_property_or_advice",
            confidence=0.94,
            evidence=["Cash purchase inquiry"],
            evidence_event_ids=[outbound_follow_up.crm_activity_id],
            lead_goal="buyer",
            last_known_intent="cash purchase of a specific property",
            intent_freshness="historical",
            conversation_waiting_on="lead",
            summary="Lead is interested in a specific property.",
        )
    )

    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(outbound_follow_up, stale_inbound),
        llm_client=client,
        dormant_threshold_days=10,
    )

    assert result.status == LeadStateClassificationStatus.CLASSIFIED
    assert result.outcome == LeadStateClassificationOutcome.DORMANT
    assert result.summary is not None
    assert "stale" in result.summary
    assert result.parsed_llm_response["outcome"] == "human_handoff"
    freshness_context = result.input_context["freshness_context"]
    assert isinstance(freshness_context, dict)
    assert freshness_context["latest_lead_signal_at"] == stale_inbound.occurred_at.isoformat()
    assert freshness_context["days_since_latest_lead_signal"] == 14
    assert freshness_context["has_current_inbound_engagement"] is False
    assert freshness_context["outbound_only_since_latest_lead_signal"] is True
    policy = result.input_context["classifier_policy"]
    assert isinstance(policy, dict)
    assert policy["decision"] == "overridden"
    assert "no_fresh_lead_signal_for_handoff" in policy["reason_codes"]
    assert "evidence_event_not_lead_authored" in policy["reason_codes"]


async def test_accepts_handoff_for_fresh_lead_authored_signal() -> None:
    inbound = _event(
        "Can someone help me schedule a showing today?",
        occurred_at=NOW - timedelta(days=1),
    )
    client = _StubLLMClient(
        _classification_json(
            outcome="human_handoff",
            handoff_reason_code="human_requested",
            confidence=0.93,
            evidence=["Lead requested help scheduling a showing."],
            evidence_event_ids=[inbound.crm_activity_id],
            lead_goal="buyer",
            last_known_intent="wants to schedule a showing",
            intent_freshness="current",
            conversation_waiting_on="agent",
            summary="Lead needs an agent to schedule a showing.",
        )
    )

    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(inbound,),
        llm_client=client,
        dormant_threshold_days=10,
    )

    assert result.outcome == LeadStateClassificationOutcome.HUMAN_HANDOFF
    policy = result.input_context["classifier_policy"]
    assert isinstance(policy, dict)
    assert policy["decision"] == "accepted"
    assert policy["applied_outcome"] == "human_handoff"
