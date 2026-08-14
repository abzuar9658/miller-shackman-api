from dataclasses import dataclass, replace
from datetime import UTC, datetime, time
from typing import cast
from uuid import UUID

from fastapi.testclient import TestClient

from app.application.ports.crm import CRMClient
from app.application.ports.temporal import TemporalWorkflowExecutionMode
from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTrack,
    PausedSearchTrackAssignment,
    PausedSearchTrackAssignmentSource,
    PausedSearchTrackStatus,
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
from app.domain.leads import CanonicalLeadRecord, CRMProvider, PausedSearchSource
from app.domain.workflows import WorkflowState
from app.domain.workspace_automation import WorkspaceOperationalControl
from app.interfaces.api.dependencies.lead_manual_enrollment import (
    LeadManualEnrollmentBundle,
    get_lead_manual_enrollment_bundle,
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
    FakeTemporalWorkflowStarter,
    FakeWorkflowTransitionRepository,
)
from tests.application.use_cases._lead_read_fakes import FakeUserRepository
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
    FakePausedSearchTrackAssignmentRepository,
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
OTHER_CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000006")
OTHER_VERSION_ID = UUID("00000000-0000-0000-0000-000000000007")


@dataclass
class LeadManualEnrollmentTestClient:
    client: TestClient
    starter: FakeTemporalWorkflowStarter
    session: object
    bundle: LeadManualEnrollmentBundle


def test_brokerage_admin_can_list_and_start_manual_enrollment() -> None:
    client = _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)

    options_response = client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/manual-enrollment-options"
    )
    start_response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/manual-enrollments",
        json={"campaign_id": str(CAMPAIGN_ID)},
    )

    assert options_response.status_code == 200
    assert options_response.json()["campaigns"][0]["campaign_id"] == str(CAMPAIGN_ID)
    assert start_response.status_code == 200
    assert start_response.json()["status"] == "started"
    assert client.starter.calls[0]["campaign_version_id"] == VERSION_ID
    assert cast(_FakeSession, client.session).commits == 2


def test_assigned_agent_can_start_own_lead_when_campaign_allows() -> None:
    client = _client_for_role(WorkspaceMembershipRole.ASSIGNED_AGENT)

    response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/manual-enrollments",
        json={"campaign_id": str(CAMPAIGN_ID)},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "started"


def test_manual_start_routes_to_paused_search_before_starting_workflow() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.BROKERAGE_ADMIN,
        classification_outcome="paused_search",
    )

    response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/manual-enrollments",
        json={"campaign_id": str(CAMPAIGN_ID)},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "started"
    assert response.json()["route"] == "paused_search"
    assert client.starter.calls[0]["campaign_version_id"] == VERSION_ID


def test_selected_paused_search_start_bypasses_classifier() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.BROKERAGE_ADMIN,
        classification_outcome="human_handoff",
        operator_paused_search=True,
    )

    response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/paused-search/start",
        json={"campaign_id": str(CAMPAIGN_ID)},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "started"
    assert response.json()["route"] == "paused_search"
    assert response.json()["reasons"] == ["operator_selected_paused_search_track"]
    assert client.starter.calls[0]["campaign_version_id"] == VERSION_ID
    assert (
        client.starter.calls[0]["execution_mode"]
        is TemporalWorkflowExecutionMode.PAUSED_SEARCH_RECURRING
    )
    assert client.starter.calls[0]["paused_search_track_version_id"] == UUID(
        "00000000-0000-0000-0000-000000000013"
    )


def test_selected_paused_search_terminal_reentry_requires_admin_reason() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.BROKERAGE_ADMIN,
        operator_paused_search=True,
        include_other_campaign=True,
    )
    first_response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/paused-search/start",
        json={"campaign_id": str(CAMPAIGN_ID)},
    )
    assert first_response.status_code == 200
    _set_latest_workflow_state(client, WorkflowState.COMPLETED)

    missing_reason_response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/paused-search/start",
        json={"campaign_id": str(OTHER_CAMPAIGN_ID)},
    )
    accepted_response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/paused-search/start",
        json={
            "campaign_id": str(OTHER_CAMPAIGN_ID),
            "reason": "Lead requested renewed outreach.",
        },
    )

    assert missing_reason_response.status_code == 422
    assert accepted_response.status_code == 200
    assert accepted_response.json()["status"] == "started"


def test_assigned_agent_cannot_reenter_terminal_workflow() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.ASSIGNED_AGENT,
        operator_paused_search=True,
        include_other_campaign=True,
    )
    first_response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/paused-search/start",
        json={"campaign_id": str(CAMPAIGN_ID)},
    )
    assert first_response.status_code == 200
    _set_latest_workflow_state(client, WorkflowState.CLOSED)

    response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/paused-search/start",
        json={
            "campaign_id": str(OTHER_CAMPAIGN_ID),
            "reason": "Agent requested renewed outreach.",
        },
    )

    assert response.status_code == 403


def _set_latest_workflow_state(
    client: LeadManualEnrollmentTestClient,
    state: WorkflowState,
) -> None:
    repository = cast(FakeLeadWorkflowRepository, client.bundle.lead_workflow_repository)
    key = (WORKSPACE_ID, LEAD_ID)
    repository.latest_by_lead[key] = replace(repository.latest_by_lead[key], state=state)


def test_selected_paused_search_start_requires_operator_assignment() -> None:
    client = _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)

    response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/paused-search/start",
        json={"campaign_id": str(CAMPAIGN_ID)},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "review_hold"
    assert response.json()["reasons"] == ["operator_paused_search_assignment_required"]
    assert client.starter.calls == []


def test_manual_start_returns_review_hold_when_classification_needs_review() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.BROKERAGE_ADMIN,
        classification_outcome="review_hold",
    )

    response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/manual-enrollments",
        json={"campaign_id": str(CAMPAIGN_ID)},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "review_hold"
    assert response.json()["route"] == "review_hold"
    assert client.starter.calls == []


def test_assigned_agent_cannot_access_unowned_lead_manual_enrollment() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.ASSIGNED_AGENT,
        assigned_agent_user_id=UUID("00000000-0000-0000-0000-000000000099"),
    )

    options_response = client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/manual-enrollment-options"
    )
    start_response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/manual-enrollments",
        json={"campaign_id": str(CAMPAIGN_ID)},
    )

    assert options_response.status_code == 403
    assert options_response.json()["detail"] == ["permission_denied"]
    assert start_response.status_code == 403
    assert start_response.json()["detail"] == ["permission_denied"]


def test_assigned_agent_sees_no_options_when_campaign_disallows_agent_manual_start() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.ASSIGNED_AGENT,
        allow_assigned_agent_manual_enrollment=False,
    )

    response = client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/manual-enrollment-options"
    )

    assert response.status_code == 200
    assert response.json()["campaigns"] == []
    assert response.json()["reasons"] == ["campaigns_disallow_agent_manual_enrollment"]


def test_admin_sees_reason_when_no_active_campaign_exists() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.BROKERAGE_ADMIN,
        campaign_status=CampaignStatus.PAUSED,
    )

    response = client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/manual-enrollment-options"
    )

    assert response.status_code == 200
    assert response.json()["campaigns"] == []
    assert response.json()["reasons"] == ["no_active_campaigns"]
    assert response.json()["total_campaign_count"] == 1
    assert response.json()["active_campaign_count"] == 0


def test_admin_sees_reason_when_lead_already_enrolled() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.BROKERAGE_ADMIN,
        already_enrolled=True,
    )

    response = client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/manual-enrollment-options"
    )

    assert response.status_code == 200
    assert response.json()["campaigns"] == []
    assert response.json()["reasons"] == ["lead_already_enrolled_in_available_campaigns"]
    assert response.json()["already_enrolled_campaign_count"] == 1


def _client_for_role(
    role: WorkspaceMembershipRole,
    *,
    assigned_agent_user_id: UUID = USER_ID,
    allow_assigned_agent_manual_enrollment: bool = True,
    campaign_status: CampaignStatus = CampaignStatus.ACTIVE,
    already_enrolled: bool = False,
    classification_outcome: str = "dormant",
    classification_confidence: float = 0.91,
    operator_paused_search: bool = False,
    include_other_campaign: bool = False,
) -> LeadManualEnrollmentTestClient:
    app = create_app()
    lead = CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        has_accountable_owner=True,
        has_email=True,
        has_phone=True,
        has_sms_capable_phone=True,
        mapped_custom_fields={"assigned_agent_user_id": str(assigned_agent_user_id)},
        paused_search_active=operator_paused_search,
        paused_search_track_key="waiting-rates" if operator_paused_search else None,
        paused_search_track_version_id=(
            UUID("00000000-0000-0000-0000-000000000013")
            if operator_paused_search
            else None
        ),
        paused_search_source=PausedSearchSource.OPERATOR if operator_paused_search else None,
        paused_search_recorded_at=NOW if operator_paused_search else None,
        paused_search_recorded_by_user_id=USER_ID if operator_paused_search else None,
        paused_search_last_confirmed_at=NOW if operator_paused_search else None,
    )
    campaign_repository = FakeCampaignAdminRepository()
    campaign_repository.campaigns[CAMPAIGN_ID] = CampaignAdminCampaign(
        campaign_id=CAMPAIGN_ID,
        workspace_id=WORKSPACE_ID,
        name="Dormant Buyers",
        status=campaign_status,
        active_version_id=VERSION_ID,
        created_by_user_id=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )
    campaign_repository.versions[VERSION_ID] = CampaignAdminVersion(
        campaign_version_id=VERSION_ID,
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        version_number=1,
        status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(ContactChannel.EMAIL,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="America/Chicago",
        preflight_digest_enabled=True,
        crm_enrollment_tag="ai_nurture",
        allow_assigned_agent_manual_enrollment=allow_assigned_agent_manual_enrollment,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        created_by_user_id=USER_ID,
        created_at=NOW,
        published_at=NOW,
    )
    if include_other_campaign:
        campaign_repository.campaigns[OTHER_CAMPAIGN_ID] = replace(
            campaign_repository.campaigns[CAMPAIGN_ID],
            campaign_id=OTHER_CAMPAIGN_ID,
            name="Other campaign",
            active_version_id=OTHER_VERSION_ID,
        )
        campaign_repository.versions[OTHER_VERSION_ID] = replace(
            campaign_repository.versions[VERSION_ID],
            campaign_version_id=OTHER_VERSION_ID,
            campaign_id=OTHER_CAMPAIGN_ID,
        )
    starter = FakeTemporalWorkflowStarter()
    enrollment_repository = FakeCampaignEnrollmentRepository()
    lead_repository = FakeLeadRepository(lead)
    if already_enrolled:
        from app.domain.campaigns.enrollment import (
            CampaignEnrollment,
            CampaignEnrollmentSource,
            CampaignEnrollmentStatus,
        )

        enrollment_repository.enrollments[(WORKSPACE_ID, LEAD_ID, CAMPAIGN_ID)] = (
            CampaignEnrollment(
                campaign_enrollment_id=UUID("00000000-0000-0000-0000-000000000099"),
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
        )

    session = _FakeSession()
    assignment_repository = FakePausedSearchTrackAssignmentRepository(
        assignments=(
            PausedSearchTrackAssignment(
                assignment_id=UUID("00000000-0000-0000-0000-000000000014"),
                workspace_id=WORKSPACE_ID,
                lead_id=LEAD_ID,
                track_id=UUID("00000000-0000-0000-0000-000000000012"),
                track_version_id=UUID("00000000-0000-0000-0000-000000000013"),
                track_key_snapshot="waiting-rates",
                track_name_snapshot="Waiting for rates",
                track_version_snapshot=1,
                source=PausedSearchTrackAssignmentSource.OPERATOR,
                assigned_by_user_id=USER_ID,
                assigned_at=NOW,
            ),
        )
        if operator_paused_search
        else ()
    )
    bundle = LeadManualEnrollmentBundle(
        session=session,
        lead_repository=lead_repository,
        campaign_admin_repository=campaign_repository,
        campaign_enrollment_repository=enrollment_repository,
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        workspace_operational_control_repository=FakeWorkspaceOperationalControlRepository(
            WorkspaceOperationalControl(
                workspace_id=WORKSPACE_ID,
                recurring_paused_search_enabled=True,
            )
        ),
        temporal_workflow_starter=starter,
        lead_classification_artifact_repository=FakeLeadClassificationArtifactRepository(),
        paused_search_history_repository=lead_repository,
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(
            outcome=classification_outcome,
            confidence=classification_confidence,
            selected_track_key=(
                "waiting-rates"
                if classification_outcome == "paused_search"
                else None
            ),
            track_selection_status=(
                "selected" if classification_outcome == "paused_search" else None
            ),
        ),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        paused_search_track_repository=_track_repository(),
        paused_search_track_assignment_repository=assignment_repository,
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

    app.dependency_overrides[get_workspace_actor] = lambda: _actor(role)
    app.dependency_overrides[get_lead_manual_enrollment_bundle] = lambda: bundle
    return LeadManualEnrollmentTestClient(
        client=TestClient(app),
        starter=starter,
        session=session,
        bundle=bundle,
    )


def _actor(role: WorkspaceMembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=USER_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=UUID("00000000-0000-0000-0000-000000000010"),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


def _track_repository() -> FakePausedSearchTrackAdminRepository:
    return FakePausedSearchTrackAdminRepository(
        tracks=(
            PausedSearchTrack(
                track_id=UUID("00000000-0000-0000-0000-000000000012"),
                workspace_id=WORKSPACE_ID,
                track_key="waiting-rates",
                display_name="Waiting for rates",
                status=PausedSearchTrackStatus.ACTIVE,
                active_version_id=UUID("00000000-0000-0000-0000-000000000013"),
                created_by_user_id=USER_ID,
                created_at=NOW,
                updated_at=NOW,
            ),
        ),
        versions=(
            PausedSearchTrackVersion(
                track_version_id=UUID("00000000-0000-0000-0000-000000000013"),
                workspace_id=WORKSPACE_ID,
                track_id=UUID("00000000-0000-0000-0000-000000000012"),
                version_number=1,
                status=CampaignVersionStatus.PUBLISHED,
                selection_guidance="Select when a lead waits for mortgage rates to improve.",
                enabled=True,
                allowed_channels=(ContactChannel.EMAIL,),
                fallback_timing_policy=(
                    PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE
                ),
                maintenance_interval_days=30,
                reactivation_window_days=30,
                max_total_touches=6,
                created_by_user_id=USER_ID,
                created_at=NOW,
                published_at=NOW,
            ),
        ),
    )
