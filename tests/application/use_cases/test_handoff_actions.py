import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.use_cases.handoff_actions import (
    HandoffActionReasonCode,
    HandoffActionStatus,
    acknowledge_handoff,
    reassign_handoff,
)
from app.domain.conversations import Handoff, HandoffReasonCode, HandoffStatus
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembership,
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
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000002")
OTHER_AGENT_ID = UUID("00000000-0000-0000-0000-000000000003")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000004")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000005")
HANDOFF_ID = UUID("00000000-0000-0000-0000-000000000007")


class FakeMembershipRepository:
    def __init__(self) -> None:
        self.memberships: dict[tuple[UUID, UUID], WorkspaceMembership] = {}

    async def get_by_id(self, membership_id: UUID) -> WorkspaceMembership | None:
        for membership in self.memberships.values():
            if membership.membership_id == membership_id:
                return membership
        return None

    async def get_by_user_and_workspace(
        self,
        user_id: UUID,
        workspace_id: UUID,
    ) -> WorkspaceMembership | None:
        return self.memberships.get((user_id, workspace_id))

    async def list_by_user_id(self, user_id: UUID) -> tuple[WorkspaceMembership, ...]:
        return tuple(m for (uid, _), m in self.memberships.items() if uid == user_id)

    async def list_by_workspace_id(
        self,
        workspace_id: UUID,
    ) -> tuple[WorkspaceMembership, ...]:
        return tuple(m for (_, wid), m in self.memberships.items() if wid == workspace_id)

    async def save(self, membership: WorkspaceMembership) -> WorkspaceMembership:
        self.memberships[(membership.user_id, membership.workspace_id)] = membership
        return membership


def test_manager_acknowledges_open_handoff() -> None:
    handoff_repository = FakeHandoffRepository()
    lead_repository = FakeLeadRepository()
    handoff_repository.handoffs[HANDOFF_ID] = _handoff(HandoffStatus.NOTIFIED)

    result = asyncio.run(
        acknowledge_handoff(
            actor=_actor(WorkspaceMembershipRole.MANAGER),
            workspace_id=WORKSPACE_ID,
            handoff_id=HANDOFF_ID,
            handoff_repository=handoff_repository,
            lead_repository=lead_repository,
            now=NOW,
        )
    )

    assert result.status == HandoffActionStatus.ACKNOWLEDGED
    assert result.handoff is not None
    assert result.handoff.status == HandoffStatus.ACKNOWLEDGED
    assert result.handoff.acknowledged_at == NOW
    assert handoff_repository.handoffs[HANDOFF_ID].status == HandoffStatus.ACKNOWLEDGED


def test_acknowledge_is_idempotent() -> None:
    handoff_repository = FakeHandoffRepository()
    lead_repository = FakeLeadRepository()
    already = _handoff(HandoffStatus.ACKNOWLEDGED, acknowledged_at=NOW - timedelta(hours=1))
    handoff_repository.handoffs[HANDOFF_ID] = already

    result = asyncio.run(
        acknowledge_handoff(
            actor=_actor(WorkspaceMembershipRole.MANAGER),
            workspace_id=WORKSPACE_ID,
            handoff_id=HANDOFF_ID,
            handoff_repository=handoff_repository,
            lead_repository=lead_repository,
            now=NOW,
        )
    )

    assert result.status == HandoffActionStatus.ALREADY_ACKNOWLEDGED
    assert result.handoff is not None
    assert result.handoff.acknowledged_at == NOW - timedelta(hours=1)


def test_assigned_agent_can_acknowledge_own_handoff() -> None:
    handoff_repository = FakeHandoffRepository()
    lead_repository = FakeLeadRepository()
    lead_repository.leads[LEAD_ID] = _lead(assigned_agent_user_id=ACTOR_ID)
    handoff_repository.handoffs[HANDOFF_ID] = _handoff(HandoffStatus.CREATED)

    result = asyncio.run(
        acknowledge_handoff(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
            workspace_id=WORKSPACE_ID,
            handoff_id=HANDOFF_ID,
            handoff_repository=handoff_repository,
            lead_repository=lead_repository,
            now=NOW,
        )
    )

    assert result.status == HandoffActionStatus.ACKNOWLEDGED


def test_assigned_agent_cannot_acknowledge_unowned_handoff() -> None:
    handoff_repository = FakeHandoffRepository()
    lead_repository = FakeLeadRepository()
    lead_repository.leads[LEAD_ID] = _lead(assigned_agent_user_id=OTHER_AGENT_ID)
    handoff_repository.handoffs[HANDOFF_ID] = _handoff(HandoffStatus.CREATED)

    result = asyncio.run(
        acknowledge_handoff(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
            workspace_id=WORKSPACE_ID,
            handoff_id=HANDOFF_ID,
            handoff_repository=handoff_repository,
            lead_repository=lead_repository,
            now=NOW,
        )
    )

    assert result.status == HandoffActionStatus.REJECTED
    assert result.reasons == (HandoffActionReasonCode.PERMISSION_DENIED,)


def test_acknowledge_rejects_resolved_handoff() -> None:
    handoff_repository = FakeHandoffRepository()
    lead_repository = FakeLeadRepository()
    handoff_repository.handoffs[HANDOFF_ID] = _handoff(HandoffStatus.RESOLVED)

    result = asyncio.run(
        acknowledge_handoff(
            actor=_actor(WorkspaceMembershipRole.MANAGER),
            workspace_id=WORKSPACE_ID,
            handoff_id=HANDOFF_ID,
            handoff_repository=handoff_repository,
            lead_repository=lead_repository,
            now=NOW,
        )
    )

    assert result.status == HandoffActionStatus.REJECTED
    assert result.reasons == (HandoffActionReasonCode.HANDOFF_NOT_OPEN,)


def test_acknowledge_missing_handoff_returns_not_found() -> None:
    result = asyncio.run(
        acknowledge_handoff(
            actor=_actor(WorkspaceMembershipRole.MANAGER),
            workspace_id=WORKSPACE_ID,
            handoff_id=HANDOFF_ID,
            handoff_repository=FakeHandoffRepository(),
            lead_repository=FakeLeadRepository(),
            now=NOW,
        )
    )

    assert result.status == HandoffActionStatus.NOT_FOUND


def test_manager_reassigns_handoff_to_active_member() -> None:
    handoff_repository = FakeHandoffRepository()
    membership_repository = FakeMembershipRepository()
    handoff_repository.handoffs[HANDOFF_ID] = _handoff(HandoffStatus.NOTIFIED)
    membership_repository.memberships[(OTHER_AGENT_ID, WORKSPACE_ID)] = _membership(
        OTHER_AGENT_ID,
        WorkspaceMembershipStatus.ACTIVE,
    )

    result = asyncio.run(
        reassign_handoff(
            actor=_actor(WorkspaceMembershipRole.MANAGER),
            workspace_id=WORKSPACE_ID,
            handoff_id=HANDOFF_ID,
            assigned_agent_user_id=OTHER_AGENT_ID,
            handoff_repository=handoff_repository,
            membership_repository=membership_repository,
        )
    )

    assert result.status == HandoffActionStatus.REASSIGNED
    assert result.handoff is not None
    assert result.handoff.assigned_agent_user_id == OTHER_AGENT_ID
    assert handoff_repository.handoffs[HANDOFF_ID].assigned_agent_user_id == OTHER_AGENT_ID


def test_assigned_agent_cannot_reassign() -> None:
    handoff_repository = FakeHandoffRepository()
    membership_repository = FakeMembershipRepository()
    handoff_repository.handoffs[HANDOFF_ID] = _handoff(HandoffStatus.NOTIFIED)

    result = asyncio.run(
        reassign_handoff(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
            workspace_id=WORKSPACE_ID,
            handoff_id=HANDOFF_ID,
            assigned_agent_user_id=OTHER_AGENT_ID,
            handoff_repository=handoff_repository,
            membership_repository=membership_repository,
        )
    )

    assert result.status == HandoffActionStatus.REJECTED
    assert result.reasons == (HandoffActionReasonCode.PERMISSION_DENIED,)


def test_reassign_rejects_inactive_member() -> None:
    handoff_repository = FakeHandoffRepository()
    membership_repository = FakeMembershipRepository()
    handoff_repository.handoffs[HANDOFF_ID] = _handoff(HandoffStatus.NOTIFIED)
    membership_repository.memberships[(OTHER_AGENT_ID, WORKSPACE_ID)] = _membership(
        OTHER_AGENT_ID,
        WorkspaceMembershipStatus.DISABLED,
    )

    result = asyncio.run(
        reassign_handoff(
            actor=_actor(WorkspaceMembershipRole.MANAGER),
            workspace_id=WORKSPACE_ID,
            handoff_id=HANDOFF_ID,
            assigned_agent_user_id=OTHER_AGENT_ID,
            handoff_repository=handoff_repository,
            membership_repository=membership_repository,
        )
    )

    assert result.status == HandoffActionStatus.REJECTED
    assert result.reasons == (HandoffActionReasonCode.ASSIGNEE_NOT_ACTIVE_MEMBER,)


def test_reassign_rejects_closed_handoff() -> None:
    handoff_repository = FakeHandoffRepository()
    membership_repository = FakeMembershipRepository()
    handoff_repository.handoffs[HANDOFF_ID] = _handoff(HandoffStatus.CANCELLED)
    membership_repository.memberships[(OTHER_AGENT_ID, WORKSPACE_ID)] = _membership(
        OTHER_AGENT_ID,
        WorkspaceMembershipStatus.ACTIVE,
    )

    result = asyncio.run(
        reassign_handoff(
            actor=_actor(WorkspaceMembershipRole.MANAGER),
            workspace_id=WORKSPACE_ID,
            handoff_id=HANDOFF_ID,
            assigned_agent_user_id=OTHER_AGENT_ID,
            handoff_repository=handoff_repository,
            membership_repository=membership_repository,
        )
    )

    assert result.status == HandoffActionStatus.REJECTED
    assert result.reasons == (HandoffActionReasonCode.HANDOFF_NOT_OPEN,)


def _handoff(
    status: HandoffStatus,
    *,
    acknowledged_at: datetime | None = None,
) -> Handoff:
    return Handoff(
        handoff_id=HANDOFF_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        reason_code=HandoffReasonCode.HUMAN_REQUESTED,
        summary="Lead asked to speak with a person.",
        status=status,
        created_at=NOW - timedelta(hours=2),
        acknowledged_at=acknowledged_at,
    )


def _lead(*, assigned_agent_user_id: UUID) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id=f"crm-{LEAD_ID}",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        assigned_agent_crm_id="demo-agent-001",
        assigned_agent_user_id=assigned_agent_user_id,
        effective_owner_user_id=assigned_agent_user_id,
        assigned_agent_name_present=True,
        has_accountable_owner=True,
        ownership_last_changed_at=NOW,
        lead_type=LeadType.BUYER,
        classification_reason=LeadClassificationReason.CRM_TYPE_BUYER,
        lead_source="test",
        lead_stage="prospect",
        created_via="test",
        primary_email="quinn@example.com",
        primary_phone="+15550000000",
        has_email=True,
        has_phone=True,
        has_sms_capable_phone=True,
        email_count=1,
        phone_count=1,
        activity_reliability=ActivityReliability.RELIABLE,
    )


def _membership(
    user_id: UUID,
    status: WorkspaceMembershipStatus,
) -> WorkspaceMembership:
    return WorkspaceMembership(
        membership_id=MEMBERSHIP_ID,
        workspace_id=WORKSPACE_ID,
        user_id=user_id,
        role=WorkspaceMembershipRole.ASSIGNED_AGENT,
        status=status,
        created_at=NOW - timedelta(days=30),
        updated_at=NOW - timedelta(days=30),
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
