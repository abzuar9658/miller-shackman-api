from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.application.use_cases.route_ai_nurture_lead import (
    AiNurtureRoute,
    AiNurtureRouteResult,
    route_ai_nurture_lead,
)
from app.domain.compliance.contactability import ContactPermissionStatus
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
    PausedSearchReasonCode,
    PausedSearchSource,
    PropertyEventType,
)
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeClassificationLLMClient,
    FakeCrmConversationEventRepository,
    FakeLeadClassificationArtifactRepository,
    FakeLeadRepository,
    FakeLeadRoutingReviewRepository,
    FakeWorkspaceLLMConfigRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeLeadWorkflowRepository,
    FakeTemporalSignalOutboxRepository,
)
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
)

NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
LEAD_ID = UUID("22222222-2222-2222-2222-222222222222")


def _lead(
    *, paused_search_active: bool = False, do_not_contact: bool = False
) -> CanonicalLeadRecord:
    pause_reason_code = PausedSearchReasonCode.WAITING_FOR_RATES if paused_search_active else None
    paused_search_source = (
        PausedSearchSource.AI_CONVERSATION_CLASSIFICATION if paused_search_active else None
    )
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="Lead",
        assigned_agent_crm_id="agent-99",
        has_accountable_owner=True,
        tags=("ai_nurture",),
        primary_email="lead@example.com",
        has_email=True,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        do_not_contact=do_not_contact,
        paused_search_active=paused_search_active,
        pause_reason_code=pause_reason_code,
        paused_search_source=paused_search_source,
    )


def _crm_event(content: str) -> CrmConversationEvent:
    return CrmConversationEvent(
        crm_conversation_event_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider="follow_up_boss",
        crm_activity_id=str(uuid4()),
        activity_type="note",
        occurred_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        direction=CrmConversationEventDirection.INBOUND,
        content=content,
    )


def _crm_event_with_metadata(
    content: str,
    *,
    direction: CrmConversationEventDirection = CrmConversationEventDirection.INTERNAL,
    occurred_at: datetime = NOW,
) -> CrmConversationEvent:
    return CrmConversationEvent(
        crm_conversation_event_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider="follow_up_boss",
        crm_activity_id=str(uuid4()),
        activity_type="note",
        occurred_at=occurred_at,
        created_at=occurred_at,
        updated_at=occurred_at,
        direction=direction,
        content=content,
    )


def _paused_search_track_repository() -> FakePausedSearchTrackAdminRepository:
    return FakePausedSearchTrackAdminRepository()


async def _route(
    lead: CanonicalLeadRecord,
    llm_client: FakeClassificationLLMClient,
    crm_events: tuple[CrmConversationEvent, ...] = (),
    routing_review_repository: FakeLeadRoutingReviewRepository | None = None,
    dormant_threshold_days: int | None = None,
) -> AiNurtureRouteResult:
    lead_repo = FakeLeadRepository(lead)
    artifact_repo = FakeLeadClassificationArtifactRepository()
    workflow_repo = FakeLeadWorkflowRepository()
    outbox = FakeTemporalSignalOutboxRepository()
    track_repo = _paused_search_track_repository()
    event_repo = FakeCrmConversationEventRepository(crm_events)

    result = await route_ai_nurture_lead(
        workspace_id=WORKSPACE_ID,
        lead=lead,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=event_repo,
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=llm_client,
        now=NOW,
        dormant_threshold_days=dormant_threshold_days,
        lead_workflow_repository=workflow_repo,
        paused_search_track_repository=track_repo,
        temporal_signal_outbox_repository=outbox,
        routing_review_repository=routing_review_repository,
    )
    return result


@pytest.mark.asyncio
async def test_hard_suppressed_lead_returns_blocked() -> None:
    lead = _lead(do_not_contact=True)
    result = await _route(lead, FakeClassificationLLMClient(outcome="dormant"))
    assert result.route == AiNurtureRoute.BLOCKED
    assert result.reason_codes == ("suppression",)
    assert result.classification_result is None


@pytest.mark.asyncio
async def test_fresh_human_handoff_wins_over_existing_paused_search() -> None:
    lead = _lead(paused_search_active=True)
    result = await _route(
        lead,
        FakeClassificationLLMClient(outcome="human_handoff"),
        crm_events=(_crm_event("I want to schedule a showing this weekend."),),
    )
    assert result.route == AiNurtureRoute.HUMAN_HANDOFF


@pytest.mark.asyncio
async def test_fresh_blocked_wins_over_existing_paused_search() -> None:
    lead = _lead(paused_search_active=True)
    result = await _route(
        lead,
        FakeClassificationLLMClient(outcome="blocked"),
        crm_events=(_crm_event("Stop contacting me."),),
    )
    assert result.route == AiNurtureRoute.BLOCKED


@pytest.mark.asyncio
async def test_fresh_paused_search_keeps_existing_paused_search() -> None:
    lead = _lead(paused_search_active=True)
    result = await _route(
        lead,
        FakeClassificationLLMClient(outcome="paused_search", pause_reason_code="waiting_for_rates"),
    )
    assert result.route == AiNurtureRoute.PAUSED_SEARCH


@pytest.mark.asyncio
async def test_existing_paused_search_fallback_beats_dormant_classification() -> None:
    lead = _lead(paused_search_active=True)
    result = await _route(lead, FakeClassificationLLMClient(outcome="dormant"))
    assert result.route == AiNurtureRoute.PAUSED_SEARCH
    assert result.reason_codes == ("existing_paused_search_profile",)


@pytest.mark.asyncio
async def test_existing_paused_search_fallback_beats_rejected_classification() -> None:
    lead = _lead(paused_search_active=True)
    result = await _route(lead, FakeClassificationLLMClient(outcome="dormant", confidence=0.5))
    assert result.route == AiNurtureRoute.PAUSED_SEARCH


@pytest.mark.asyncio
async def test_dormant_classification_without_profile_returns_dormant() -> None:
    lead = _lead(paused_search_active=False)
    result = await _route(lead, FakeClassificationLLMClient(outcome="dormant"))
    assert result.route == AiNurtureRoute.DORMANT


@pytest.mark.asyncio
async def test_rejected_classification_without_profile_returns_review_hold() -> None:
    lead = _lead(paused_search_active=False)
    result = await _route(lead, FakeClassificationLLMClient(outcome="dormant", confidence=0.5))
    assert result.route == AiNurtureRoute.REVIEW_HOLD


@pytest.mark.asyncio
async def test_review_hold_route_creates_pending_routing_review() -> None:
    lead = _lead(paused_search_active=False)
    review_repository = FakeLeadRoutingReviewRepository()

    result = await _route(
        lead,
        FakeClassificationLLMClient(outcome="dormant", confidence=0.5),
        routing_review_repository=review_repository,
    )

    assert result.route == AiNurtureRoute.REVIEW_HOLD
    assert len(review_repository.saved) == 1
    assert result.artifact is not None
    assert review_repository.saved[0].artifact_id == result.artifact.artifact_id
    assert review_repository.saved[0].reason_codes == ("classification_rejected",)


@pytest.mark.asyncio
async def test_paused_search_fallback_supersedes_pending_routing_review() -> None:
    review_repository = FakeLeadRoutingReviewRepository()

    initial_result = await _route(
        _lead(paused_search_active=False),
        FakeClassificationLLMClient(outcome="dormant", confidence=0.5),
        routing_review_repository=review_repository,
    )
    assert initial_result.route == AiNurtureRoute.REVIEW_HOLD

    fallback_result = await _route(
        _lead(paused_search_active=True),
        FakeClassificationLLMClient(outcome="dormant", confidence=0.5),
        routing_review_repository=review_repository,
    )

    assert fallback_result.route == AiNurtureRoute.PAUSED_SEARCH
    assert len(review_repository.saved) == 1
    latest_review = review_repository.saved[0]
    assert latest_review.status.value == "superseded"


@pytest.mark.asyncio
async def test_supplemental_crm_events_are_considered_for_rerouting() -> None:
    lead = _lead(paused_search_active=True)
    event_repo = FakeCrmConversationEventRepository()
    lead_repo = FakeLeadRepository(lead)
    artifact_repo = FakeLeadClassificationArtifactRepository()

    result = await route_ai_nurture_lead(
        workspace_id=WORKSPACE_ID,
        lead=lead,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=event_repo,
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(outcome="human_handoff"),
        now=NOW,
        supplemental_crm_conversation_events=(_crm_event("I am ready to buy now."),),
    )
    assert result.route == AiNurtureRoute.HUMAN_HANDOFF
    assert result.has_recent_crm_conversation_context is True


@pytest.mark.asyncio
async def test_route_passes_configured_dormant_threshold_to_classifier() -> None:
    property_inquiry_at = NOW - timedelta(days=80)
    lead = replace(
        _lead(),
        latest_property_event_type=PropertyEventType.PROPERTY_INQUIRY,
        latest_property_event_at=property_inquiry_at,
        latest_property_context_present=True,
        last_meaningful_communication_at=property_inquiry_at,
    )
    llm_client = FakeClassificationLLMClient(outcome="dormant")

    result = await _route(
        lead,
        llm_client,
        crm_events=(
            _crm_event_with_metadata(
                "I am interested in this listing.",
                direction=CrmConversationEventDirection.INTERNAL,
            ),
        ),
        dormant_threshold_days=45,
    )

    assert result.route == AiNurtureRoute.DORMANT
    assert '"dormant_threshold_days": 45' in llm_client.requests[0].prompt
    assert '"stale_property_interest_without_observed_reply": true' in llm_client.requests[0].prompt


@pytest.mark.asyncio
async def test_route_includes_overall_message_staleness_for_old_conversation_window() -> None:
    llm_client = FakeClassificationLLMClient(outcome="dormant")

    result = await _route(
        _lead(),
        llm_client,
        crm_events=(
            _crm_event_with_metadata(
                "I am interested in 425 W 24th St and want a tour.",
                direction=CrmConversationEventDirection.OUTBOUND,
                occurred_at=NOW - timedelta(days=74),
            ),
            _crm_event_with_metadata(
                "AI has been disabled until ai_on is added.",
                direction=CrmConversationEventDirection.INTERNAL,
                occurred_at=NOW - timedelta(days=60),
            ),
        ),
        dormant_threshold_days=10,
    )

    assert result.route == AiNurtureRoute.DORMANT
    assert (
        '"latest_observed_message_older_than_dormant_threshold": true'
        in llm_client.requests[0].prompt
    )
    assert '"days_since_latest_observed_message": 60' in llm_client.requests[0].prompt


@pytest.mark.asyncio
async def test_future_timing_text_still_uses_llm_route_for_dormant() -> None:
    lead = _lead(paused_search_active=False)
    llm_client = FakeClassificationLLMClient(outcome="dormant")

    result = await _route(
        lead,
        llm_client,
        crm_events=(_crm_event("Lead said maybe January 2027."),),
    )

    assert result.route == AiNurtureRoute.DORMANT
    assert len(llm_client.requests) == 1


@pytest.mark.asyncio
async def test_future_timing_text_with_low_confidence_routes_to_review_hold() -> None:
    lead = _lead(paused_search_active=False)
    llm_client = FakeClassificationLLMClient(outcome="paused_search", confidence=0.5)

    result = await _route(
        lead,
        llm_client,
        crm_events=(_crm_event("Lead wants to wait until January 2027."),),
    )

    assert result.route == AiNurtureRoute.REVIEW_HOLD
    assert len(llm_client.requests) == 2


@pytest.mark.asyncio
async def test_future_timing_text_can_still_route_to_paused_search_when_llm_confirms() -> None:
    lead = _lead(paused_search_active=False)
    llm_client = FakeClassificationLLMClient(
        outcome="paused_search",
        pause_reason_code="timing_not_right",
        reengagement_not_before="2027-01-01T00:00:00Z",
        reengagement_window_label="January 2027",
    )

    result = await _route(
        lead,
        llm_client,
        crm_events=(_crm_event("Lead wants to wait until January 2027."),),
    )

    assert result.route == AiNurtureRoute.PAUSED_SEARCH
    assert len(llm_client.requests) == 1
