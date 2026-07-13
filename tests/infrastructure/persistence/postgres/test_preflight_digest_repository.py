from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.preflight_digest import (
    PreflightDigestEntry,
    PreflightDigestIssueStatus,
    PreflightDigestNotificationRecord,
    PreflightDigestRecord,
    PreflightVetoRecord,
)
from app.infrastructure.persistence.postgres.models import (
    CampaignModel,
    LeadModel,
    PreflightVetoModel,
    UserModel,
    WorkspaceModel,
)
from app.infrastructure.persistence.postgres.preflight_digest_repository import (
    PostgresPreflightDigestRepository,
)


@pytest.mark.asyncio
async def test_round_trip_digest_and_vetoes(postgres_session: AsyncSession) -> None:
    workspace_id = uuid4()
    campaign_id = uuid4()
    lead_id = uuid4()
    actor_user_id = uuid4()
    batch_id = "batch-1"
    digest_id = str(uuid4())
    now = datetime.now(UTC)

    postgres_session.add(
        WorkspaceModel(
            workspace_id=workspace_id,
            name="Test",
            status="active",
            default_timezone="UTC",
            created_at=now,
            updated_at=now,
        )
    )
    postgres_session.add(
        UserModel(
            user_id=actor_user_id,
            email="actor@example.com",
            email_normalized="actor@example.com",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    await postgres_session.commit()

    postgres_session.add(
        CampaignModel(
            campaign_id=campaign_id,
            workspace_id=workspace_id,
            name="Test Campaign",
            status="active",
            active_version_id=None,
            created_by_user_id=actor_user_id,
            created_at=now,
            updated_at=now,
        )
    )
    postgres_session.add(
        LeadModel(
            lead_id=lead_id,
            workspace_id=workspace_id,
            crm_provider="follow_up_boss",
            crm_lead_id="crm-1",
            has_accountable_owner=True,
            lead_type="buyer",
            classification_reason="crm_type_buyer",
            activity_reliability="reliable",
            do_not_contact=False,
            has_email=True,
            sms_permission_status="unknown",
            email_permission_status="confirmed",
            last_meaningful_communication_at=now - timedelta(days=90),
            facts_derived_at=now,
            source_payload_version="1",
            created_at=now,
            updated_at=now,
        )
    )
    await postgres_session.commit()

    repository = PostgresPreflightDigestRepository(postgres_session)
    record = PreflightDigestRecord(
        digest_id=digest_id,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        batch_id=batch_id,
        status=PreflightDigestIssueStatus.ISSUED,
        entries=(
            PreflightDigestEntry(
                lead_id=lead_id,
                recipient_id="agent-1",
                recipient_destination="agent@example.com",
                display_name="Lead One",
            ),
        ),
        notification_records=(
            PreflightDigestNotificationRecord(
                recipient_id="agent-1",
                idempotency_key="key-1",
                accepted=True,
                provider_reference="ref-1",
                uncertain=False,
            ),
        ),
        digest_sent_at=now,
        veto_window_expires_at=now + timedelta(hours=24),
        vetoes=(),
    )
    await repository.save_digest(record)
    await postgres_session.commit()

    loaded = await repository.get_digest(workspace_id, campaign_id, batch_id)
    assert loaded is not None
    assert loaded.digest_id == digest_id
    assert loaded.status == PreflightDigestIssueStatus.ISSUED
    assert len(loaded.entries) == 1
    assert loaded.entries[0].lead_id == lead_id

    await repository.save_digest(
        PreflightDigestRecord(
            digest_id=digest_id,
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            batch_id=batch_id,
            status=loaded.status,
            entries=loaded.entries,
            notification_records=loaded.notification_records,
            digest_sent_at=loaded.digest_sent_at,
            veto_window_expires_at=loaded.veto_window_expires_at,
            vetoes=(
                PreflightVetoRecord(
                    lead_id=lead_id,
                    actor_id=str(actor_user_id),
                    recorded_at=now,
                    idempotency_key="veto-1",
                    reason="no longer interested",
                ),
            ),
        )
    )
    await postgres_session.commit()

    after_veto = await repository.get_digest(workspace_id, campaign_id, batch_id)
    assert after_veto is not None
    assert len(after_veto.vetoes) == 1
    assert after_veto.vetoes[0].lead_id == lead_id

    veto_rows = await postgres_session.execute(
        select(PreflightVetoModel).where(PreflightVetoModel.digest_id == UUID(digest_id))
    )
    assert len(veto_rows.scalars().all()) == 1
