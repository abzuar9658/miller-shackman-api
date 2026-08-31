from dataclasses import replace
from datetime import UTC, datetime, time
from typing import cast
from uuid import UUID, uuid5

from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    CampaignExecutionRepository,
)
from app.application.services.pinned_campaign_version import resolve_pinned_campaign_config
from app.domain.campaigns.enrollment import (
    CampaignEnrollment,
    CampaignEnrollmentSource,
    CampaignEnrollmentStatus,
)
from app.domain.campaigns.execution import (
    CampaignCadenceStep,
    CampaignExecutionConfig,
    CampaignVersionStatus,
)
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.compliance.contactability import ContactChannel
from app.domain.workflows import LeadWorkflow, WorkflowState

NOW = datetime(2026, 8, 9, 15, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
LEAD_ID = UUID("22222222-2222-2222-2222-222222222222")
WORKFLOW_ID = UUID("33333333-3333-3333-3333-333333333333")
CAMPAIGN_ID = UUID("77777777-7777-7777-7777-777777777777")
ENROLLMENT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
PINNED_VERSION_ID = UUID("88888888-8888-8888-8888-888888888888")
ACTIVE_VERSION_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


class FakeCampaignExecutionRepository:
    def __init__(self, versions: dict[UUID, CampaignExecutionConfig]) -> None:
        self.versions = versions

    async def get_by_version_id(
        self,
        workspace_id: UUID,
        version_id: UUID,
    ) -> CampaignExecutionConfig | None:
        _ = workspace_id
        return self.versions.get(version_id)

    async def get_active_for_campaign(
        self,
        workspace_id: UUID,
        campaign_id: UUID,
    ) -> CampaignExecutionConfig | None:
        _ = (workspace_id, campaign_id)
        return self.versions.get(ACTIVE_VERSION_ID)


class FakeEnrollmentRepository:
    def __init__(self, enrollment: CampaignEnrollment | None) -> None:
        self.enrollment = enrollment

    async def get_by_id(
        self,
        workspace_id: UUID,
        campaign_enrollment_id: UUID,
    ) -> CampaignEnrollment | None:
        _ = (workspace_id, campaign_enrollment_id)
        return self.enrollment


async def test_resolves_the_version_the_workflow_was_enrolled_on() -> None:
    result = await _resolve(FakeEnrollmentRepository(_enrollment(PINNED_VERSION_ID)))

    assert result is not None
    assert result.campaign_version_id == PINNED_VERSION_ID
    assert result.version_status is CampaignVersionStatus.RETIRED


async def test_falls_back_to_active_version_without_an_enrollment_repository() -> None:
    result = await _resolve(None)

    assert result is not None
    assert result.campaign_version_id == ACTIVE_VERSION_ID


async def test_falls_back_to_active_version_when_the_enrollment_is_missing() -> None:
    result = await _resolve(FakeEnrollmentRepository(None))

    assert result is not None
    assert result.campaign_version_id == ACTIVE_VERSION_ID


async def _resolve(
    enrollment_repository: FakeEnrollmentRepository | None,
) -> CampaignExecutionConfig | None:
    repository = FakeCampaignExecutionRepository(
        {
            PINNED_VERSION_ID: replace(
                _config(PINNED_VERSION_ID),
                version_status=CampaignVersionStatus.RETIRED,
            ),
            ACTIVE_VERSION_ID: _config(ACTIVE_VERSION_ID),
        }
    )
    return await resolve_pinned_campaign_config(
        workspace_id=WORKSPACE_ID,
        workflow=_workflow(),
        campaign_execution_repository=cast(CampaignExecutionRepository, repository),
        campaign_enrollment_repository=cast(
            "CampaignEnrollmentRepository | None",
            enrollment_repository,
        ),
    )


def _workflow() -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture-1",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=WorkflowState.WAITING_FOR_RESPONSE,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _config(campaign_version_id: UUID) -> CampaignExecutionConfig:
    return CampaignExecutionConfig(
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=campaign_version_id,
        workspace_id=WORKSPACE_ID,
        campaign_name="Dormant leads",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(ContactChannel.SMS,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10),
        quiet_hours_end=time(17),
        timezone="UTC",
        preflight_digest_enabled=True,
        crm_enrollment_tag=None,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(
            CampaignCadenceStep(
                cadence_step_id=uuid5(campaign_version_id, "step-1"),
                workspace_id=WORKSPACE_ID,
                campaign_version_id=campaign_version_id,
                step_order=1,
                channel=ContactChannel.SMS,
                delay_hours=0,
                message_goal="Check in",
                template_key="step-1",
                max_attempts=1,
                created_at=NOW,
            ),
        ),
        created_at=NOW,
        published_at=NOW,
    )


def _enrollment(campaign_version_id: UUID) -> CampaignEnrollment:
    return CampaignEnrollment(
        campaign_enrollment_id=ENROLLMENT_ID,
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=campaign_version_id,
        lead_id=LEAD_ID,
        source=CampaignEnrollmentSource.DORMANT_SELECTOR,
        status=CampaignEnrollmentStatus.ACTIVE,
        eligible_at=NOW,
        enrolled_at=NOW,
        started_at=NOW,
        ended_at=None,
        created_by_user_id=None,
        reason_codes=(),
        created_at=NOW,
        updated_at=NOW,
    )
