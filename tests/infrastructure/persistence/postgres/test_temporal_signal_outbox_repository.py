from datetime import UTC, datetime, time, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.workflows import (
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    TemporalSignalOutboxStatus,
)
from app.infrastructure.persistence.postgres.models import (
    CampaignModel,
    CampaignVersionModel,
    LeadModel,
    UserModel,
    WorkspaceModel,
)
from app.infrastructure.persistence.postgres.temporal_signal_outbox_repository import (
    PostgresTemporalSignalOutboxRepository,
)
from app.infrastructure.persistence.postgres.workflow_models import (
    CampaignEnrollmentModel,
    LeadWorkflowModel,
)

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("21111111-1111-1111-1111-111111111111")
USER_ID = UUID("21111111-1111-1111-1111-111111111112")
LEAD_ID = UUID("21111111-1111-1111-1111-111111111113")
CAMPAIGN_ID = UUID("21111111-1111-1111-1111-111111111114")
CAMPAIGN_VERSION_ID = UUID("21111111-1111-1111-1111-111111111115")
ENROLLMENT_ID = UUID("21111111-1111-1111-1111-111111111116")
WORKFLOW_ID = UUID("21111111-1111-1111-1111-111111111117")
SIGNAL_ID = UUID("21111111-1111-1111-1111-111111111118")
EXTERNAL_EVENT_ID = UUID("21111111-1111-1111-1111-111111111119")


@pytest.mark.asyncio
async def test_temporal_signal_outbox_repository_appends_claims_and_marks_sent(
    postgres_session: AsyncSession,
) -> None:
    await _create_workflow_graph(postgres_session)
    repository = PostgresTemporalSignalOutboxRepository(postgres_session)

    appended = await repository.append(_entry())
    claimed = await repository.claim_available_batch(
        now=NOW,
        limit=10,
        lease_duration=timedelta(minutes=5),
        max_attempts=3,
    )

    assert appended.status == TemporalSignalOutboxStatus.PENDING
    assert len(claimed) == 1
    assert claimed[0].status == TemporalSignalOutboxStatus.DISPATCHING
    assert claimed[0].attempt_count == 1
    assert claimed[0].claimed_until == NOW + timedelta(minutes=5)

    sent = await repository.mark_sent(claimed[0].temporal_signal_id, now=NOW)
    assert sent.status == TemporalSignalOutboxStatus.SENT
    assert sent.sent_at == NOW


@pytest.mark.asyncio
async def test_temporal_signal_outbox_repository_deduplicates_and_reclaims_failed_entries(
    postgres_session: AsyncSession,
) -> None:
    await _create_workflow_graph(postgres_session)
    repository = PostgresTemporalSignalOutboxRepository(postgres_session)

    first = await repository.append(_entry())
    duplicate = await repository.append(_entry())
    claimed = await repository.claim_available_batch(
        now=NOW,
        limit=10,
        lease_duration=timedelta(minutes=5),
        max_attempts=3,
    )
    failed = await repository.mark_failed(
        claimed[0].temporal_signal_id,
        error="temporal unavailable",
        available_at=NOW + timedelta(minutes=1),
        now=NOW,
    )

    not_ready = await repository.claim_available_batch(
        now=NOW + timedelta(seconds=30),
        limit=10,
        lease_duration=timedelta(minutes=5),
        max_attempts=3,
    )
    ready = await repository.claim_available_batch(
        now=NOW + timedelta(minutes=1),
        limit=10,
        lease_duration=timedelta(minutes=5),
        max_attempts=3,
    )

    assert duplicate.temporal_signal_id == first.temporal_signal_id
    assert failed.status == TemporalSignalOutboxStatus.FAILED
    assert failed.last_error == "temporal unavailable"
    assert not_ready == ()
    assert len(ready) == 1
    assert ready[0].attempt_count == 2


def _entry() -> TemporalSignalOutboxEntry:
    return TemporalSignalOutboxEntry(
        temporal_signal_id=SIGNAL_ID,
        workspace_id=WORKSPACE_ID,
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="workflow-123",
        signal_name=TemporalSignalName.INBOUND_PROCESSED,
        payload={
            "lead_id": str(LEAD_ID),
            "occurred_at": NOW.isoformat(),
            "external_event_id": str(EXTERNAL_EVENT_ID),
            "conversation_id": None,
            "inbound_message_id": None,
            "workflow_transition_id": None,
            "inbound_action": "human_handoff",
            "reason": "human_requested",
        },
        idempotency_key=f"inbound-processed:{EXTERNAL_EVENT_ID}",
        status=TemporalSignalOutboxStatus.PENDING,
        attempt_count=0,
        available_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


async def _create_workflow_graph(postgres_session: AsyncSession) -> None:
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
    postgres_session.add(
        UserModel(
            user_id=USER_ID,
            email="owner@example.com",
            email_normalized="owner@example.com",
            full_name="Owner",
            status="active",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    postgres_session.add(
        LeadModel(
            lead_id=LEAD_ID,
            workspace_id=WORKSPACE_ID,
            crm_provider="follow_up_boss",
            crm_lead_id="crm-123",
            source_payload_version="test:v1",
            facts_derived_at=NOW,
            assigned_agent_name_present=False,
            has_accountable_owner=True,
            lead_type="buyer",
            classification_reason="imported",
            lead_source="website",
            lead_stage="nurture",
            created_via="sync",
            tags=[],
            mapped_custom_fields={},
            primary_phone="+15555550123",
            primary_email="lead@example.com",
            has_email=True,
            has_phone=True,
            has_sms_capable_phone=True,
            email_count=1,
            phone_count=1,
            sms_permission_status="unknown",
            email_permission_status="unknown",
            sms_opted_out=False,
            email_unsubscribed=False,
            suppression_types=[],
            permission_evidence={},
            activity_reliability="trusted",
            latest_property_context_present=False,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()

    postgres_session.add(
        CampaignModel(
            campaign_id=CAMPAIGN_ID,
            workspace_id=WORKSPACE_ID,
            name="Dormant Reengagement",
            status="active",
            active_version_id=None,
            created_by_user_id=USER_ID,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()

    postgres_session.add(
        CampaignVersionModel(
            campaign_version_id=CAMPAIGN_VERSION_ID,
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            version_number=1,
            status="published",
            enabled_channels=["sms"],
            daily_start_cap=50,
            dormant_threshold_days=60,
            quiet_hours_start=time(10, 0),
            quiet_hours_end=time(17, 0),
            timezone="UTC",
            sms_compliance_required=True,
            preflight_digest_enabled=False,
            allow_assigned_agent_manual_enrollment=True,
            prompt_version="reply-classifier:v1",
            approved_model="openai/gpt-4o-mini",
            created_by_user_id=USER_ID,
            created_at=NOW,
        )
    )
    await postgres_session.commit()

    postgres_session.add(
        CampaignEnrollmentModel(
            campaign_enrollment_id=ENROLLMENT_ID,
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
            lead_id=LEAD_ID,
            source="manual",
            status="active",
            reason_codes=[],
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()

    postgres_session.add(
        LeadWorkflowModel(
            workflow_id=WORKFLOW_ID,
            temporal_workflow_id="workflow-123",
            workspace_id=WORKSPACE_ID,
            campaign_enrollment_id=ENROLLMENT_ID,
            campaign_id=CAMPAIGN_ID,
            lead_id=LEAD_ID,
            state="waiting_for_response",
            last_transition_at=NOW,
            state_version=3,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()