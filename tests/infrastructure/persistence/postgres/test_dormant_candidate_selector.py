from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.persistence.postgres.dormant_candidate_selector import (
    PostgresDormantCandidateSelector,
)
from app.infrastructure.persistence.postgres.models import (
    CampaignModel,
    LeadModel,
    UserModel,
    WorkspaceModel,
)


@pytest.mark.asyncio
async def test_selects_dormant_leads(postgres_session: AsyncSession) -> None:
    workspace_id = uuid4()
    campaign_id = uuid4()
    lead_id = uuid4()
    actor_user_id = uuid4()
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

    selector = PostgresDormantCandidateSelector(postgres_session)
    candidates = await selector.select_candidates(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        threshold_days=60,
        limit=10,
        now=now,
    )

    assert len(candidates) == 1
    assert candidates[0].lead_id == lead_id
