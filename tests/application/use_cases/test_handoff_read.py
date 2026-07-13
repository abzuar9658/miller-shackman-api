import asyncio
from datetime import UTC, datetime
from uuid import UUID

from app.application.use_cases.handoff_read import (
    HandoffReadStatus,
    get_handoff_view,
    list_handoff_views,
)
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
RESOLVED_HANDOFF_ID = UUID("00000000-0000-0000-0000-000000000009")


def test_brokerage_admin_can_list_open_handoffs() -> None:
    handoff_repository = FakeHandoffRepository()
    lead_repository = FakeLeadRepository()
    user_repository = FakeUserRepository()
    user_repository.users[ACTOR_ID] = _user(ACTOR_ID, "Avery Demo Agent")
    lead_repository.leads[LEAD_ID] = _lead(LEAD_ID, "Quinn Demo", ACTOR_ID)
    lead_repository.leads[OTHER_LEAD_ID] = _lead(OTHER_LEAD_ID, "Parker Demo", OTHER_AGENT_ID)
    handoff_repository.handoffs[HANDOFF_ID] = _handoff(HANDOFF_ID, LEAD_ID, HandoffStatus.CREATED)
    handoff_repository.handoffs[OTHER_HANDOFF_ID] = _handoff(
        OTHER_HANDOFF_ID,
        OTHER_LEAD_ID,
        HandoffStatus.ACKNOWLEDGED,
    )
    handoff_repository.handoffs[RESOLVED_HANDOFF_ID] = _handoff(
        RESOLVED_HANDOFF_ID,
        LEAD_ID,
        HandoffStatus.RESOLVED,
    )

    result = asyncio.run(
        list_handoff_views(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            handoff_repository=handoff_repository,
            lead_repository=lead_repository,
            user_repository=user_repository,
        )
    )

    assert result.status == HandoffReadStatus.OK
    assert [view.handoff.handoff_id for view in result.views] == [OTHER_HANDOFF_ID, HANDOFF_ID]
    assert result.views[1].lead.display_name == "Quinn Demo"
    assert result.views[1].assigned_agent_name == "Avery Demo Agent"


def test_assigned_agent_only_sees_owned_handoffs() -> None:
    handoff_repository = FakeHandoffRepository()
    lead_repository = FakeLeadRepository()
    user_repository = FakeUserRepository()
    lead_repository.leads[LEAD_ID] = _lead(LEAD_ID, "Quinn Demo", ACTOR_ID)
    lead_repository.leads[OTHER_LEAD_ID] = _lead(OTHER_LEAD_ID, "Parker Demo", OTHER_AGENT_ID)
    handoff_repository.handoffs[HANDOFF_ID] = _handoff(HANDOFF_ID, LEAD_ID, HandoffStatus.CREATED)
    handoff_repository.handoffs[OTHER_HANDOFF_ID] = _handoff(
        OTHER_HANDOFF_ID,
        OTHER_LEAD_ID,
        HandoffStatus.CREATED,
    )

    result = asyncio.run(
        list_handoff_views(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
            workspace_id=WORKSPACE_ID,
            handoff_repository=handoff_repository,
            lead_repository=lead_repository,
            user_repository=user_repository,
        )
    )

    assert result.status == HandoffReadStatus.OK
    assert [view.handoff.handoff_id for view in result.views] == [HANDOFF_ID]


def test_handoff_detail_returns_not_found_when_handoff_is_missing() -> None:
    result = asyncio.run(
        get_handoff_view(
            actor=_actor(WorkspaceMembershipRole.MANAGER),
            workspace_id=WORKSPACE_ID,
            handoff_id=HANDOFF_ID,
            handoff_repository=FakeHandoffRepository(),
            lead_repository=FakeLeadRepository(),
            user_repository=FakeUserRepository(),
        )
    )

    assert result.status == HandoffReadStatus.NOT_FOUND
    assert result.reasons[0].value == "handoff_not_found"


def _handoff(handoff_id: UUID, lead_id: UUID, status: HandoffStatus) -> Handoff:
    return Handoff(
        handoff_id=handoff_id,
        workspace_id=WORKSPACE_ID,
        lead_id=lead_id,
        reason_code=HandoffReasonCode.HUMAN_REQUESTED,
        summary="Lead asked to speak with a person.",
        latest_inbound_text="Can an agent call me today?",
        preferences={"next_action": "call_today"},
        status=status,
        created_at=NOW if handoff_id == HANDOFF_ID else NOW.replace(minute=30),
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
