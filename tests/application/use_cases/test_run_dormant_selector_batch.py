import json
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest

from app.application.ports.crm import CanonicalLead, CRMActivity, CRMAgent, CRMClient
from app.application.ports.dormant_candidates import DormantCandidateSelector
from app.application.ports.llm import LLMClient, LLMCompletionRequest, LLMResult
from app.application.use_cases.preflight_digest import (
    PreflightDigestPreparationStatus,
    PreflightVetoPolicy,
    VetoActorRole,
    record_preflight_veto,
)
from app.application.use_cases.run_dormant_selector_batch import (
    DormantSelectorBatchResult,
    DormantSelectorBatchStatus,
    run_dormant_selector_batch,
)
from app.domain.campaigns.execution import CampaignExecutionConfig, CampaignVersionStatus
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchReasonMapping,
    PausedSearchTrackFamily,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import CampaignId, WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SmsComplianceState,
    WorkspaceContactPolicy,
)
from app.domain.leads.canonical import (
    ActivityReliability,
    CanonicalLeadRecord,
    CRMProvider,
    LeadType,
    PausedSearchReasonCode,
    PausedSearchSource,
    lead_paused_search_profile,
)
from app.domain.llm import WorkspaceLLMConfig
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCampaignExecutionRepository,
    FakeCrmConversationEventRepository,
    FakeLeadClassificationArtifactRepository,
    FakeLeadRepository,
    FakeLeadRoutingReviewRepository,
    FakeLeadWorkflowRepository,
    FakeWorkflowTransitionRepository,
    FakeWorkspaceContactPolicyRepository,
    FakeWorkspaceLLMConfigRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeTemporalWorkflowStarter,
)
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
)
from tests.application.use_cases.test_preflight_digest import (
    FakeNotificationProvider,
    FakePreflightDigestRepository,
)

NOW = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
CAMPAIGN_ID = UUID("22222222-2222-2222-2222-222222222222")
CAMPAIGN_VERSION_ID = UUID("33333333-3333-3333-3333-333333333333")
TRACK_ID = UUID("44444444-4444-4444-4444-444444444444")
TRACK_VERSION_ID = UUID("55555555-5555-5555-5555-555555555555")
USER_ID = UUID("66666666-6666-6666-6666-666666666666")


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


class FakeDormantCandidateSelector(DormantCandidateSelector):
    def __init__(self, leads: tuple[CanonicalLeadRecord, ...]) -> None:
        self.leads = leads

    async def select_candidates(
        self,
        *,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
        threshold_days: int,
        limit: int,
        now: datetime,
    ) -> tuple[CanonicalLeadRecord, ...]:
        return self.leads[:limit]


class FakeCRMClient(CRMClient):
    def __init__(self, agent: CRMAgent | None = None) -> None:
        self.agent = agent

    async def get_assigned_agent(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
    ) -> CRMAgent | None:
        return self.agent

    async def get_lead_url(self, workspace_id: UUID, crm_lead_id: str) -> str | None:
        return None

    async def validate_connection(self, workspace_id: UUID) -> bool:
        return True

    async def get_lead(self, workspace_id: UUID, crm_lead_id: str) -> CanonicalLead | None:
        return None

    async def search_leads(
        self,
        workspace_id: UUID,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[CanonicalLead]:
        return []

    async def get_recent_activity(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        limit: int = 50,
    ) -> list[CRMActivity]:
        return []

    async def add_note(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        content: str,
        subject: str | None = None,
    ) -> None:
        return None

    async def add_tag(self, workspace_id: UUID, crm_lead_id: str, tag: str) -> None:
        return None

    async def remove_tag(self, workspace_id: UUID, crm_lead_id: str, tag: str) -> None:
        return None

    async def update_custom_fields(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        fields: dict[str, str],
    ) -> None:
        return None

    async def subscribe_to_events(self, workspace_id: UUID, webhook_url: str) -> None:
        return None

    async def fetch_resource_by_uri(
        self, workspace_id: UUID, uri: str
    ) -> dict[str, object] | None:
        return None


def _lead(
    *,
    lead_id: UUID | None = None,
    has_assigned_agent: bool = True,
    last_meaningful_communication_at: datetime | None = NOW - timedelta(days=90),
) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=lead_id or uuid4(),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id=f"crm-{lead_id or uuid4()}",
        facts_derived_at=NOW,
        source_payload_version="1",
        source_updated_at=NOW,
        assigned_agent_crm_id="agent-1" if has_assigned_agent else None,
        assigned_agent_name_present=has_assigned_agent,
        has_accountable_owner=has_assigned_agent,
        lead_type=LeadType.BUYER,
        primary_email="lead@example.com",
        has_email=True,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        sms_permission_status=ContactPermissionStatus.CONFIRMED,
        do_not_contact=False,
        last_meaningful_communication_at=last_meaningful_communication_at,
        activity_reliability=ActivityReliability.RELIABLE,
    )


def _config(*, preflight_digest_enabled: bool = True) -> CampaignExecutionConfig:
    return CampaignExecutionConfig(
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        workspace_id=WORKSPACE_ID,
        campaign_name="Test Campaign",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(ContactChannel.EMAIL,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="UTC",
        sms_compliance_required=False,
        preflight_digest_enabled=preflight_digest_enabled,
        crm_enrollment_tag=None,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(),
        created_at=NOW,
        published_at=NOW,
    )


def _policy() -> WorkspaceContactPolicy:
    return WorkspaceContactPolicy(
        workspace_id=WORKSPACE_ID,
        sms_compliance_state=SmsComplianceState.APPROVED,
    )


def _workspace_llm_config() -> WorkspaceLLMConfig:
    return WorkspaceLLMConfig(
        workspace_id=WORKSPACE_ID,
        openrouter_model="openai/gpt-4o-mini",
    )


def _classification_json(**kwargs: object) -> str:
    if (
        kwargs.get("outcome") == "human_handoff"
        and "handoff_reason_code" not in kwargs
    ):
        kwargs["handoff_reason_code"] = "human_requested"
    return json.dumps(kwargs)


def _paused_search_track_repository() -> FakePausedSearchTrackAdminRepository:
    return FakePausedSearchTrackAdminRepository(
        mappings=(
            PausedSearchReasonMapping(
                mapping_id=uuid4(),
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
                fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL,
                maintenance_interval_days=365,
                reactivation_window_days=45,
                max_total_touches=3,
                requires_review_before_publish=False,
                created_by_user_id=USER_ID,
                created_at=NOW,
                published_at=NOW,
            ),
        ),
    )


class _Missing:
    pass


_MISSING = _Missing()


async def _run(
    *,
    leads: tuple[CanonicalLeadRecord, ...] = (),
    batch_id: str | None = None,
    config: CampaignExecutionConfig | None | _Missing = _MISSING,
    policy: WorkspaceContactPolicy | None | _Missing = _MISSING,
    preflight_digest_enabled: bool = True,
    crm_agent: CRMAgent | None = None,
    campaign_enrollment_repository: FakeCampaignEnrollmentRepository | None = None,
    lead_repository: FakeLeadRepository | None = None,
    artifact_repository: FakeLeadClassificationArtifactRepository | None = None,
    lead_workflow_repository: FakeLeadWorkflowRepository | None = None,
    notification_provider: FakeNotificationProvider | None = None,
    now: datetime = NOW,
    preflight_digest_repository: FakePreflightDigestRepository | None = None,
    temporal_workflow_starter: FakeTemporalWorkflowStarter | None = None,
    paused_search_track_repository: FakePausedSearchTrackAdminRepository | None = None,
    llm_client: _StubLLMClient | None = None,
    routing_review_repository: FakeLeadRoutingReviewRepository | None = None,
) -> DormantSelectorBatchResult:

    resolved_config: CampaignExecutionConfig | None = (
        _config(preflight_digest_enabled=preflight_digest_enabled)
        if isinstance(config, _Missing)
        else config
    )
    resolved_policy: WorkspaceContactPolicy | None = (
        _policy() if isinstance(policy, _Missing) else policy
    )
    campaign_enrollment_repository = (
        campaign_enrollment_repository or FakeCampaignEnrollmentRepository()
    )
    lead_repository = lead_repository or FakeLeadRepository()
    for lead in leads:
        await lead_repository.upsert(lead)
    artifact_repository = artifact_repository or FakeLeadClassificationArtifactRepository()
    lead_workflow_repository = lead_workflow_repository or FakeLeadWorkflowRepository()
    notification_provider = notification_provider or FakeNotificationProvider()
    preflight_digest_repository = (
        preflight_digest_repository or FakePreflightDigestRepository()
    )
    temporal_workflow_starter = temporal_workflow_starter or FakeTemporalWorkflowStarter()
    llm_client = llm_client or _StubLLMClient(
        _classification_json(
            outcome="dormant",
            confidence=0.86,
            evidence=["Lead has been quiet"],
            summary="No known reason for going quiet.",
        )
    )
    return await run_dormant_selector_batch(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=batch_id,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            config=resolved_config,
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            policy=resolved_policy,
        ),
        dormant_candidate_selector=FakeDormantCandidateSelector(leads),
        campaign_enrollment_repository=campaign_enrollment_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=temporal_workflow_starter,
        preflight_digest_repository=preflight_digest_repository,
        notification_provider=notification_provider,
        crm_client=FakeCRMClient(agent=crm_agent),
        lead_repository=lead_repository,
        paused_search_history_repository=lead_repository,
        artifact_repository=artifact_repository,
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(
            _workspace_llm_config()
        ),
        llm_client=llm_client,
        default_openrouter_model="openai/gpt-4o-mini",
        paused_search_track_repository=paused_search_track_repository,
        temporal_signal_outbox_repository=None,
        routing_review_repository=routing_review_repository,
        now=now,
    )


@pytest.mark.asyncio
async def test_returns_campaign_inactive_when_config_missing() -> None:
    result = await _run(leads=(_lead(),), config=None)
    assert result.status == DormantSelectorBatchStatus.CAMPAIGN_INACTIVE


@pytest.mark.asyncio
async def test_returns_missing_policy_when_policy_missing() -> None:
    result = await _run(leads=(_lead(),), policy=None)
    assert result.status == DormantSelectorBatchStatus.MISSING_CONTACT_POLICY


@pytest.mark.asyncio
async def test_returns_no_candidates_when_selector_empty() -> None:
    result = await _run(leads=())
    assert result.status == DormantSelectorBatchStatus.NO_CANDIDATES


@pytest.mark.asyncio
async def test_starts_unassigned_lead_without_preflight_digest() -> None:
    lead = _lead(has_assigned_agent=False)
    result = await _run(leads=(lead,), preflight_digest_enabled=True)

    assert result.status == DormantSelectorBatchStatus.COMPLETED
    assert result.selected_count == 1
    assert result.started_count == 1
    assert result.paused_search_started_count == 0
    assert result.started_lead_ids == (lead.lead_id,)
    assert result.digest_status == PreflightDigestPreparationStatus.NOT_REQUIRED.value


@pytest.mark.asyncio
async def test_issues_preflight_digest_and_holds_back_assigned_lead() -> None:
    lead = _lead(has_assigned_agent=True)
    agent = CRMAgent(crm_agent_id="agent-1", name="Agent", email="agent@example.com")
    result = await _run(leads=(lead,), crm_agent=agent)

    assert result.status == DormantSelectorBatchStatus.COMPLETED
    assert result.selected_count == 0
    assert result.held_back_count == 1
    assert result.started_count == 0
    assert result.paused_search_started_count == 0
    assert result.digest_status == PreflightDigestPreparationStatus.ISSUED.value
    assert result.veto_window_expires_at is not None


@pytest.mark.asyncio
async def test_paused_search_candidate_is_classified_and_not_started_as_dormant() -> None:
    lead = _lead(has_assigned_agent=False)
    lead_repository = FakeLeadRepository()
    artifact_repository = FakeLeadClassificationArtifactRepository()
    llm_client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            pause_reason_code="waiting_for_rates",
            reengagement_not_before="2027-07-01",
            reengagement_window_label="next summer",
            confidence=0.91,
            evidence=["Lead said they are waiting for rates"],
            summary="Lead is waiting for rates before restarting the search.",
        )
    )

    result = await _run(
        leads=(lead,),
        preflight_digest_enabled=False,
        lead_repository=lead_repository,
        artifact_repository=artifact_repository,
        llm_client=llm_client,
    )

    assert result.status == DormantSelectorBatchStatus.COMPLETED
    assert result.started_count == 0
    assert result.paused_search_started_count == 0
    assert result.started_lead_ids == ()
    assert artifact_repository.saved[0].outcome.value == "paused_search"
    saved_lead = await lead_repository.get_by_id(WORKSPACE_ID, lead.lead_id)
    assert saved_lead is not None
    profile = lead_paused_search_profile(saved_lead)
    assert profile is not None
    assert profile.pause_reason_code == PausedSearchReasonCode.WAITING_FOR_RATES


@pytest.mark.asyncio
async def test_paused_search_candidate_starts_reason_specific_track_when_mapping_exists() -> None:
    lead = _lead(has_assigned_agent=False)
    lead_repository = FakeLeadRepository()
    lead_workflow_repository = FakeLeadWorkflowRepository()
    temporal_workflow_starter = FakeTemporalWorkflowStarter()
    llm_client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            pause_reason_code="waiting_for_rates",
            confidence=0.91,
            evidence=["Lead said rates need to improve"],
            summary="Lead is waiting for rates before restarting the search.",
        )
    )

    result = await _run(
        leads=(lead,),
        preflight_digest_enabled=False,
        lead_repository=lead_repository,
        lead_workflow_repository=lead_workflow_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        paused_search_track_repository=_paused_search_track_repository(),
        llm_client=llm_client,
    )

    assert result.status == DormantSelectorBatchStatus.COMPLETED
    assert result.selected_count == 1
    assert result.started_count == 0
    assert result.paused_search_started_count == 1
    assert result.started_lead_ids == (lead.lead_id,)
    assert temporal_workflow_starter.calls
    saved_workflow = lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, lead.lead_id)]
    assert saved_workflow.paused_search_track_version_id == TRACK_VERSION_ID


@pytest.mark.asyncio
async def test_paused_search_profile_with_dormant_classification_is_paused_search() -> None:
    lead = _lead(has_assigned_agent=False)
    lead = replace(
        lead,
        paused_search_active=True,
        pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
        paused_search_source=PausedSearchSource.AI_CONVERSATION_CLASSIFICATION,
    )
    lead_repository = FakeLeadRepository()
    lead_workflow_repository = FakeLeadWorkflowRepository()
    temporal_workflow_starter = FakeTemporalWorkflowStarter()
    llm_client = _StubLLMClient(
        _classification_json(
            outcome="dormant",
            confidence=0.86,
            evidence=["No recent replies."],
            summary="Lead appears dormant.",
        )
    )

    result = await _run(
        leads=(lead,),
        preflight_digest_enabled=False,
        lead_repository=lead_repository,
        lead_workflow_repository=lead_workflow_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        paused_search_track_repository=_paused_search_track_repository(),
        llm_client=llm_client,
    )

    assert result.status == DormantSelectorBatchStatus.COMPLETED
    assert result.selected_count == 1
    assert result.started_count == 0
    assert result.paused_search_started_count == 1
    assert result.started_lead_ids == (lead.lead_id,)
    assert temporal_workflow_starter.calls
    saved_workflow = lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, lead.lead_id)]
    assert saved_workflow.paused_search_track_version_id == TRACK_VERSION_ID


@pytest.mark.asyncio
async def test_existing_paused_search_profile_with_handoff_classification_is_not_started() -> None:
    lead = _lead(has_assigned_agent=False)
    lead = replace(
        lead,
        paused_search_active=True,
        pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
        paused_search_source=PausedSearchSource.AI_CONVERSATION_CLASSIFICATION,
    )
    lead_repository = FakeLeadRepository()
    lead_workflow_repository = FakeLeadWorkflowRepository()
    temporal_workflow_starter = FakeTemporalWorkflowStarter()
    llm_client = _StubLLMClient(
        _classification_json(
            outcome="human_handoff",
            confidence=0.91,
            evidence=["Lead asked to speak with an agent."],
            summary="Lead wants human follow-up.",
        )
    )

    result = await _run(
        leads=(lead,),
        preflight_digest_enabled=False,
        lead_repository=lead_repository,
        lead_workflow_repository=lead_workflow_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        paused_search_track_repository=_paused_search_track_repository(),
        llm_client=llm_client,
    )

    assert result.status == DormantSelectorBatchStatus.COMPLETED
    assert result.selected_count == 0
    assert result.started_count == 0
    assert result.paused_search_started_count == 0
    assert len(temporal_workflow_starter.calls) == 0
    assert lead_workflow_repository.latest_by_lead == {}


@pytest.mark.asyncio
async def test_review_hold_candidate_is_not_started_as_dormant() -> None:
    lead = _lead(has_assigned_agent=False)
    llm_client = _StubLLMClient(
        _classification_json(
            outcome="review_hold",
            confidence=0.92,
            evidence=["Conversation is contradictory"],
            summary="Needs human review before outreach.",
        )
    )

    result = await _run(
        leads=(lead,),
        preflight_digest_enabled=False,
        llm_client=llm_client,
    )

    assert result.status == DormantSelectorBatchStatus.COMPLETED
    assert result.selected_count == 0
    assert result.started_count == 0
    assert result.paused_search_started_count == 0


@pytest.mark.asyncio
async def test_review_hold_candidate_records_pending_routing_review() -> None:
    lead = _lead(has_assigned_agent=False)
    artifact_repository = FakeLeadClassificationArtifactRepository()
    routing_review_repository = FakeLeadRoutingReviewRepository()
    llm_client = _StubLLMClient(
        _classification_json(
            outcome="review_hold",
            confidence=0.92,
            evidence=["Conversation is contradictory"],
            summary="Needs human review before outreach.",
        )
    )

    result = await _run(
        leads=(lead,),
        preflight_digest_enabled=False,
        artifact_repository=artifact_repository,
        routing_review_repository=routing_review_repository,
        llm_client=llm_client,
    )

    assert result.status == DormantSelectorBatchStatus.COMPLETED
    assert result.selected_count == 0
    assert result.started_count == 0
    assert result.paused_search_started_count == 0
    assert len(artifact_repository.saved) == 1
    assert len(routing_review_repository.saved) == 1
    assert (
        routing_review_repository.saved[0].artifact_id
        == artifact_repository.saved[0].artifact_id
    )
    assert routing_review_repository.saved[0].reason_codes == ("ai_classified_review_hold",)


@pytest.mark.asyncio
async def test_blocked_candidate_is_not_started_as_dormant() -> None:
    lead = replace(_lead(has_assigned_agent=False), do_not_contact=True)
    lead_workflow_repository = FakeLeadWorkflowRepository()
    temporal_workflow_starter = FakeTemporalWorkflowStarter()

    result = await _run(
        leads=(lead,),
        preflight_digest_enabled=False,
        lead_workflow_repository=lead_workflow_repository,
        temporal_workflow_starter=temporal_workflow_starter,
    )

    assert result.status == DormantSelectorBatchStatus.COMPLETED
    assert result.selected_count == 0
    assert result.started_count == 0
    assert result.paused_search_started_count == 0
    assert result.started_lead_ids == ()
    assert len(temporal_workflow_starter.calls) == 0
    assert lead_workflow_repository.latest_by_lead == {}


@pytest.mark.asyncio
async def test_dormant_candidate_with_missing_last_communication_is_not_started() -> None:
    lead = _lead(
        has_assigned_agent=False,
        last_meaningful_communication_at=None,
    )

    result = await _run(leads=(lead,), preflight_digest_enabled=False)

    assert result.status == DormantSelectorBatchStatus.COMPLETED
    assert result.selected_count == 0
    assert result.started_count == 0
    assert result.held_back_count == 0
    assert result.paused_search_started_count == 0


@pytest.mark.asyncio
async def test_assigned_paused_search_candidate_issues_digest_before_start() -> None:
    lead = _lead(has_assigned_agent=True)
    agent = CRMAgent(crm_agent_id="agent-1", name="Agent", email="agent@example.com")
    digest_repository = FakePreflightDigestRepository()
    temporal_workflow_starter = FakeTemporalWorkflowStarter()
    llm_client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            pause_reason_code="waiting_for_rates",
            confidence=0.91,
            evidence=["Lead said rates need to improve"],
            summary="Lead is waiting for rates before restarting the search.",
        )
    )

    result = await _run(
        batch_id="paused-digest-batch",
        leads=(lead,),
        crm_agent=agent,
        llm_client=llm_client,
        paused_search_track_repository=_paused_search_track_repository(),
        preflight_digest_repository=digest_repository,
        temporal_workflow_starter=temporal_workflow_starter,
    )

    digest = await digest_repository.get_digest(
        WORKSPACE_ID,
        CAMPAIGN_ID,
        "paused-digest-batch",
    )

    assert result.status == DormantSelectorBatchStatus.COMPLETED
    assert result.selected_count == 0
    assert result.held_back_count == 1
    assert result.started_count == 0
    assert result.paused_search_started_count == 0
    assert result.digest_status == PreflightDigestPreparationStatus.ISSUED.value
    assert digest is not None
    assert [entry.lead_id for entry in digest.entries] == [lead.lead_id]
    assert temporal_workflow_starter.calls == []


@pytest.mark.asyncio
async def test_vetoed_assigned_paused_search_candidate_does_not_start_after_window() -> None:
    lead = _lead(has_assigned_agent=True)
    agent = CRMAgent(crm_agent_id="agent-1", name="Agent", email="agent@example.com")
    digest_repository = FakePreflightDigestRepository()
    temporal_workflow_starter = FakeTemporalWorkflowStarter()
    llm_client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            pause_reason_code="waiting_for_rates",
            confidence=0.91,
            evidence=["Lead said rates need to improve"],
            summary="Lead is waiting for rates before restarting the search.",
        )
    )

    first_result = await _run(
        batch_id="paused-veto-batch",
        leads=(lead,),
        crm_agent=agent,
        llm_client=llm_client,
        paused_search_track_repository=_paused_search_track_repository(),
        preflight_digest_repository=digest_repository,
        temporal_workflow_starter=temporal_workflow_starter,
    )

    assert first_result.digest_status == PreflightDigestPreparationStatus.ISSUED.value

    veto_result = await record_preflight_veto(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id="paused-veto-batch",
        lead_id=lead.lead_id,
        actor_id="agent-1",
        actor_role=VetoActorRole.ASSIGNED_AGENT,
        repository=digest_repository,
        policy=PreflightVetoPolicy(),
        now=NOW + timedelta(hours=1),
    )

    second_result = await _run(
        batch_id="paused-veto-batch",
        leads=(lead,),
        crm_agent=agent,
        llm_client=llm_client,
        now=NOW + timedelta(hours=25),
        paused_search_track_repository=_paused_search_track_repository(),
        preflight_digest_repository=digest_repository,
        temporal_workflow_starter=temporal_workflow_starter,
    )

    assert veto_result.recorded is True
    assert second_result.selected_count == 0
    assert second_result.held_back_count == 1
    assert second_result.paused_search_started_count == 0
    assert temporal_workflow_starter.calls == []


@pytest.mark.asyncio
async def test_assigned_paused_search_candidate_starts_after_digest_window() -> None:
    lead = _lead(has_assigned_agent=True)
    agent = CRMAgent(crm_agent_id="agent-1", name="Agent", email="agent@example.com")
    digest_repository = FakePreflightDigestRepository()
    temporal_workflow_starter = FakeTemporalWorkflowStarter()
    lead_workflow_repository = FakeLeadWorkflowRepository()
    llm_client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            pause_reason_code="waiting_for_rates",
            confidence=0.91,
            evidence=["Lead said rates need to improve"],
            summary="Lead is waiting for rates before restarting the search.",
        )
    )

    first_result = await _run(
        batch_id="paused-start-batch",
        leads=(lead,),
        crm_agent=agent,
        llm_client=llm_client,
        paused_search_track_repository=_paused_search_track_repository(),
        preflight_digest_repository=digest_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        lead_workflow_repository=lead_workflow_repository,
    )

    second_result = await _run(
        batch_id="paused-start-batch",
        leads=(lead,),
        crm_agent=agent,
        llm_client=llm_client,
        now=NOW + timedelta(hours=25),
        paused_search_track_repository=_paused_search_track_repository(),
        preflight_digest_repository=digest_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        lead_workflow_repository=lead_workflow_repository,
    )

    assert first_result.digest_status == PreflightDigestPreparationStatus.ISSUED.value
    assert second_result.selected_count == 1
    assert second_result.started_count == 0
    assert second_result.paused_search_started_count == 1
    assert second_result.started_lead_ids == (lead.lead_id,)
    assert temporal_workflow_starter.calls


@pytest.mark.asyncio
async def test_paused_search_and_dormant_candidates_share_daily_cap_ordering() -> None:
    paused_search_lead = replace(
        _lead(has_assigned_agent=False),
        paused_search_active=True,
        pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
        paused_search_source=PausedSearchSource.AI_CONVERSATION_CLASSIFICATION,
    )
    dormant_lead = _lead(has_assigned_agent=False)
    temporal_workflow_starter = FakeTemporalWorkflowStarter()
    lead_workflow_repository = FakeLeadWorkflowRepository()

    result = await _run(
        leads=(paused_search_lead, dormant_lead),
        config=replace(_config(preflight_digest_enabled=False), daily_start_cap=1),
        preflight_digest_enabled=False,
        lead_workflow_repository=lead_workflow_repository,
        paused_search_track_repository=_paused_search_track_repository(),
        temporal_workflow_starter=temporal_workflow_starter,
        llm_client=_StubLLMClient(
            _classification_json(
                outcome="dormant",
                confidence=0.86,
                evidence=["No recent replies."],
                summary="Lead appears dormant.",
            )
        ),
    )

    assert result.status == DormantSelectorBatchStatus.COMPLETED
    assert result.selected_count == 1
    assert result.held_back_count == 1
    assert result.started_count == 0
    assert result.paused_search_started_count == 1
    assert result.started_lead_ids == (paused_search_lead.lead_id,)
    assert temporal_workflow_starter.calls
