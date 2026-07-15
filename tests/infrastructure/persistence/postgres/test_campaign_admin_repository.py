from datetime import UTC, datetime, time
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.admin import (
    CampaignAdminAuditAction,
    CampaignAdminAuditLog,
    CampaignAdminCadenceStep,
    CampaignAdminCampaign,
    CampaignAdminVersion,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.compliance.contactability import ContactChannel
from app.infrastructure.persistence.postgres.campaign_admin_repository import (
    PostgresCampaignAdminAuditLogRepository,
    PostgresCampaignAdminRepository,
)
from app.infrastructure.persistence.postgres.models import UserModel, WorkspaceModel

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
CAMPAIGN_ID = UUID("22222222-2222-2222-2222-222222222222")
VERSION_ID = UUID("33333333-3333-3333-3333-333333333333")
STEP_ID = UUID("44444444-4444-4444-4444-444444444444")
USER_ID = UUID("55555555-5555-5555-5555-555555555555")
AUDIT_ID = UUID("66666666-6666-6666-6666-666666666666")


@pytest.mark.asyncio
async def test_campaign_admin_repository_saves_campaign_version_steps_and_audit(
    postgres_session: AsyncSession,
) -> None:
    await _create_workspace_and_user(postgres_session)
    repository = PostgresCampaignAdminRepository(postgres_session)
    audit_repository = PostgresCampaignAdminAuditLogRepository(postgres_session)

    campaign = await repository.save_campaign(_campaign())
    version = await repository.save_version(_version())
    steps = await repository.replace_cadence_steps(WORKSPACE_ID, VERSION_ID, (_step(),))
    audit_log = await audit_repository.append(_audit_log())

    assert campaign == _campaign()
    assert version == _version()
    assert steps == (_step(),)
    assert audit_log.action == CampaignAdminAuditAction.DRAFT_CREATED
    assert await repository.list_campaigns(WORKSPACE_ID) == (campaign,)
    assert await repository.get_campaign_by_name(WORKSPACE_ID, "Dormant Buyers") == campaign
    assert await repository.get_latest_draft_version(WORKSPACE_ID, CAMPAIGN_ID) == version
    assert await repository.get_latest_version(WORKSPACE_ID, CAMPAIGN_ID) == version
    assert await repository.get_latest_version_number(WORKSPACE_ID, CAMPAIGN_ID) == 1
    assert await repository.get_cadence_steps(WORKSPACE_ID, VERSION_ID) == (_step(),)


def _campaign() -> CampaignAdminCampaign:
    return CampaignAdminCampaign(
        campaign_id=CAMPAIGN_ID,
        workspace_id=WORKSPACE_ID,
        name="Dormant Buyers",
        status=CampaignStatus.DRAFT,
        active_version_id=None,
        created_by_user_id=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _version() -> CampaignAdminVersion:
    return CampaignAdminVersion(
        campaign_version_id=VERSION_ID,
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        version_number=1,
        status=CampaignVersionStatus.DRAFT,
        enabled_channels=(ContactChannel.EMAIL,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="America/Chicago",
        sms_compliance_required=True,
        preflight_digest_enabled=True,
        crm_enrollment_tag="ai_nurture",
        allow_assigned_agent_manual_enrollment=True,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        created_by_user_id=USER_ID,
        created_at=NOW,
    )


def _step() -> CampaignAdminCadenceStep:
    return CampaignAdminCadenceStep(
        cadence_step_id=STEP_ID,
        workspace_id=WORKSPACE_ID,
        campaign_version_id=VERSION_ID,
        step_order=1,
        channel=ContactChannel.EMAIL,
        delay_hours=24,
        message_goal="Check whether the lead is still considering a move.",
        template_key="dormant-email-1",
        max_attempts=1,
        created_at=NOW,
    )


def _audit_log() -> CampaignAdminAuditLog:
    return CampaignAdminAuditLog(
        audit_log_id=AUDIT_ID,
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=VERSION_ID,
        action=CampaignAdminAuditAction.DRAFT_CREATED,
        actor_user_id=USER_ID,
        details={"campaign_name": "Dormant Buyers"},
        created_at=NOW,
    )


async def _create_workspace_and_user(postgres_session: AsyncSession) -> None:
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
            email="admin@example.com",
            email_normalized="admin@example.com",
            full_name="Admin User",
            status="active",
            email_verified_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()
