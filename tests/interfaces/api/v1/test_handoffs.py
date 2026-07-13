from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.domain.conversations import Handoff, HandoffReasonCode, HandoffStatus
from app.domain.identity import (
    AuthenticatedActor,
    User,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import (
    ActivityReliability,
    CanonicalLeadRecord,
    CRMProvider,
    LeadClassificationReason,
    LeadType,
)
from app.interfaces.api.dependencies.handoff import HandoffReadBundle, get_handoff_read_bundle
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.main import create_app
from tests.application.use_cases._handoff_read_fakes import (
    FakeHandoffRepository,
    FakeLeadRepository,
    FakeUserRepository,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000002")
OTHER_AGENT_ID = UUID("00000000-0000-0000-0000-000000000003")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000004")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000005")
OTHER_LEAD_ID = UUID("00000000-0000-0000-0000-000000000006")
HANDOFF_ID = UUID("00000000-0000-0000-0000-000000000007")
OTHER_HANDOFF_ID = UUID("00000000-0000-0000-0000-000000000008")


@dataclass
class HandoffTestClient:
    client: TestClient


def test_handoff_routes_return_list_and_detail_for_brokerage_admin() -> None:
    test_client = _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)

    list_response = test_client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/handoffs")
    detail_response = test_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/handoffs/{HANDOFF_ID}"
    )

    assert list_response.status_code == 200
    assert list_response.json()["handoffs"][0]["lead"]["display_name"] == "Quinn Demo"
    assert detail_response.status_code == 200
    assert detail_response.json()["assigned_agent_name"] == "Avery Demo Agent"
    assert detail_response.json()["recommended_next_action"].startswith("Review the latest reply")


def test_assigned_agent_only_sees_owned_handoffs() -> None:
    test_client = _client_for_role(WorkspaceMembershipRole.ASSIGNED_AGENT)

    response = test_client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/handoffs")

    assert response.status_code == 200
    assert [item["handoff"]["handoff_id"] for item in response.json()["handoffs"]] == [
        str(HANDOFF_ID)
    ]


def test_assigned_agent_cannot_view_unowned_handoff_detail() -> None:
    test_client = _client_for_role(WorkspaceMembershipRole.ASSIGNED_AGENT)

    response = test_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/handoffs/{OTHER_HANDOFF_ID}"
    )

    assert response.status_code == 403
    assert response.json()["detail"] == ["permission_denied"]


def _client_for_role(role: WorkspaceMembershipRole) -> HandoffTestClient:
    app = create_app()
    handoff_repository = FakeHandoffRepository()
    lead_repository = FakeLeadRepository()
    user_repository = FakeUserRepository()

    handoff_repository.handoffs[HANDOFF_ID] = _handoff(HANDOFF_ID, LEAD_ID)
    handoff_repository.handoffs[OTHER_HANDOFF_ID] = _handoff(OTHER_HANDOFF_ID, OTHER_LEAD_ID)
    lead_repository.leads[LEAD_ID] = _lead(LEAD_ID, "Quinn Demo", ACTOR_ID)
    lead_repository.leads[OTHER_LEAD_ID] = _lead(OTHER_LEAD_ID, "Parker Demo", OTHER_AGENT_ID)
    user_repository.users[ACTOR_ID] = _user(ACTOR_ID, "Avery Demo Agent")
    bundle = HandoffReadBundle(
        handoff_repository=handoff_repository,
        lead_repository=lead_repository,
        user_repository=user_repository,
    )

    app.dependency_overrides[get_workspace_actor] = lambda: _actor(role)
    app.dependency_overrides[get_handoff_read_bundle] = lambda: bundle
    return HandoffTestClient(client=TestClient(app))


def _handoff(handoff_id: UUID, lead_id: UUID) -> Handoff:
    return Handoff(
        handoff_id=handoff_id,
        workspace_id=WORKSPACE_ID,
        lead_id=lead_id,
        reason_code=HandoffReasonCode.HUMAN_REQUESTED,
        summary="Lead asked to speak with a person.",
        latest_inbound_text="Can an agent call me today?",
        preferences={"next_action": "call_today"},
        status=HandoffStatus.CREATED,
        created_at=NOW.replace(minute=30) if handoff_id == HANDOFF_ID else NOW,
    )


def _lead(lead_id: UUID, display_name: str, assigned_agent_user_id: UUID) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=lead_id,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id=f"crm-{lead_id}",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        assigned_agent_crm_id="demo-agent-001",
        assigned_agent_name_present=True,
        has_accountable_owner=True,
        ownership_last_changed_at=NOW,
        lead_type=LeadType.BUYER,
        classification_reason=LeadClassificationReason.CRM_TYPE_BUYER,
        lead_source="test",
        lead_stage="prospect",
        created_via="test",
        mapped_custom_fields={
            "display_name": display_name,
            "assigned_agent_user_id": str(assigned_agent_user_id),
        },
        primary_email=f"{display_name.lower().split()[0]}@example.com",
        primary_phone="+15550000000",
        has_email=True,
        has_phone=True,
        has_sms_capable_phone=True,
        email_count=1,
        phone_count=1,
        activity_reliability=ActivityReliability.RELIABLE,
    )


def _user(user_id: UUID, full_name: str) -> User:
    return User(
        user_id=user_id,
        email=f"{full_name.lower().replace(' ', '.')}@example.com",
        email_normalized=f"{full_name.lower().replace(' ', '.')}@example.com",
        full_name=full_name,
        status=UserStatus.ACTIVE,
        email_verified_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _actor(role: WorkspaceMembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=MEMBERSHIP_ID,
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )
