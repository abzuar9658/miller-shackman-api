import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.application.ports.llm import LLMClient, LLMCompletionRequest, LLMResult
from app.application.use_cases.apply_lead_state_classification import (
    ApplyLeadStateClassificationStatus,
    apply_lead_state_classification,
)
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
    LeadClassificationAppliedStatus,
    LeadStateClassificationOutcome,
    PausedSearchReasonCode,
    PausedSearchSource,
    lead_paused_search_profile,
)
from app.domain.llm import WorkspaceLLMConfig
from app.domain.workflows import LeadWorkflow, TemporalSignalName, WorkflowState
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCrmConversationEventRepository,
    FakeLeadClassificationArtifactRepository,
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeWorkspaceLLMConfigRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeTemporalSignalOutboxRepository,
)
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000004")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000005")
ENROLLMENT_ID = UUID("00000000-0000-0000-0000-000000000006")
TRACK_ID = UUID("00000000-0000-0000-0000-000000000007")
TRACK_VERSION_ID = UUID("00000000-0000-0000-0000-000000000008")
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


def _classification_json(**kwargs: object) -> str:
    return json.dumps(kwargs)


def _lead(*, paused_search_source: PausedSearchSource | None = None) -> CanonicalLeadRecord:
    lead = CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
    )
    if paused_search_source is not None:
        return replace(
            lead,
            paused_search_active=True,
            pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
            paused_search_source=paused_search_source,
            paused_search_recorded_at=NOW,
            paused_search_recorded_by_user_id=USER_ID,
            paused_search_last_confirmed_at=NOW,
        )
    return lead


def _crms_event(content: str) -> CrmConversationEvent:
    return CrmConversationEvent(
        crm_conversation_event_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        crm_activity_id=f"act-{content[:10]}",
        activity_type="Note",
        direction=CrmConversationEventDirection.INBOUND,
        content=content,
        occurred_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _workspace_llm_config() -> WorkspaceLLMConfig:
    return WorkspaceLLMConfig(
        workspace_id=WORKSPACE_ID,
        openrouter_model="openai/gpt-4o-mini",
    )


def _workflow() -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture:test",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=WorkflowState.PAUSED,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _track_repository() -> FakePausedSearchTrackAdminRepository:
    from app.domain.campaigns import (
        PausedSearchFallbackTimingPolicy,
        PausedSearchReasonMapping,
        PausedSearchTrackFamily,
        PausedSearchTrackVersion,
    )
    from app.domain.campaigns.execution import CampaignVersionStatus
    from app.domain.compliance.contactability import ContactChannel

    return FakePausedSearchTrackAdminRepository(
        mappings=(
            PausedSearchReasonMapping(
                mapping_id=UUID("00000000-0000-0000-0000-000000000009"),
                workspace_id=WORKSPACE_ID,
                reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
                track_id=TRACK_ID,
                track_version_id=TRACK_VERSION_ID,
                created_by_user_id=USER_ID,
                created_at=NOW,
            ),
        ),
        versions=(
            PausedSearchTrackVersion(
                track_version_id=TRACK_VERSION_ID,
                workspace_id=WORKSPACE_ID,
                track_id=TRACK_ID,
                version_number=1,
                status=CampaignVersionStatus.PUBLISHED,
                track_family=PausedSearchTrackFamily.MAINTENANCE,
                enabled=True,
                allowed_channels=(ContactChannel.EMAIL,),
                default_for_reason_codes=(PausedSearchReasonCode.WAITING_FOR_RATES,),
                fallback_timing_policy=(
                    PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE
                ),
                maintenance_interval_days=90,
                reactivation_window_days=45,
                max_total_touches=2,
                requires_review_before_publish=False,
                created_by_user_id=USER_ID,
                created_at=NOW,
                published_at=NOW,
            ),
        ),
    )


async def test_applies_valid_paused_search_classification() -> None:
    lead = _lead()
    lead_repo = FakeLeadRepository(lead)
    artifact_repo = FakeLeadClassificationArtifactRepository()
    crm_repo = FakeCrmConversationEventRepository()
    llm_repo = FakeWorkspaceLLMConfigRepository(_workspace_llm_config())
    workflow_repo = FakeLeadWorkflowRepository()
    workflow_repo.latest_by_lead[(WORKSPACE_ID, LEAD_ID)] = _workflow()
    signal_outbox_repository = FakeTemporalSignalOutboxRepository()
    client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            pause_reason_code="waiting_for_rates",
            reengagement_not_before="2026-09-01",
            reengagement_window_label="after summer",
            confidence=0.88,
            evidence=["Lead said rates are too high"],
            summary="Waiting for rates.",
        )
    )

    result = await apply_lead_state_classification(
        actor=None,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=crm_repo,
        workspace_llm_config_repository=llm_repo,
        lead_workflow_repository=workflow_repo,
        paused_search_track_repository=_track_repository(),
        temporal_signal_outbox_repository=signal_outbox_repository,
        llm_client=client,
        now=NOW,
    )

    assert result.status == ApplyLeadStateClassificationStatus.APPLIED
    assert result.classification_result is not None
    assert result.classification_result.outcome == LeadStateClassificationOutcome.PAUSED_SEARCH
    assert result.artifact is not None
    assert result.artifact.applied_status == LeadClassificationAppliedStatus.APPLIED
    assert result.artifact.prompt_text == client.requests[0].prompt
    assert result.artifact.raw_llm_response_text == client.text
    assert result.artifact.parsed_llm_response["outcome"] == "paused_search"
    assert result.artifact.input_context["conversation_summary"] is None
    assert result.history_entry is not None
    assert lead_repo.lead is not None
    profile = lead_paused_search_profile(lead_repo.lead)
    assert profile is not None
    assert profile.paused_search_source == PausedSearchSource.AI_CONVERSATION_CLASSIFICATION
    assert profile.pause_reason_code == PausedSearchReasonCode.WAITING_FOR_RATES
    saved_workflow = workflow_repo.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert saved_workflow.paused_search_track_version_id == TRACK_VERSION_ID
    signal_entry = next(iter(signal_outbox_repository.entries.values()))
    assert signal_entry.signal_name == TemporalSignalName.RESCHEDULE_REQUESTED


async def test_rejects_low_confidence_and_leaves_profile_unchanged() -> None:
    lead = _lead()
    lead_repo = FakeLeadRepository(lead)
    artifact_repo = FakeLeadClassificationArtifactRepository()
    crm_repo = FakeCrmConversationEventRepository()
    llm_repo = FakeWorkspaceLLMConfigRepository(_workspace_llm_config())
    client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            pause_reason_code="waiting_for_rates",
            confidence=0.45,
            evidence=["Maybe"],
            summary="Low confidence.",
        )
    )

    result = await apply_lead_state_classification(
        actor=None,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=crm_repo,
        workspace_llm_config_repository=llm_repo,
        llm_client=client,
        now=NOW,
    )

    assert result.status == ApplyLeadStateClassificationStatus.REVIEW
    assert result.artifact is not None
    assert result.artifact.applied_status == LeadClassificationAppliedStatus.REVIEW
    assert result.artifact.raw_llm_response_text == client.text
    assert result.artifact.parsed_llm_response["confidence"] == 0.45
    assert lead_repo.lead is not None
    assert lead_paused_search_profile(lead_repo.lead) is None


async def test_unknown_outcome_becomes_review_hold_artifact() -> None:
    lead = _lead()
    lead_repo = FakeLeadRepository(lead)
    artifact_repo = FakeLeadClassificationArtifactRepository()
    crm_repo = FakeCrmConversationEventRepository()
    llm_repo = FakeWorkspaceLLMConfigRepository(_workspace_llm_config())
    client = _StubLLMClient(
        _classification_json(
            outcome="unknown",
            pause_reason_code=None,
            handoff_reason_code=None,
            confidence=0.93,
            evidence=["Signals conflict between future timing and active interest."],
            summary="No route is a clear safe winner.",
        )
    )

    result = await apply_lead_state_classification(
        actor=None,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=crm_repo,
        workspace_llm_config_repository=llm_repo,
        llm_client=client,
        now=NOW,
    )

    assert result.status == ApplyLeadStateClassificationStatus.REVIEW
    assert result.artifact is not None
    assert result.artifact.outcome == LeadStateClassificationOutcome.REVIEW_HOLD
    assert result.artifact.applied_status == LeadClassificationAppliedStatus.REVIEW
    assert result.artifact.parsed_llm_response["outcome"] == "unknown"
    assert lead_repo.lead is not None
    assert lead_paused_search_profile(lead_repo.lead) is None


async def test_human_operator_profile_blocks_ai_overwrite() -> None:
    lead = _lead(paused_search_source=PausedSearchSource.OPERATOR)
    lead_repo = FakeLeadRepository(lead)
    artifact_repo = FakeLeadClassificationArtifactRepository()
    crm_repo = FakeCrmConversationEventRepository()
    llm_repo = FakeWorkspaceLLMConfigRepository(_workspace_llm_config())
    client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            pause_reason_code="waiting_for_inventory",
            confidence=0.92,
            evidence=["Lead said inventory is low"],
            summary="Now waiting for inventory.",
        )
    )

    result = await apply_lead_state_classification(
        actor=None,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=crm_repo,
        workspace_llm_config_repository=llm_repo,
        llm_client=client,
        now=NOW,
    )

    assert result.status == ApplyLeadStateClassificationStatus.REVIEW
    assert result.artifact is not None
    assert result.artifact.applied_status == LeadClassificationAppliedStatus.REVIEW
    assert result.reasons == ("human_profile_blocks_ai_overwrite",)
    assert lead_repo.lead is not None
    profile = lead_paused_search_profile(lead_repo.lead)
    assert profile is not None
    assert profile.pause_reason_code == PausedSearchReasonCode.WAITING_FOR_RATES


async def test_allow_overwrite_human_state() -> None:
    lead = _lead(paused_search_source=PausedSearchSource.OPERATOR)
    lead_repo = FakeLeadRepository(lead)
    artifact_repo = FakeLeadClassificationArtifactRepository()
    crm_repo = FakeCrmConversationEventRepository()
    llm_repo = FakeWorkspaceLLMConfigRepository(_workspace_llm_config())
    client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            pause_reason_code="waiting_for_inventory",
            confidence=0.92,
            evidence=["Lead said inventory is low"],
            summary="Now waiting for inventory.",
        )
    )

    result = await apply_lead_state_classification(
        actor=None,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=crm_repo,
        workspace_llm_config_repository=llm_repo,
        llm_client=client,
        now=NOW,
        allow_overwrite_human_state=True,
    )

    assert result.status == ApplyLeadStateClassificationStatus.APPLIED
    assert lead_repo.lead is not None
    profile = lead_paused_search_profile(lead_repo.lead)
    assert profile is not None
    assert profile.pause_reason_code == PausedSearchReasonCode.WAITING_FOR_INVENTORY


async def test_dormant_outcome_does_not_write_paused_profile() -> None:
    lead = _lead()
    lead_repo = FakeLeadRepository(lead)
    artifact_repo = FakeLeadClassificationArtifactRepository()
    crm_repo = FakeCrmConversationEventRepository()
    llm_repo = FakeWorkspaceLLMConfigRepository(_workspace_llm_config())
    client = _StubLLMClient(
        _classification_json(
            outcome="dormant",
            confidence=0.85,
            evidence=["Lead went quiet"],
            summary="No reason known.",
        )
    )

    result = await apply_lead_state_classification(
        actor=None,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=crm_repo,
        workspace_llm_config_repository=llm_repo,
        llm_client=client,
        now=NOW,
    )

    assert result.status == ApplyLeadStateClassificationStatus.REVIEW
    assert result.artifact is not None
    assert result.artifact.applied_status == LeadClassificationAppliedStatus.REVIEW
    assert lead_repo.lead is not None
    assert lead_paused_search_profile(lead_repo.lead) is None


async def test_blocked_outcome_records_blocked_artifact_status() -> None:
    lead = _lead()
    lead_repo = FakeLeadRepository(lead)
    artifact_repo = FakeLeadClassificationArtifactRepository()
    crm_repo = FakeCrmConversationEventRepository()
    llm_repo = FakeWorkspaceLLMConfigRepository(_workspace_llm_config())
    client = _StubLLMClient(
        _classification_json(
            outcome="blocked",
            confidence=0.94,
            evidence=["Lead is opted out or human-owned."],
            summary="Automation should stay blocked.",
        )
    )

    result = await apply_lead_state_classification(
        actor=None,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=crm_repo,
        workspace_llm_config_repository=llm_repo,
        llm_client=client,
        now=NOW,
    )

    assert result.status == ApplyLeadStateClassificationStatus.REVIEW
    assert result.artifact is not None
    assert result.artifact.applied_status == LeadClassificationAppliedStatus.BLOCKED
    assert lead_repo.lead is not None
    assert lead_paused_search_profile(lead_repo.lead) is None


async def test_matching_paused_search_profile_is_not_marked_applied() -> None:
    lead = replace(
        _lead(),
        paused_search_active=True,
        pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
        paused_search_source=PausedSearchSource.AI_CONVERSATION_CLASSIFICATION,
        paused_search_recorded_at=NOW,
        paused_search_recorded_by_user_id=None,
        paused_search_last_confirmed_at=NOW,
    )
    lead_repo = FakeLeadRepository(lead)
    artifact_repo = FakeLeadClassificationArtifactRepository()
    crm_repo = FakeCrmConversationEventRepository()
    llm_repo = FakeWorkspaceLLMConfigRepository(_workspace_llm_config())
    workflow_repo = FakeLeadWorkflowRepository()
    workflow_repo.latest_by_lead[(WORKSPACE_ID, LEAD_ID)] = _workflow()
    track_repo = _track_repository()
    client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            pause_reason_code="waiting_for_rates",
            confidence=0.88,
            evidence=["Lead still wants to wait for rates."],
            summary="Paused-search status is unchanged.",
        )
    )

    result = await apply_lead_state_classification(
        actor=None,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=crm_repo,
        workspace_llm_config_repository=llm_repo,
        llm_client=client,
        lead_workflow_repository=workflow_repo,
        paused_search_track_repository=track_repo,
        now=NOW,
    )

    assert result.status == ApplyLeadStateClassificationStatus.UNCHANGED
    assert result.artifact is not None
    assert result.artifact.applied_status == LeadClassificationAppliedStatus.REVIEW
    assert workflow_repo.latest_by_lead[(WORKSPACE_ID, LEAD_ID)].paused_search_track_version_id == (
        TRACK_VERSION_ID
    )


async def test_lead_not_found() -> None:
    lead_repo = FakeLeadRepository(None)
    artifact_repo = FakeLeadClassificationArtifactRepository()
    crm_repo = FakeCrmConversationEventRepository()
    llm_repo = FakeWorkspaceLLMConfigRepository(_workspace_llm_config())
    client = _StubLLMClient(
        _classification_json(outcome="dormant", confidence=0.85, evidence=[], summary="x")
    )

    result = await apply_lead_state_classification(
        actor=None,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=crm_repo,
        workspace_llm_config_repository=llm_repo,
        llm_client=client,
        now=NOW,
    )

    assert result.status == ApplyLeadStateClassificationStatus.NOT_FOUND
