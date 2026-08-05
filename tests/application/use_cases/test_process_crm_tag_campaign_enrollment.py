from datetime import UTC, datetime, time
from uuid import UUID, uuid4

import pytest

from app.application.ports.llm import LLMClient, LLMCompletionRequest, LLMResult
from app.application.use_cases.complete_handoff import HandoffCompletionStatus
from app.application.use_cases.process_crm_tag_campaign_enrollment import (
    CRMTagCampaignEnrollmentStatus,
    process_crm_tag_campaign_enrollment,
)
from app.domain.campaigns import (
    CampaignStatus,
    CampaignVersionStatus,
    PausedSearchFallbackTimingPolicy,
    PausedSearchReasonMapping,
    PausedSearchTrack,
    PausedSearchTrackFamily,
    PausedSearchTrackStatus,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.execution import CampaignCadenceStep, CampaignExecutionConfig
from app.domain.common.ids import PausedSearchTrackVersionId
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SmsComplianceState,
    WorkspaceContactPolicy,
)
from app.domain.conversations import (
    CrmConversationEvent,
    CrmConversationEventDirection,
    HandoffReasonCode,
    WorkspaceHandoffConfig,
)
from app.domain.events import DomainEventType
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
    LeadStateClassificationOutcome,
    PausedSearchReasonCode,
    PausedSearchSource,
)
from app.domain.workflows import WorkflowState
from app.domain.workspace_automation import WorkspaceOperationalControl
from tests.application.use_cases._campaign_admin_fakes import FakeEventBus
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCampaignExecutionRepository,
    FakeClassificationLLMClient,
    FakeCrmConversationEventRepository,
    FakeLeadClassificationArtifactRepository,
    FakeLeadRepository,
    FakeLeadRoutingReviewRepository,
    FakeWorkspaceContactPolicyRepository,
    FakeWorkspaceLLMConfigRepository,
    FakeWorkspaceOperationalControlRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeLeadWorkflowRepository,
    FakeTemporalWorkflowStarter,
    FakeWorkflowTransitionRepository,
)
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
    FakePausedSearchTrackAssignmentRepository,
)
from tests.application.use_cases.test_complete_handoff import (
    FakeCRMClient as FakeHandoffCRMClient,
)
from tests.application.use_cases.test_complete_handoff import (
    FakeHandoffCompletionRepository,
    FakeNotificationProvider,
    FakeWorkspaceHandoffConfigRepository,
)
from tests.application.use_cases.test_process_inbound_message_event import FakeHandoffRepository

NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
LEAD_ID = UUID("22222222-2222-2222-2222-222222222222")
CAMPAIGN_ID = UUID("33333333-3333-3333-3333-333333333333")
CAMPAIGN_ID_2 = UUID("44444444-4444-4444-4444-444444444444")
VERSION_ID = UUID("55555555-5555-5555-5555-555555555555")
VERSION_ID_2 = UUID("66666666-6666-6666-6666-666666666666")
STEP_ID = UUID("77777777-7777-7777-7777-777777777777")
TRACK_VERSION_ID = UUID("88888888-8888-8888-8888-888888888888")
TIMING_TRACK_VERSION_ID = UUID("99999999-9999-9999-9999-999999999999")
TIMING_TRACK_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.mark.asyncio
async def test_starts_matching_campaign_from_configured_crm_tag() -> None:
    commit_calls: list[str] = []
    temporal = FakeTemporalWorkflowStarter()
    lead_repo = FakeLeadRepository()

    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=await _lead(tags=("configured_tag",), repository=lead_repo),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(
                campaign_id=CAMPAIGN_ID,
                version_id=VERSION_ID,
                crm_enrollment_tag="configured_tag",
            )
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=FakeCampaignEnrollmentRepository(),
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=temporal,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        artifact_repository=FakeLeadClassificationArtifactRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(outcome="dormant"),
        event_bus=FakeEventBus(),
        workspace_operational_control_repository=FakeWorkspaceOperationalControlRepository(None),
        commit=lambda: _record_commit(commit_calls),
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.STARTED
    assert result.campaign_id == CAMPAIGN_ID
    assert result.matched_tag == "configured_tag"
    assert result.route == "dormant"
    assert commit_calls == ["commit"]
    assert len(temporal.calls) == 1


@pytest.mark.asyncio
async def test_returns_no_matching_campaign_when_tags_do_not_match_admin_config() -> None:
    lead_repo = FakeLeadRepository()
    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=await _lead(tags=("some_other_tag",), repository=lead_repo),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(
                campaign_id=CAMPAIGN_ID,
                version_id=VERSION_ID,
                crm_enrollment_tag="configured_tag",
            )
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=FakeCampaignEnrollmentRepository(),
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=FakeTemporalWorkflowStarter(),
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        artifact_repository=FakeLeadClassificationArtifactRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(outcome="dormant"),
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.NO_MATCHING_CAMPAIGN
    assert result.campaign_id is None


@pytest.mark.asyncio
async def test_chooses_only_the_matching_campaign_when_multiple_are_active() -> None:
    configs = (
        _config(
            campaign_id=CAMPAIGN_ID,
            version_id=VERSION_ID,
            crm_enrollment_tag="non_matching",
        ),
        _config(
            campaign_id=CAMPAIGN_ID_2,
            version_id=VERSION_ID_2,
            crm_enrollment_tag="configured_tag",
        ),
    )
    enrollments = FakeCampaignEnrollmentRepository()
    lead_repo = FakeLeadRepository()

    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=await _lead(tags=("configured_tag",), repository=lead_repo),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(configs),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=enrollments,
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=FakeTemporalWorkflowStarter(),
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        artifact_repository=FakeLeadClassificationArtifactRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(outcome="dormant"),
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.STARTED
    assert result.campaign_id == CAMPAIGN_ID_2
    assert result.route == "dormant"
    assert len(enrollments.enrollments) == 1
    saved = next(iter(enrollments.enrollments.values()))
    assert saved.campaign_id == CAMPAIGN_ID_2


@pytest.mark.asyncio
async def test_routes_to_paused_search_when_existing_profile_beats_dormant() -> None:
    lead_repo = FakeLeadRepository()
    artifact_repo = FakeLeadClassificationArtifactRepository()
    workflow_repo = FakeLeadWorkflowRepository()
    temporal = FakeTemporalWorkflowStarter()
    enrollments = FakeCampaignEnrollmentRepository()
    transitions = FakeWorkflowTransitionRepository()

    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=await _lead(tags=("configured_tag",), repository=lead_repo, paused_search_active=True),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(
                campaign_id=CAMPAIGN_ID,
                version_id=VERSION_ID,
                crm_enrollment_tag="configured_tag",
            )
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=enrollments,
        lead_workflow_repository=workflow_repo,
        workflow_transition_repository=transitions,
        temporal_workflow_starter=temporal,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=_paused_search_track_repository(),
        paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(outcome="dormant"),
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.STARTED
    assert result.route == "paused_search"
    assert len(artifact_repo.saved) == 1
    assert artifact_repo.saved[0].outcome.value == "dormant"
    assert len(enrollments.enrollments) == 1
    assert len(temporal.calls) == 1
    workflow = workflow_repo.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert workflow.state == WorkflowState.ACTIVE_NURTURE
    assert workflow.paused_search_track_version_id == TRACK_VERSION_ID
    transition = next(iter(transitions.transitions.values()))
    assert transition.to_state == WorkflowState.ACTIVE_NURTURE
    assert transition.metadata["route"] == "paused_search"


@pytest.mark.asyncio
async def test_paused_search_enrollment_holds_when_recurring_flag_is_disabled() -> None:
    lead_repo = FakeLeadRepository()
    routing_review_repository = FakeLeadRoutingReviewRepository()

    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=await _lead(tags=("configured_tag",), repository=lead_repo, paused_search_active=True),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(
                campaign_id=CAMPAIGN_ID,
                version_id=VERSION_ID,
                crm_enrollment_tag="configured_tag",
            )
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=FakeCampaignEnrollmentRepository(),
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=FakeTemporalWorkflowStarter(),
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=_paused_search_track_repository(),
        paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
        artifact_repository=FakeLeadClassificationArtifactRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(outcome="dormant"),
        workspace_operational_control_repository=FakeWorkspaceOperationalControlRepository(
            WorkspaceOperationalControl(workspace_id=WORKSPACE_ID)
        ),
        routing_review_repository=routing_review_repository,
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.REVIEW_HOLD
    assert result.route == "review_hold"
    assert "recurring_paused_search_disabled" in result.reason_codes


@pytest.mark.asyncio
async def test_fresh_human_handoff_wins_over_existing_paused_search_profile() -> None:
    lead_repo = FakeLeadRepository()
    artifact_repo = FakeLeadClassificationArtifactRepository()
    workflow_repo = FakeLeadWorkflowRepository()
    temporal = FakeTemporalWorkflowStarter()
    enrollments = FakeCampaignEnrollmentRepository()
    transitions = FakeWorkflowTransitionRepository()

    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=await _lead(tags=("configured_tag",), repository=lead_repo, paused_search_active=True),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(
                campaign_id=CAMPAIGN_ID,
                version_id=VERSION_ID,
                crm_enrollment_tag="configured_tag",
            )
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=enrollments,
        lead_workflow_repository=workflow_repo,
        workflow_transition_repository=transitions,
        temporal_workflow_starter=temporal,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=_paused_search_track_repository(),
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=FakeCrmConversationEventRepository(
            events=(_crm_event("Lead asked for an agent to help today."),)
        ),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(outcome="human_handoff"),
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.HUMAN_HANDOFF
    assert result.route == "human_handoff"
    assert len(artifact_repo.saved) == 1
    assert artifact_repo.saved[0].outcome.value == "human_handoff"
    assert len(enrollments.enrollments) == 0
    assert len(temporal.calls) == 0


@pytest.mark.asyncio
async def test_fresh_blocked_wins_over_existing_paused_search_profile() -> None:
    lead_repo = FakeLeadRepository()
    artifact_repo = FakeLeadClassificationArtifactRepository()
    workflow_repo = FakeLeadWorkflowRepository()
    temporal = FakeTemporalWorkflowStarter()
    enrollments = FakeCampaignEnrollmentRepository()
    transitions = FakeWorkflowTransitionRepository()

    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=await _lead(tags=("configured_tag",), repository=lead_repo, paused_search_active=True),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(
                campaign_id=CAMPAIGN_ID,
                version_id=VERSION_ID,
                crm_enrollment_tag="configured_tag",
            )
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=enrollments,
        lead_workflow_repository=workflow_repo,
        workflow_transition_repository=transitions,
        temporal_workflow_starter=temporal,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=_paused_search_track_repository(),
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(outcome="blocked"),
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.BLOCKED
    assert result.route == "blocked"
    assert len(artifact_repo.saved) == 1
    assert artifact_repo.saved[0].outcome.value == "blocked"
    assert len(enrollments.enrollments) == 0
    assert len(temporal.calls) == 0


@pytest.mark.asyncio
async def test_duplicate_paused_search_tag_event_returns_already_enrolled() -> None:
    lead_repo = FakeLeadRepository()
    workflow_repo = FakeLeadWorkflowRepository()
    enrollments = FakeCampaignEnrollmentRepository()
    temporal = FakeTemporalWorkflowStarter()
    lead = await _lead(tags=("configured_tag",), repository=lead_repo, paused_search_active=True)
    config_repository = FakeCampaignExecutionRepository(
        _config(
            campaign_id=CAMPAIGN_ID,
            version_id=VERSION_ID,
            crm_enrollment_tag="configured_tag",
        )
    )
    contact_policy_repository = FakeWorkspaceContactPolicyRepository(_contact_policy())
    transition_repository = FakeWorkflowTransitionRepository()
    track_repository = _paused_search_track_repository()
    artifact_repository = FakeLeadClassificationArtifactRepository()
    conversation_repository = FakeCrmConversationEventRepository()
    llm_config_repository = FakeWorkspaceLLMConfigRepository()
    llm_client = FakeClassificationLLMClient(outcome="dormant")

    first_result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=lead,
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=config_repository,
        workspace_contact_policy_repository=contact_policy_repository,
        campaign_enrollment_repository=enrollments,
        lead_workflow_repository=workflow_repo,
        workflow_transition_repository=transition_repository,
        temporal_workflow_starter=temporal,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=track_repository,
        paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
        artifact_repository=artifact_repository,
        crm_conversation_event_repository=conversation_repository,
        workspace_llm_config_repository=llm_config_repository,
        llm_client=llm_client,
    )
    second_result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=lead,
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=config_repository,
        workspace_contact_policy_repository=contact_policy_repository,
        campaign_enrollment_repository=enrollments,
        lead_workflow_repository=workflow_repo,
        workflow_transition_repository=transition_repository,
        temporal_workflow_starter=temporal,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=track_repository,
        paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
        artifact_repository=artifact_repository,
        crm_conversation_event_repository=conversation_repository,
        workspace_llm_config_repository=llm_config_repository,
        llm_client=llm_client,
    )

    assert first_result.status == CRMTagCampaignEnrollmentStatus.STARTED
    assert second_result.status == CRMTagCampaignEnrollmentStatus.ALREADY_ENROLLED
    assert len(enrollments.enrollments) == 1
    assert len(temporal.calls) == 1


@pytest.mark.asyncio
async def test_review_holds_paused_search_when_no_published_track_mapping_exists() -> None:
    lead_repo = FakeLeadRepository()
    routing_review_repository = FakeLeadRoutingReviewRepository()

    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=await _lead(tags=("configured_tag",), repository=lead_repo, paused_search_active=True),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(
                campaign_id=CAMPAIGN_ID,
                version_id=VERSION_ID,
                crm_enrollment_tag="configured_tag",
            )
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=FakeCampaignEnrollmentRepository(),
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=FakeTemporalWorkflowStarter(),
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        artifact_repository=FakeLeadClassificationArtifactRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(outcome="dormant"),
        routing_review_repository=routing_review_repository,
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.REVIEW_HOLD
    assert result.route == "review_hold"
    assert "paused_search_track_assignment_unavailable" in result.reason_codes
    assert routing_review_repository.saved[0].reason_codes == (
        "existing_paused_search_profile",
        "paused_search_track_assignment_unavailable",
    )


@pytest.mark.asyncio
async def test_creates_and_completes_human_handoff_without_starting_workflow() -> None:
    lead_repo = FakeLeadRepository()
    enrollments = FakeCampaignEnrollmentRepository()
    artifact_repo = FakeLeadClassificationArtifactRepository()
    workflow_repo = FakeLeadWorkflowRepository()
    temporal = FakeTemporalWorkflowStarter()
    handoff_repo = FakeHandoffRepository()
    completion_repo = FakeHandoffCompletionRepository()
    notification_provider = FakeNotificationProvider()
    crm_client = FakeHandoffCRMClient(lead_tags=("needs_agent_review",))
    event_bus = FakeEventBus()

    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=await _lead(tags=("configured_tag",), repository=lead_repo),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(
                campaign_id=CAMPAIGN_ID,
                version_id=VERSION_ID,
                crm_enrollment_tag="configured_tag",
            )
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=enrollments,
        lead_workflow_repository=workflow_repo,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=temporal,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=FakeCrmConversationEventRepository(
            events=(
                _crm_event(
                    "Can someone call me about this listing?",
                    direction=CrmConversationEventDirection.INBOUND,
                ),
            )
        ),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(
            outcome="human_handoff",
            handoff_reason_code="specific_property_or_advice",
            summary="Lead needs an agent for listing advice.",
        ),
        handoff_repository=handoff_repo,
        handoff_completion_repository=completion_repo,
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            _workspace_handoff_config()
        ),
        crm_client=crm_client,
        notification_provider=notification_provider,
        event_bus=event_bus,
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.HUMAN_HANDOFF
    assert result.route == "human_handoff"
    assert result.reason_codes == ("ai_classified_human_handoff",)
    assert result.handoff_id is not None
    assert result.handoff_completion_status == HandoffCompletionStatus.COMPLETED
    assert len(artifact_repo.saved) == 1
    assert {handoff.handoff_id for handoff in handoff_repo.saved} == {result.handoff_id}
    assert handoff_repo.saved[0].reason_code == HandoffReasonCode.SPECIFIC_PROPERTY_OR_ADVICE
    assert handoff_repo.saved[0].latest_inbound_text == "Can someone call me about this listing?"
    assert handoff_repo.saved[-1].notified_at == NOW
    assert completion_repo.record is not None and completion_repo.record.completed_at == NOW
    assert len(notification_provider.notifications) == 1
    assert crm_client.tag == "human_handoff_required"
    assert crm_client.fields["handoff_status"] == "required"
    assert crm_client.note is not None
    assert len(event_bus.events) == 1
    assert event_bus.events[0].event_type == DomainEventType.HANDOFF_CREATED
    assert enrollments.enrollments == {}
    assert len(temporal.calls) == 0
    assert (WORKSPACE_ID, LEAD_ID) not in workflow_repo.latest_by_lead


@pytest.mark.asyncio
async def test_repeated_human_handoff_reuses_existing_open_handoff() -> None:
    lead_repo = FakeLeadRepository()
    handoff_repo = FakeHandoffRepository()
    completion_repo = FakeHandoffCompletionRepository()
    notification_provider = FakeNotificationProvider()
    crm_client = FakeHandoffCRMClient()

    for _ in range(2):
        result = await process_crm_tag_campaign_enrollment(
            workspace_id=WORKSPACE_ID,
            lead=await _lead(tags=("configured_tag",), repository=lead_repo),
            observed_at=NOW,
            now=NOW,
            campaign_execution_repository=FakeCampaignExecutionRepository(
                _config(
                    campaign_id=CAMPAIGN_ID,
                    version_id=VERSION_ID,
                    crm_enrollment_tag="configured_tag",
                )
            ),
            workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
                _contact_policy()
            ),
            campaign_enrollment_repository=FakeCampaignEnrollmentRepository(),
            lead_workflow_repository=FakeLeadWorkflowRepository(),
            workflow_transition_repository=FakeWorkflowTransitionRepository(),
            temporal_workflow_starter=FakeTemporalWorkflowStarter(),
            lead_repository=lead_repo,
            paused_search_history_repository=lead_repo,
            paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
            artifact_repository=FakeLeadClassificationArtifactRepository(),
            crm_conversation_event_repository=FakeCrmConversationEventRepository(
                events=(_crm_event("Please have an agent reach out."),)
            ),
            workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
            llm_client=FakeClassificationLLMClient(
                outcome="human_handoff",
                handoff_reason_code="human_requested",
            ),
            handoff_repository=handoff_repo,
            handoff_completion_repository=completion_repo,
            workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
                _workspace_handoff_config()
            ),
            crm_client=crm_client,
            notification_provider=notification_provider,
        )

    assert result.status == CRMTagCampaignEnrollmentStatus.HUMAN_HANDOFF
    assert result.handoff_completion_status == HandoffCompletionStatus.ALREADY_COMPLETED
    assert {handoff.handoff_id for handoff in handoff_repo.saved} == {result.handoff_id}
    assert len(notification_provider.notifications) == 1


@pytest.mark.asyncio
async def test_human_handoff_completion_failure_is_reported_without_starting_workflow() -> None:
    lead_repo = FakeLeadRepository()
    artifact_repo = FakeLeadClassificationArtifactRepository()
    workflow_repo = FakeLeadWorkflowRepository()
    temporal = FakeTemporalWorkflowStarter()
    notification_provider = FakeNotificationProvider()
    notification_provider.handoff_exception = RuntimeError("smtp unavailable")
    handoff_repo = FakeHandoffRepository()

    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=await _lead(tags=("configured_tag",), repository=lead_repo),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(
                campaign_id=CAMPAIGN_ID,
                version_id=VERSION_ID,
                crm_enrollment_tag="configured_tag",
            )
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=FakeCampaignEnrollmentRepository(),
        lead_workflow_repository=workflow_repo,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=temporal,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=FakeCrmConversationEventRepository(
            events=(_crm_event("I need a real person to help."),)
        ),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(
            outcome="human_handoff",
            handoff_reason_code="human_requested",
        ),
        handoff_repository=handoff_repo,
        handoff_completion_repository=FakeHandoffCompletionRepository(),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            _workspace_handoff_config()
        ),
        crm_client=FakeHandoffCRMClient(),
        notification_provider=notification_provider,
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.HUMAN_HANDOFF
    assert result.handoff_completion_status == HandoffCompletionStatus.RETRYABLE_FAILURE
    assert result.handoff_completion_failure_reason == "notification_exception:RuntimeError"
    assert {handoff.handoff_id for handoff in handoff_repo.saved} == {result.handoff_id}
    assert len(artifact_repo.saved) == 1
    assert len(temporal.calls) == 0
    assert (WORKSPACE_ID, LEAD_ID) not in workflow_repo.latest_by_lead


@pytest.mark.asyncio
async def test_holds_when_classifier_is_uncertain_without_starting_workflow() -> None:
    lead_repo = FakeLeadRepository()
    enrollments = FakeCampaignEnrollmentRepository()
    artifact_repo = FakeLeadClassificationArtifactRepository()
    workflow_repo = FakeLeadWorkflowRepository()
    temporal = FakeTemporalWorkflowStarter()

    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=await _lead(tags=("configured_tag",), repository=lead_repo),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(
                campaign_id=CAMPAIGN_ID,
                version_id=VERSION_ID,
                crm_enrollment_tag="configured_tag",
            )
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=enrollments,
        lead_workflow_repository=workflow_repo,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=temporal,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(outcome="review_hold"),
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.REVIEW_HOLD
    assert result.route == "review_hold"
    assert result.reason_codes == ("ai_classified_review_hold",)
    assert len(artifact_repo.saved) == 1
    assert enrollments.enrollments == {}
    assert len(temporal.calls) == 0
    assert (WORKSPACE_ID, LEAD_ID) not in workflow_repo.latest_by_lead


@pytest.mark.asyncio
async def test_blocks_when_classifier_marks_lead_blocked_without_starting_workflow() -> None:
    lead_repo = FakeLeadRepository()
    enrollments = FakeCampaignEnrollmentRepository()
    artifact_repo = FakeLeadClassificationArtifactRepository()
    workflow_repo = FakeLeadWorkflowRepository()
    temporal = FakeTemporalWorkflowStarter()

    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=await _lead(tags=("configured_tag",), repository=lead_repo),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(
                campaign_id=CAMPAIGN_ID,
                version_id=VERSION_ID,
                crm_enrollment_tag="configured_tag",
            )
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=enrollments,
        lead_workflow_repository=workflow_repo,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=temporal,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(outcome="blocked"),
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.BLOCKED
    assert result.route == "blocked"
    assert result.reason_codes == ("ai_classified_blocked",)
    assert len(artifact_repo.saved) == 1
    assert enrollments.enrollments == {}
    assert len(temporal.calls) == 0
    assert (WORKSPACE_ID, LEAD_ID) not in workflow_repo.latest_by_lead


@pytest.mark.asyncio
async def test_holds_when_classifier_is_uncertain_but_conversation_context_exists() -> None:
    lead_repo = FakeLeadRepository()
    artifact_repo = FakeLeadClassificationArtifactRepository()
    workflow_repo = FakeLeadWorkflowRepository()
    temporal = FakeTemporalWorkflowStarter()
    conversation_repo = FakeCrmConversationEventRepository(
        events=(_crm_event("Just looking around, not sure about timing yet."),)
    )

    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=await _lead(tags=("configured_tag",), repository=lead_repo),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(
                campaign_id=CAMPAIGN_ID,
                version_id=VERSION_ID,
                crm_enrollment_tag="configured_tag",
            )
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=FakeCampaignEnrollmentRepository(),
        lead_workflow_repository=workflow_repo,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=temporal,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=conversation_repo,
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(outcome="review_hold"),
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.REVIEW_HOLD, (
        "A review_hold classification with recent CRM conversation context must not auto-start "
        "dormant outreach."
    )
    assert result.route == "review_hold"
    assert "review_hold_with_conversation_context" in result.reason_codes
    assert len(artifact_repo.saved) == 1
    assert len(temporal.calls) == 0, "No workflow should be started when the lead is held."
    assert (WORKSPACE_ID, LEAD_ID) not in workflow_repo.latest_by_lead


@pytest.mark.asyncio
async def test_holds_when_classification_is_rejected_and_conversation_context_exists() -> None:
    lead_repo = FakeLeadRepository()
    artifact_repo = FakeLeadClassificationArtifactRepository()
    workflow_repo = FakeLeadWorkflowRepository()
    temporal = FakeTemporalWorkflowStarter()
    conversation_repo = FakeCrmConversationEventRepository(
        events=(_crm_event("Just looking for now."),)
    )

    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=await _lead(tags=("configured_tag",), repository=lead_repo),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(
                campaign_id=CAMPAIGN_ID,
                version_id=VERSION_ID,
                crm_enrollment_tag="configured_tag",
            )
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=FakeCampaignEnrollmentRepository(),
        lead_workflow_repository=workflow_repo,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=temporal,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=conversation_repo,
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=_InvalidJsonLLMClient(),
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.REVIEW_HOLD, (
        "A rejected/invalid classification with recent CRM conversation context must not fall "
        "back to dormant outreach."
    )
    assert result.route == "review_hold"
    assert "review_hold_with_conversation_context" in result.reason_codes
    assert len(artifact_repo.saved) == 1
    assert len(temporal.calls) == 0, "No workflow should be started when the lead is held."
    assert (WORKSPACE_ID, LEAD_ID) not in workflow_repo.latest_by_lead


@pytest.mark.asyncio
async def test_future_month_year_note_still_uses_llm_first_routing() -> None:
    lead_repo = FakeLeadRepository()
    artifact_repo = FakeLeadClassificationArtifactRepository()
    workflow_repo = FakeLeadWorkflowRepository()
    temporal = FakeTemporalWorkflowStarter()
    enrollments = FakeCampaignEnrollmentRepository()
    transitions = FakeWorkflowTransitionRepository()
    conversation_repo = FakeCrmConversationEventRepository(
        events=(_crm_event("Looks needs a house but in 2027 January."),)
    )
    llm_client = FakeClassificationLLMClient(outcome="dormant")

    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=await _lead(tags=("configured_tag",), repository=lead_repo),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(
                campaign_id=CAMPAIGN_ID,
                version_id=VERSION_ID,
                crm_enrollment_tag="configured_tag",
            )
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=enrollments,
        lead_workflow_repository=workflow_repo,
        workflow_transition_repository=transitions,
        temporal_workflow_starter=temporal,
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=_timing_not_right_track_repository(),
        paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
        artifact_repository=artifact_repo,
        crm_conversation_event_repository=conversation_repo,
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=llm_client,
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.STARTED
    assert result.route == "dormant"
    assert len(llm_client.requests) == 1
    assert len(artifact_repo.saved) == 1
    saved_artifact = artifact_repo.saved[0]
    assert saved_artifact.outcome == LeadStateClassificationOutcome.DORMANT
    saved_lead = lead_repo.lead
    assert saved_lead is not None
    assert saved_lead.paused_search_active is False
    assert len(temporal.calls) == 1
    workflow = workflow_repo.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert workflow.state == WorkflowState.QUEUED
    transition = next(iter(transitions.transitions.values()))
    assert transition.to_state == WorkflowState.QUEUED


@pytest.mark.asyncio
async def test_routes_to_blocked_when_lead_is_suppressed() -> None:
    lead_repo = FakeLeadRepository()

    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=await _lead(tags=("configured_tag",), repository=lead_repo, do_not_contact=True),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(
                campaign_id=CAMPAIGN_ID,
                version_id=VERSION_ID,
                crm_enrollment_tag="configured_tag",
            )
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=FakeCampaignEnrollmentRepository(),
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=FakeTemporalWorkflowStarter(),
        lead_repository=lead_repo,
        paused_search_history_repository=lead_repo,
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        artifact_repository=FakeLeadClassificationArtifactRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(outcome="dormant"),
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.BLOCKED
    assert result.route == "blocked"


def _config(
    *,
    campaign_id: UUID,
    version_id: UUID,
    crm_enrollment_tag: str | None,
) -> CampaignExecutionConfig:
    return CampaignExecutionConfig(
        campaign_id=campaign_id,
        campaign_version_id=version_id,
        workspace_id=WORKSPACE_ID,
        campaign_name="Configured Campaign",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(ContactChannel.EMAIL,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="UTC",
        sms_compliance_required=False,
        preflight_digest_enabled=True,
        crm_enrollment_tag=crm_enrollment_tag,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(
            CampaignCadenceStep(
                cadence_step_id=STEP_ID,
                workspace_id=WORKSPACE_ID,
                campaign_version_id=version_id,
                step_order=1,
                channel=ContactChannel.EMAIL,
                delay_hours=0,
                message_goal="Check in",
                template_key="email-1",
                max_attempts=1,
                created_at=NOW,
            ),
        ),
        created_at=NOW,
        published_at=NOW,
    )


def _contact_policy() -> WorkspaceContactPolicy:
    return WorkspaceContactPolicy(
        workspace_id=WORKSPACE_ID,
        sms_compliance_state=SmsComplianceState.APPROVED,
    )


def _workspace_handoff_config() -> WorkspaceHandoffConfig:
    return WorkspaceHandoffConfig(
        workspace_id=WORKSPACE_ID,
        fallback_recipient_email="fallback@example.com",
        crm_handoff_tag="human_handoff_required",
        crm_review_tag="needs_agent_review",
        crm_custom_fields={"handoff_status": "required"},
    )


async def _lead(
    *,
    tags: tuple[str, ...],
    repository: FakeLeadRepository | None = None,
    do_not_contact: bool = False,
    paused_search_active: bool = False,
) -> CanonicalLeadRecord:
    lead = CanonicalLeadRecord(
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
        tags=tags,
        primary_email="lead@example.com",
        has_email=True,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        do_not_contact=do_not_contact,
        paused_search_active=paused_search_active,
        pause_reason_code=(
            PausedSearchReasonCode.WAITING_FOR_RATES if paused_search_active else None
        ),
        paused_search_source=(
            PausedSearchSource.AI_CONVERSATION_CLASSIFICATION if paused_search_active else None
        ),
    )
    if repository is not None:
        await repository.upsert(lead)
    return lead


async def _record_commit(calls: list[str]) -> None:
    calls.append("commit")


def _paused_search_track_repository(
    track_version_id: PausedSearchTrackVersionId = TRACK_VERSION_ID,
) -> FakePausedSearchTrackAdminRepository:
    return FakePausedSearchTrackAdminRepository(
        mappings=(
            PausedSearchReasonMapping(
                mapping_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
                workspace_id=WORKSPACE_ID,
                reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
                track_id=UUID("99999999-9999-9999-9999-999999999999"),
                track_version_id=track_version_id,
                created_by_user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                created_at=NOW,
            ),
        ),
        tracks=(
            PausedSearchTrack(
                track_id=UUID("99999999-9999-9999-9999-999999999999"),
                workspace_id=WORKSPACE_ID,
                track_key="waiting-for-rates",
                display_name="Waiting for rates",
                status=PausedSearchTrackStatus.ACTIVE,
                active_version_id=track_version_id,
                created_by_user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                created_at=NOW,
                updated_at=NOW,
            ),
        ),
        versions=(
            PausedSearchTrackVersion(
                track_version_id=track_version_id,
                workspace_id=WORKSPACE_ID,
                track_id=UUID("99999999-9999-9999-9999-999999999999"),
                version_number=1,
                status=CampaignVersionStatus.PUBLISHED,
                track_family=PausedSearchTrackFamily.MAINTENANCE,
                enabled=True,
                allowed_channels=(ContactChannel.EMAIL,),
                default_for_reason_codes=(PausedSearchReasonCode.WAITING_FOR_RATES,),
                fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL,
                maintenance_interval_days=60,
                reactivation_window_days=30,
                max_total_touches=4,
                requires_review_before_publish=False,
                created_by_user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                created_at=NOW,
                published_at=NOW,
            ),
        ),
    )


def _crm_event(
    content: str,
    *,
    direction: CrmConversationEventDirection = CrmConversationEventDirection.INBOUND,
) -> CrmConversationEvent:
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
        direction=direction,
        content=content,
    )


class _InvalidJsonLLMClient(LLMClient):
    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        return LLMResult(
            text="this is not valid json",
            model="openai/gpt-4o-mini",
            prompt_version=request.prompt_version,
            latency_ms=13,
            usage_tokens=37,
        )


def _timing_not_right_track_repository() -> FakePausedSearchTrackAdminRepository:
    return FakePausedSearchTrackAdminRepository(
        mappings=(
            PausedSearchReasonMapping(
                mapping_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
                workspace_id=WORKSPACE_ID,
                reason_code=PausedSearchReasonCode.TIMING_NOT_RIGHT,
                track_id=TIMING_TRACK_ID,
                track_version_id=TIMING_TRACK_VERSION_ID,
                created_by_user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                created_at=NOW,
            ),
        ),
        versions=(
            PausedSearchTrackVersion(
                track_version_id=TIMING_TRACK_VERSION_ID,
                workspace_id=WORKSPACE_ID,
                track_id=TIMING_TRACK_ID,
                version_number=1,
                status=CampaignVersionStatus.PUBLISHED,
                track_family=PausedSearchTrackFamily.MAINTENANCE,
                enabled=True,
                allowed_channels=(ContactChannel.EMAIL,),
                default_for_reason_codes=(PausedSearchReasonCode.TIMING_NOT_RIGHT,),
                fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL,
                maintenance_interval_days=60,
                reactivation_window_days=30,
                max_total_touches=4,
                requires_review_before_publish=False,
                created_by_user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                created_at=NOW,
                published_at=NOW,
            ),
        ),
    )
