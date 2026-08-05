from dataclasses import replace
from datetime import UTC, datetime, time
from uuid import UUID

import pytest

from app.application.use_cases.lead_review_hold_resolution import (
    LeadReviewHoldResolution,
    LeadReviewHoldResolutionReasonCode,
    LeadReviewHoldResolutionStatus,
    resolve_lead_review_hold,
)
from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchReasonMapping,
    PausedSearchTrack,
    PausedSearchTrackFamily,
    PausedSearchTrackStatus,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.admin import CampaignAdminCampaign, CampaignAdminVersion
from app.domain.campaigns.enrollment import (
    CampaignEnrollment,
    CampaignEnrollmentSource,
    CampaignEnrollmentStatus,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.compliance.contactability import ContactChannel
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
    LeadClassificationAppliedStatus,
    LeadClassificationArtifact,
    LeadRoutingReview,
    LeadRoutingReviewStatus,
    LeadStateClassificationOutcome,
    PausedSearchReasonCode,
)
from app.domain.llm import WorkspaceLLMConfig
from app.domain.workflows import WorkflowState
from app.domain.workspace_automation import WorkspaceOperationalControl
from tests.application.use_cases._campaign_admin_fakes import (
    FakeCampaignAdminRepository,
    FakeEventBus,
)
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeClassificationLLMClient,
    FakeCrmConversationEventRepository,
    FakeLeadClassificationArtifactRepository,
    FakeLeadRepository,
    FakeLeadRoutingReviewRepository,
    FakeWorkspaceLLMConfigRepository,
    FakeWorkspaceOperationalControlRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeLeadWorkflowRepository,
    FakeTemporalSignalOutboxRepository,
    FakeTemporalWorkflowStarter,
    FakeWorkflowTransitionRepository,
)
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
    FakePausedSearchTrackAssignmentRepository,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000004")
VERSION_ID = UUID("00000000-0000-0000-0000-000000000005")
TRACK_ID = UUID("00000000-0000-0000-0000-000000000006")
TRACK_VERSION_ID = UUID("00000000-0000-0000-0000-000000000007")


@pytest.mark.asyncio
async def test_resolve_review_hold_to_dormant_starts_manual_enrollment() -> None:
    deps = _deps(latest_artifact=_artifact(LeadStateClassificationOutcome.REVIEW_HOLD))
    commit_calls: list[str] = []

    result = await resolve_lead_review_hold(
        actor=_actor(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        resolution=LeadReviewHoldResolution.DORMANT,
        lead_repository=deps.lead_repository,
        lead_read_repository=deps.lead_repository,
        artifact_repository=deps.artifact_repository,
        paused_search_history_repository=deps.lead_repository,
        workspace_llm_config_repository=deps.workspace_llm_config_repository,
        llm_client=deps.llm_client,
        crm_conversation_event_repository=deps.crm_conversation_event_repository,
        campaign_admin_repository=deps.campaign_admin_repository,
        campaign_enrollment_repository=deps.campaign_enrollment_repository,
        lead_workflow_repository=deps.lead_workflow_repository,
        workflow_transition_repository=deps.workflow_transition_repository,
        paused_search_track_repository=deps.paused_search_track_repository,
        paused_search_track_assignment_repository=deps.paused_search_track_assignment_repository,
        temporal_signal_outbox_repository=deps.temporal_signal_outbox_repository,
        temporal_workflow_starter=deps.temporal_workflow_starter,
        event_bus=deps.event_bus,
        workspace_operational_control_repository=deps.workspace_operational_control_repository,
        now=NOW,
        default_openrouter_model="openai/gpt-4o-mini",
        commit=lambda: _record_commit(commit_calls),
        routing_review_repository=deps.routing_review_repository,
    )

    assert result.status == LeadReviewHoldResolutionStatus.RESOLVED
    assert result.resolution == LeadReviewHoldResolution.DORMANT
    assert deps.temporal_workflow_starter.calls[0]["campaign_version_id"] == VERSION_ID
    workflow = deps.lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert workflow.state == WorkflowState.QUEUED
    assert commit_calls == ["commit"]
    assert deps.routing_review_repository.saved[0].status == LeadRoutingReviewStatus.SUPERSEDED


@pytest.mark.asyncio
async def test_resolve_review_hold_to_paused_search_starts_pinned_workflow() -> None:
    deps = _deps(latest_artifact=_artifact(LeadStateClassificationOutcome.REVIEW_HOLD))

    result = await resolve_lead_review_hold(
        actor=_actor(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        resolution=LeadReviewHoldResolution.PAUSED_SEARCH,
        lead_repository=deps.lead_repository,
        lead_read_repository=deps.lead_repository,
        artifact_repository=deps.artifact_repository,
        paused_search_history_repository=deps.lead_repository,
        workspace_llm_config_repository=deps.workspace_llm_config_repository,
        llm_client=deps.llm_client,
        crm_conversation_event_repository=deps.crm_conversation_event_repository,
        campaign_admin_repository=deps.campaign_admin_repository,
        campaign_enrollment_repository=deps.campaign_enrollment_repository,
        lead_workflow_repository=deps.lead_workflow_repository,
        workflow_transition_repository=deps.workflow_transition_repository,
        paused_search_track_repository=deps.paused_search_track_repository,
        paused_search_track_assignment_repository=deps.paused_search_track_assignment_repository,
        temporal_signal_outbox_repository=deps.temporal_signal_outbox_repository,
        temporal_workflow_starter=deps.temporal_workflow_starter,
        event_bus=deps.event_bus,
        workspace_operational_control_repository=deps.workspace_operational_control_repository,
        now=NOW,
        default_openrouter_model="openai/gpt-4o-mini",
        routing_review_repository=deps.routing_review_repository,
        pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
        pause_reason_note="Waiting for rates to improve.",
        reengagement_not_before=NOW,
        reengagement_window_label="spring check-in",
    )

    assert result.status == LeadReviewHoldResolutionStatus.RESOLVED
    assert result.resolution == LeadReviewHoldResolution.PAUSED_SEARCH
    assert result.paused_search is not None
    assert result.history_entry is not None
    workflow = deps.lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert workflow.state == WorkflowState.ACTIVE_NURTURE
    assert workflow.paused_search_track_version_id == TRACK_VERSION_ID
    assert deps.routing_review_repository.saved[0].status.value == "resolved"


@pytest.mark.asyncio
async def test_resolve_review_hold_requires_latest_review_hold_artifact() -> None:
    deps = _deps(latest_artifact=_artifact(LeadStateClassificationOutcome.PAUSED_SEARCH))

    result = await resolve_lead_review_hold(
        actor=_actor(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        resolution=LeadReviewHoldResolution.DORMANT,
        lead_repository=deps.lead_repository,
        lead_read_repository=deps.lead_repository,
        artifact_repository=deps.artifact_repository,
        paused_search_history_repository=deps.lead_repository,
        workspace_llm_config_repository=deps.workspace_llm_config_repository,
        llm_client=deps.llm_client,
        crm_conversation_event_repository=deps.crm_conversation_event_repository,
        campaign_admin_repository=deps.campaign_admin_repository,
        campaign_enrollment_repository=deps.campaign_enrollment_repository,
        lead_workflow_repository=deps.lead_workflow_repository,
        workflow_transition_repository=deps.workflow_transition_repository,
        paused_search_track_repository=deps.paused_search_track_repository,
        temporal_signal_outbox_repository=deps.temporal_signal_outbox_repository,
        temporal_workflow_starter=deps.temporal_workflow_starter,
        event_bus=deps.event_bus,
        workspace_operational_control_repository=deps.workspace_operational_control_repository,
        now=NOW,
        default_openrouter_model="openai/gpt-4o-mini",
        routing_review_repository=deps.routing_review_repository,
    )

    assert result.status == LeadReviewHoldResolutionStatus.INVALID
    assert result.reasons == (LeadReviewHoldResolutionReasonCode.REVIEW_HOLD_REQUIRED,)
    assert deps.routing_review_repository.saved[0].status == LeadRoutingReviewStatus.PENDING


@pytest.mark.asyncio
async def test_resolve_review_hold_ignores_older_review_hold_artifacts() -> None:
    deps = _deps(latest_artifact=_artifact(LeadStateClassificationOutcome.PAUSED_SEARCH))
    deps.artifact_repository.saved.append(
        replace(
            _artifact(LeadStateClassificationOutcome.REVIEW_HOLD),
            artifact_id=UUID("00000000-0000-0000-0000-000000000099"),
            created_at=NOW.replace(hour=11),
        )
    )

    result = await resolve_lead_review_hold(
        actor=_actor(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        resolution=LeadReviewHoldResolution.DORMANT,
        lead_repository=deps.lead_repository,
        lead_read_repository=deps.lead_repository,
        artifact_repository=deps.artifact_repository,
        paused_search_history_repository=deps.lead_repository,
        workspace_llm_config_repository=deps.workspace_llm_config_repository,
        llm_client=deps.llm_client,
        crm_conversation_event_repository=deps.crm_conversation_event_repository,
        campaign_admin_repository=deps.campaign_admin_repository,
        campaign_enrollment_repository=deps.campaign_enrollment_repository,
        lead_workflow_repository=deps.lead_workflow_repository,
        workflow_transition_repository=deps.workflow_transition_repository,
        paused_search_track_repository=deps.paused_search_track_repository,
        temporal_signal_outbox_repository=deps.temporal_signal_outbox_repository,
        temporal_workflow_starter=deps.temporal_workflow_starter,
        event_bus=deps.event_bus,
        workspace_operational_control_repository=deps.workspace_operational_control_repository,
        now=NOW,
        default_openrouter_model="openai/gpt-4o-mini",
        routing_review_repository=deps.routing_review_repository,
    )

    assert result.status == LeadReviewHoldResolutionStatus.INVALID
    assert result.reasons == (LeadReviewHoldResolutionReasonCode.REVIEW_HOLD_REQUIRED,)


@pytest.mark.asyncio
async def test_resolve_review_hold_to_dormant_already_enrolled_resolves_pending_review() -> None:
    deps = _deps(latest_artifact=_artifact(LeadStateClassificationOutcome.REVIEW_HOLD))
    existing_enrollment = _existing_enrollment()
    deps.campaign_enrollment_repository.enrollments[(WORKSPACE_ID, LEAD_ID, CAMPAIGN_ID)] = (
        existing_enrollment
    )

    result = await resolve_lead_review_hold(
        actor=_actor(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        resolution=LeadReviewHoldResolution.DORMANT,
        lead_repository=deps.lead_repository,
        lead_read_repository=deps.lead_repository,
        artifact_repository=deps.artifact_repository,
        paused_search_history_repository=deps.lead_repository,
        workspace_llm_config_repository=deps.workspace_llm_config_repository,
        llm_client=deps.llm_client,
        crm_conversation_event_repository=deps.crm_conversation_event_repository,
        campaign_admin_repository=deps.campaign_admin_repository,
        campaign_enrollment_repository=deps.campaign_enrollment_repository,
        lead_workflow_repository=deps.lead_workflow_repository,
        workflow_transition_repository=deps.workflow_transition_repository,
        paused_search_track_repository=deps.paused_search_track_repository,
        temporal_signal_outbox_repository=deps.temporal_signal_outbox_repository,
        temporal_workflow_starter=deps.temporal_workflow_starter,
        event_bus=deps.event_bus,
        workspace_operational_control_repository=deps.workspace_operational_control_repository,
        now=NOW,
        default_openrouter_model="openai/gpt-4o-mini",
        routing_review_repository=deps.routing_review_repository,
    )

    assert result.status == LeadReviewHoldResolutionStatus.ALREADY_ENROLLED
    assert result.campaign_enrollment_id == str(existing_enrollment.campaign_enrollment_id)
    assert deps.routing_review_repository.saved[0].status == LeadRoutingReviewStatus.RESOLVED
    assert deps.temporal_workflow_starter.calls == []


class _Deps:
    def __init__(self, latest_artifact: LeadClassificationArtifact) -> None:
        self.lead_repository = FakeLeadRepository(_lead())
        self.artifact_repository = FakeLeadClassificationArtifactRepository()
        self.artifact_repository.saved.append(latest_artifact)
        self.workspace_llm_config_repository = FakeWorkspaceLLMConfigRepository(
            WorkspaceLLMConfig(
                workspace_id=WORKSPACE_ID,
                openrouter_model="openai/gpt-4o-mini",
            )
        )
        self.llm_client = FakeClassificationLLMClient()
        self.crm_conversation_event_repository = FakeCrmConversationEventRepository()
        self.campaign_admin_repository = _campaign_repository()
        self.campaign_enrollment_repository = FakeCampaignEnrollmentRepository()
        self.lead_workflow_repository = FakeLeadWorkflowRepository()
        self.workflow_transition_repository = FakeWorkflowTransitionRepository()
        self.temporal_workflow_starter = FakeTemporalWorkflowStarter()
        self.temporal_signal_outbox_repository = FakeTemporalSignalOutboxRepository()
        self.paused_search_track_repository = _track_repository()
        self.paused_search_track_assignment_repository = FakePausedSearchTrackAssignmentRepository()
        self.routing_review_repository = FakeLeadRoutingReviewRepository()
        self.workspace_operational_control_repository = FakeWorkspaceOperationalControlRepository(
            WorkspaceOperationalControl(
                workspace_id=WORKSPACE_ID,
                recurring_paused_search_enabled=True,
            )
        )
        self.event_bus = FakeEventBus()
        self.routing_review_repository.saved.append(
            LeadRoutingReview(
                review_id=UUID("00000000-0000-0000-0000-000000000011"),
                workspace_id=WORKSPACE_ID,
                lead_id=LEAD_ID,
                artifact_id=latest_artifact.artifact_id,
                status=LeadRoutingReviewStatus.PENDING,
                reason_codes=("classification_rejected",),
                created_at=NOW,
                updated_at=NOW,
            )
        )


def _deps(*, latest_artifact: LeadClassificationArtifact) -> _Deps:
    return _Deps(latest_artifact)


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        assigned_agent_user_id=USER_ID,
        assigned_agent_crm_id="agent-1",
        has_accountable_owner=True,
        primary_email="lead@example.com",
        has_email=True,
    )


def _artifact(outcome: LeadStateClassificationOutcome) -> LeadClassificationArtifact:
    return LeadClassificationArtifact(
        artifact_id=UUID("00000000-0000-0000-0000-000000000010"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        source="ai_conversation_classification",
        outcome=outcome,
        pause_reason_code=None,
        reengagement_not_before=None,
        reengagement_window_label=None,
        confidence=0.55,
        evidence=("Silent lead needs human route review.",),
        summary="Ambiguous dormant route.",
        model="openai/gpt-4o-mini",
        prompt_version="lead_state_classification:v1",
        latency_ms=10,
        usage_tokens=20,
        applied_status=LeadClassificationAppliedStatus.REVIEW,
        applied_at=NOW,
        created_at=NOW,
    )


def _existing_enrollment() -> CampaignEnrollment:
    return CampaignEnrollment(
        campaign_enrollment_id=UUID("00000000-0000-0000-0000-000000000012"),
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=VERSION_ID,
        lead_id=LEAD_ID,
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        status=CampaignEnrollmentStatus.QUEUED,
        eligible_at=NOW,
        enrolled_at=NOW,
        started_at=None,
        ended_at=None,
        created_by_user_id=USER_ID,
        reason_codes=(),
        created_at=NOW,
        updated_at=NOW,
    )


def _campaign_repository() -> FakeCampaignAdminRepository:
    repository = FakeCampaignAdminRepository()
    repository.campaigns[CAMPAIGN_ID] = CampaignAdminCampaign(
        campaign_id=CAMPAIGN_ID,
        workspace_id=WORKSPACE_ID,
        name="Dormant Follow Up",
        status=CampaignStatus.ACTIVE,
        active_version_id=VERSION_ID,
        created_by_user_id=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )
    repository.versions[VERSION_ID] = CampaignAdminVersion(
        campaign_version_id=VERSION_ID,
        campaign_id=CAMPAIGN_ID,
        workspace_id=WORKSPACE_ID,
        version_number=1,
        status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(ContactChannel.EMAIL,),
        daily_start_cap=100,
        dormant_threshold_days=60,
        quiet_hours_start=time(9, 0),
        quiet_hours_end=time(18, 0),
        timezone="America/Los_Angeles",
        sms_compliance_required=False,
        preflight_digest_enabled=False,
        crm_enrollment_tag="ai_nurture",
        allow_assigned_agent_manual_enrollment=True,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        created_by_user_id=USER_ID,
        created_at=NOW,
        published_at=NOW,
    )
    return repository


def _track_repository() -> FakePausedSearchTrackAdminRepository:
    return FakePausedSearchTrackAdminRepository(
        mappings=(
            PausedSearchReasonMapping(
                mapping_id=UUID("00000000-0000-0000-0000-000000000011"),
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
                maintenance_interval_days=30,
                reactivation_window_days=30,
                max_total_touches=6,
                requires_review_before_publish=False,
                created_by_user_id=USER_ID,
                created_at=NOW,
                published_at=NOW,
            ),
        ),
        tracks=(
            PausedSearchTrack(
                track_id=TRACK_ID,
                workspace_id=WORKSPACE_ID,
                track_key="waiting-for-rates",
                display_name="Waiting for rates",
                status=PausedSearchTrackStatus.ACTIVE,
                active_version_id=TRACK_VERSION_ID,
                created_by_user_id=USER_ID,
                created_at=NOW,
                updated_at=NOW,
            ),
        ),
    )


def _actor() -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=USER_ID,
        user_status=UserStatus.ACTIVE,
        active_role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=UUID("00000000-0000-0000-0000-000000000012"),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


async def _record_commit(calls: list[str]) -> None:
    calls.append("commit")
