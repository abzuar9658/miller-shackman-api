from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.conversations import (
    ConversationStatus,
    InboundMessageClassificationStatus,
    canonical_crm_event_identity,
)
from app.domain.leads import (
    ActivityReliability,
    CanonicalLeadRecord,
    CRMProvider,
    LeadClassificationReason,
    LeadType,
)
from app.infrastructure.persistence.postgres.lead_activity_repository import (
    PostgresLeadActivityRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import (
    ConversationModel,
    CrmConversationEventModel,
    ExternalEventModel,
    InboundMessageModel,
    WorkspaceModel,
)
from app.infrastructure.persistence.postgres.workflow_models import (  # noqa: F401
    LeadWorkflowModel,
)

NOW = datetime(2026, 7, 23, 17, 22, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
LEAD_ID = UUID("22222222-2222-2222-2222-222222222222")
CONVERSATION_ID = UUID("33333333-3333-3333-3333-333333333333")


@pytest.mark.asyncio
async def test_list_for_lead_prefers_inbound_business_outcome_status(
    postgres_session: AsyncSession,
) -> None:
    await _seed_workspace(postgres_session)
    await PostgresLeadRepository(postgres_session).upsert(_lead())
    postgres_session.add(
        ConversationModel(
            conversation_id=CONVERSATION_ID,
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            campaign_id=None,
            workflow_id=None,
            status=ConversationStatus.PAUSED.value,
            ai_interaction_count=0,
            last_message_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    postgres_session.add_all(
        [
            _external_event(
                UUID("44444444-4444-4444-4444-444444444444"),
                "evt-review",
                {
                    "decision": {"inbound_action": "pause_for_review"},
                    "workflow": {"to_state": "paused"},
                },
                NOW,
            ),
            _external_event(
                UUID("55555555-5555-5555-5555-555555555555"),
                "evt-handoff",
                {
                    "decision": {"inbound_action": "human_handoff"},
                    "workflow": {"to_state": "human_handoff"},
                },
                NOW.replace(minute=23),
            ),
            _external_event(
                UUID("66666666-6666-6666-6666-666666666666"),
                "evt-continue",
                {
                    "decision": {"inbound_action": "continue_ai"},
                    "workflow": {"to_state": "waiting_for_response"},
                },
                NOW.replace(minute=24),
            ),
        ]
    )
    postgres_session.add_all(
        [
            _inbound_message(
                UUID("77777777-7777-7777-7777-777777777777"),
                "msg-review",
                UUID("44444444-4444-4444-4444-444444444444"),
                "Hmm maybe, not sure yet.",
                InboundMessageClassificationStatus.FAILED.value,
                NOW,
            ),
            _inbound_message(
                UUID("88888888-8888-8888-8888-888888888888"),
                "msg-handoff",
                UUID("55555555-5555-5555-5555-555555555555"),
                "Can an agent call me today?",
                InboundMessageClassificationStatus.CLASSIFIED.value,
                NOW.replace(minute=23),
            ),
            _inbound_message(
                UUID("99999999-9999-9999-9999-999999999999"),
                "msg-continue",
                UUID("66666666-6666-6666-6666-666666666666"),
                "Thanks, sounds good.",
                InboundMessageClassificationStatus.CLASSIFIED.value,
                NOW.replace(minute=24),
            ),
        ]
    )
    await postgres_session.commit()

    items = await PostgresLeadActivityRepository(postgres_session).list_for_lead(
        WORKSPACE_ID,
        LEAD_ID,
    )

    assert [item.status for item in items] == [
        "waiting_for_response",
        "human_handoff",
        "pause_for_review",
    ]


@pytest.mark.asyncio
async def test_list_for_lead_returns_rich_crm_conversation_event_content(
    postgres_session: AsyncSession,
) -> None:
    await _seed_workspace(postgres_session)
    await PostgresLeadRepository(postgres_session).upsert(_lead())
    postgres_session.add(
        CrmConversationEventModel(
            crm_conversation_event_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            conversation_id=None,
            crm_provider="follow_up_boss",
            crm_activity_id="call:123",
            canonical_identity=canonical_crm_event_identity(
                activity_type="Call",
                occurred_at=NOW,
                content="Agent Ada: Hello there.\nJordan Buyer: I will call back next week.",
                direction="inbound",
            ),
            activity_type="Call",
            direction="inbound",
            occurred_at=NOW,
            content="Agent Ada: Hello there.\nJordan Buyer: I will call back next week.",
            actor_agent_id="demo-agent-001",
            actor_name="Agent Ada",
            details={"duration_seconds": 40, "call_outcome": "Connected"},
            transcript_segments=[
                {
                    "text": "Hello there.",
                    "speaker_name": "Agent Ada",
                    "speaker_role": "agent",
                    "started_at": NOW.isoformat(),
                },
                {
                    "text": "I will call back next week.",
                    "speaker_name": "Jordan Buyer",
                    "speaker_role": "lead",
                    "started_at": NOW.isoformat(),
                },
            ],
            source_payload_version="follow_up_boss/v1",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()

    items = await PostgresLeadActivityRepository(postgres_session).list_for_lead(
        WORKSPACE_ID,
        LEAD_ID,
    )

    assert len(items) == 1
    assert items[0].title == "CRM call logged"
    assert items[0].content == "Agent Ada: Hello there.\nJordan Buyer: I will call back next week."
    assert items[0].details == {"duration_seconds": 40, "call_outcome": "Connected"}
    assert len(items[0].transcript_segments) == 2
    assert items[0].transcript_segments[0].speaker_name == "Agent Ada"


async def _seed_workspace(postgres_session: AsyncSession) -> None:
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
    await postgres_session.flush()


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-activity-1",
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
        mapped_custom_fields={"display_name": "Jordan Buyer"},
        primary_email="jordan@example.com",
        primary_phone="+15550000000",
        has_email=True,
        has_phone=True,
        has_sms_capable_phone=True,
        email_count=1,
        phone_count=1,
        activity_reliability=ActivityReliability.RELIABLE,
    )


def _external_event(
    external_event_id: UUID,
    provider_event_id: str,
    processing_audit: dict[str, object],
    received_at: datetime,
) -> ExternalEventModel:
    return ExternalEventModel(
        external_event_id=external_event_id,
        workspace_id=WORKSPACE_ID,
        provider="twilio",
        event_type="inbound_message.received",
        provider_event_id=provider_event_id,
        crm_lead_id="crm-activity-1",
        lead_id=LEAD_ID,
        received_at=received_at,
        processed_at=received_at,
        status="processed",
        payload_redacted={"processing_audit": processing_audit},
        failure_reason=None,
        created_at=received_at,
        updated_at=received_at,
    )


def _inbound_message(
    inbound_message_id: UUID,
    provider_message_id: str,
    external_event_id: UUID,
    body: str,
    classification_status: str,
    received_at: datetime,
) -> InboundMessageModel:
    return InboundMessageModel(
        inbound_message_id=inbound_message_id,
        workspace_id=WORKSPACE_ID,
        conversation_id=CONVERSATION_ID,
        lead_id=LEAD_ID,
        channel="sms",
        provider="twilio",
        provider_message_id=provider_message_id,
        external_event_id=external_event_id,
        from_address_redacted="+15550000000",
        to_address_redacted="+15551111111",
        body=body,
        received_at=received_at,
        processed_at=received_at,
        classification_status=classification_status,
        created_at=received_at,
    )
