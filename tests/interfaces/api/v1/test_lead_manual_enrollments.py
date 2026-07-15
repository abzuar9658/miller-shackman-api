from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import cast
from uuid import UUID

from fastapi.testclient import TestClient

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
from app.domain.leads import CanonicalLeadRecord, CRMProvider
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
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeLeadWorkflowRepository,
    FakeTemporalWorkflowStarter,
    FakeWorkflowTransitionRepository,
)
from tests.application.use_cases._lead_read_fakes import FakeLeadRepository

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000004")
VERSION_ID = UUID("00000000-0000-0000-0000-000000000005")


@dataclass
class LeadManualEnrollmentTestClient:
    client: TestClient
    starter: FakeTemporalWorkflowStarter
    session: object


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
    assert cast(_FakeSession, client.session).commits == 1


def test_assigned_agent_can_start_own_lead_when_campaign_allows() -> None:
    client = _client_for_role(WorkspaceMembershipRole.ASSIGNED_AGENT)

    response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/manual-enrollments",
        json={"campaign_id": str(CAMPAIGN_ID)},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "started"


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
    assert response.json()["reasons"] == [
        "campaigns_disallow_agent_manual_enrollment"
    ]


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
    assert response.json()["reasons"] == [
        "lead_already_enrolled_in_available_campaigns"
    ]
    assert response.json()["already_enrolled_campaign_count"] == 1


def _client_for_role(
    role: WorkspaceMembershipRole,
    *,
    assigned_agent_user_id: UUID = USER_ID,
    allow_assigned_agent_manual_enrollment: bool = True,
    campaign_status: CampaignStatus = CampaignStatus.ACTIVE,
    already_enrolled: bool = False,
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
        sms_compliance_required=True,
        preflight_digest_enabled=True,
        crm_enrollment_tag="ai_nurture",
        allow_assigned_agent_manual_enrollment=allow_assigned_agent_manual_enrollment,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        created_by_user_id=USER_ID,
        created_at=NOW,
        published_at=NOW,
    )
    starter = FakeTemporalWorkflowStarter()
    enrollment_repository = FakeCampaignEnrollmentRepository()
    if already_enrolled:
        from app.domain.campaigns.enrollment import (
            CampaignEnrollment,
            CampaignEnrollmentSource,
            CampaignEnrollmentStatus,
        )

        enrollment_repository.enrollments[(WORKSPACE_ID, LEAD_ID, CAMPAIGN_ID)] = (
            CampaignEnrollment(
                campaign_enrollment_id=UUID(
                    "00000000-0000-0000-0000-000000000099"
                ),
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
    bundle = LeadManualEnrollmentBundle(
        session=session,
        lead_repository=FakeLeadRepository((lead,)),
        campaign_admin_repository=campaign_repository,
        campaign_enrollment_repository=enrollment_repository,
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=starter,
        event_bus=FakeEventBus(),
    )

    app.dependency_overrides[get_workspace_actor] = lambda: _actor(role)
    app.dependency_overrides[get_lead_manual_enrollment_bundle] = lambda: bundle
    return LeadManualEnrollmentTestClient(
        client=TestClient(app),
        starter=starter,
        session=session,
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