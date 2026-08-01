from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import cast
from uuid import UUID

from fastapi.testclient import TestClient

from app.application.ports.crm import CRMClient
from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchReasonMapping,
    PausedSearchTrackFamily,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.admin import CampaignAdminCampaign, CampaignAdminVersion
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
    LeadStateClassificationOutcome,
    PausedSearchReasonCode,
)
from app.domain.workspace_automation import WorkspaceOperationalControl
from app.interfaces.api.dependencies.lead_classification import (
    LeadClassificationActionBundle,
    get_lead_classification_action_bundle,
)
from app.interfaces.api.dependencies.lead_manual_enrollment import (
    LeadManualEnrollmentBundle,
    get_lead_manual_enrollment_bundle,
)
from app.interfaces.api.dependencies.lead_paused_search import (
    LeadPausedSearchActionBundle,
    get_lead_paused_search_action_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.main import create_app
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
from tests.application.use_cases._lead_read_fakes import FakeUserRepository
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
)
from tests.application.use_cases.test_complete_handoff import (
    FakeCRMClient,
    FakeHandoffCompletionRepository,
    FakeNotificationProvider,
    FakeWorkspaceHandoffConfigRepository,
)
from tests.application.use_cases.test_process_inbound_message_event import (
    FakeHandoffRepository,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000004")
VERSION_ID = UUID("00000000-0000-0000-0000-000000000005")
TRACK_ID = UUID("00000000-0000-0000-0000-000000000006")
TRACK_VERSION_ID = UUID("00000000-0000-0000-0000-000000000007")


@dataclass
class ReviewHoldResolutionTestClient:
    client: TestClient
    starter: FakeTemporalWorkflowStarter
    lead_repository: FakeLeadRepository


def test_admin_can_resolve_review_hold_to_paused_search() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.BROKERAGE_ADMIN,
        latest_artifact=_artifact(LeadStateClassificationOutcome.REVIEW_HOLD),
    )

    response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/review-hold-resolutions",
        json={
            "resolution": "paused_search",
            "campaign_id": str(CAMPAIGN_ID),
            "pause_reason_code": "waiting_for_rates",
            "pause_reason_note": "Need better financing conditions.",
            "reengagement_not_before": NOW.isoformat(),
            "reengagement_window_label": "spring check-in",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
    assert response.json()["resolution"] == "paused_search"
    assert client.starter.calls[0]["campaign_version_id"] == VERSION_ID
    assert client.lead_repository.lead is not None
    assert client.lead_repository.lead.paused_search_active is True


def test_resolution_conflicts_when_latest_artifact_is_not_review_hold() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.BROKERAGE_ADMIN,
        latest_artifact=_artifact(LeadStateClassificationOutcome.PAUSED_SEARCH),
    )

    response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/review-hold-resolutions",
        json={
            "resolution": "dormant",
            "campaign_id": str(CAMPAIGN_ID),
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == ["review_hold_required"]


def _client_for_role(
    role: WorkspaceMembershipRole,
    *,
    latest_artifact: LeadClassificationArtifact,
) -> ReviewHoldResolutionTestClient:
    app = create_app()
    lead_repository = FakeLeadRepository(_lead())
    artifact_repository = FakeLeadClassificationArtifactRepository()
    artifact_repository.saved.append(latest_artifact)
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    starter = FakeTemporalWorkflowStarter()
    signal_outbox_repository = FakeTemporalSignalOutboxRepository()
    session = _FakeSession()
    track_repository = _track_repository()

    manual_bundle = LeadManualEnrollmentBundle(
        session=session,
        lead_repository=lead_repository,
        campaign_admin_repository=_campaign_repository(),
        campaign_enrollment_repository=FakeCampaignEnrollmentRepository(),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        workspace_operational_control_repository=FakeWorkspaceOperationalControlRepository(
            WorkspaceOperationalControl(
                workspace_id=WORKSPACE_ID,
                recurring_paused_search_enabled=True,
            )
        ),
        temporal_workflow_starter=starter,
        lead_classification_artifact_repository=artifact_repository,
        paused_search_history_repository=lead_repository,
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(outcome="review_hold"),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        paused_search_track_repository=track_repository,
        routing_review_repository=FakeLeadRoutingReviewRepository(),
        default_openrouter_model="openai/gpt-4o-mini",
        handoff_repository=FakeHandoffRepository(),
        handoff_completion_repository=FakeHandoffCompletionRepository(),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(),
        crm_client=cast(CRMClient, FakeCRMClient()),
        notification_provider=FakeNotificationProvider(),
        user_repository=FakeUserRepository({}),
        event_bus=FakeEventBus(),
    )
    paused_bundle = LeadPausedSearchActionBundle(
        session=session,
        lead_repository=lead_repository,
        paused_search_history_repository=lead_repository,
        lead_workflow_repository=workflow_repository,
        paused_search_track_repository=track_repository,
        temporal_signal_outbox_repository=signal_outbox_repository,
    )
    classification_bundle = LeadClassificationActionBundle(
        session=session,
        lead_repository=lead_repository,
        paused_search_history_repository=lead_repository,
        artifact_repository=artifact_repository,
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        lead_workflow_repository=workflow_repository,
        paused_search_track_repository=track_repository,
        temporal_signal_outbox_repository=signal_outbox_repository,
        llm_client=FakeClassificationLLMClient(outcome="review_hold"),
        default_openrouter_model="openai/gpt-4o-mini",
    )

    app.dependency_overrides[get_workspace_actor] = lambda: _actor(role)
    app.dependency_overrides[get_lead_manual_enrollment_bundle] = lambda: manual_bundle
    app.dependency_overrides[get_lead_paused_search_action_bundle] = lambda: paused_bundle
    app.dependency_overrides[get_lead_classification_action_bundle] = lambda: classification_bundle
    return ReviewHoldResolutionTestClient(
        client=TestClient(app),
        starter=starter,
        lead_repository=lead_repository,
    )


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
    )


def _actor(role: WorkspaceMembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=USER_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=UUID("00000000-0000-0000-0000-000000000012"),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


class _FakeSession:
    async def commit(self) -> None:
        return None
