from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.conversations import Handoff, HandoffReasonCode, HandoffStatus
from app.domain.identity import User, UserStatus
from app.domain.leads import (
    ActivityReliability,
    CanonicalLeadRecord,
    CRMProvider,
    LeadClassificationReason,
    LeadType,
)
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresHandoffRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import PostgresUserRepository
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import WorkspaceModel

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
USER_ID = UUID("22222222-2222-2222-2222-222222222222")
LEAD_ID = UUID("33333333-3333-3333-3333-333333333333")
OTHER_LEAD_ID = UUID("44444444-4444-4444-4444-444444444444")
HANDOFF_ID = UUID("55555555-5555-5555-5555-555555555555")
OTHER_HANDOFF_ID = UUID("66666666-6666-6666-6666-666666666666")


@pytest.mark.asyncio
async def test_handoff_repository_lists_handoffs_in_created_order(
    postgres_session: AsyncSession,
) -> None:
    await _create_workspace(postgres_session)
    await PostgresUserRepository(postgres_session).save(_user())
    lead_repository = PostgresLeadRepository(postgres_session)
    await lead_repository.upsert(_lead(LEAD_ID, "Quinn Demo"))
    await lead_repository.upsert(_lead(OTHER_LEAD_ID, "Parker Demo"))
    repository = PostgresHandoffRepository(postgres_session)

    older = await repository.save(_handoff(HANDOFF_ID, LEAD_ID, NOW))
    newer = await repository.save(_handoff(OTHER_HANDOFF_ID, OTHER_LEAD_ID, NOW.replace(hour=13)))

    assert await repository.get_by_id(WORKSPACE_ID, HANDOFF_ID) == older
    assert await repository.list_handoffs(WORKSPACE_ID) == (newer, older)


async def _create_workspace(postgres_session: AsyncSession) -> None:
    postgres_session.add(
        WorkspaceModel(
            workspace_id=WORKSPACE_ID,
            name="Test Workspace",
            status="active",
            default_timezone="UTC",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()


def _user() -> User:
    return User(
        user_id=USER_ID,
        email="agent@example.com",
        email_normalized="agent@example.com",
        full_name="Avery Demo Agent",
        status=UserStatus.ACTIVE,
        email_verified_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _lead(lead_id: UUID, display_name: str) -> CanonicalLeadRecord:
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
            "assigned_agent_user_id": str(USER_ID),
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


def _handoff(handoff_id: UUID, lead_id: UUID, created_at: datetime) -> Handoff:
    return Handoff(
        handoff_id=handoff_id,
        workspace_id=WORKSPACE_ID,
        lead_id=lead_id,
        reason_code=HandoffReasonCode.HUMAN_REQUESTED,
        summary="Lead asked to speak with a person.",
        latest_inbound_text="Can an agent call me today?",
        preferences={"next_action": "call_today"},
        status=HandoffStatus.CREATED,
        created_at=created_at,
        assigned_agent_user_id=USER_ID,
        assigned_agent_crm_id="demo-agent-001",
    )
