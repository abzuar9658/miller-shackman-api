from datetime import UTC, datetime, time
from uuid import UUID

import pytest

from app.application.use_cases.process_crm_tag_campaign_enrollment import (
    CRMTagCampaignEnrollmentStatus,
    process_crm_tag_campaign_enrollment,
)
from app.domain.campaigns import CampaignStatus, CampaignVersionStatus
from app.domain.campaigns.execution import CampaignCadenceStep, CampaignExecutionConfig
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SmsComplianceState,
    WorkspaceContactPolicy,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from tests.application.use_cases._campaign_admin_fakes import FakeEventBus
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCampaignExecutionRepository,
    FakeWorkspaceContactPolicyRepository,
    FakeWorkspaceOperationalControlRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeLeadWorkflowRepository,
    FakeTemporalWorkflowStarter,
    FakeWorkflowTransitionRepository,
)

NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
LEAD_ID = UUID("22222222-2222-2222-2222-222222222222")
CAMPAIGN_ID = UUID("33333333-3333-3333-3333-333333333333")
CAMPAIGN_ID_2 = UUID("44444444-4444-4444-4444-444444444444")
VERSION_ID = UUID("55555555-5555-5555-5555-555555555555")
VERSION_ID_2 = UUID("66666666-6666-6666-6666-666666666666")
STEP_ID = UUID("77777777-7777-7777-7777-777777777777")


@pytest.mark.asyncio
async def test_starts_matching_campaign_from_configured_crm_tag() -> None:
    commit_calls: list[str] = []
    temporal = FakeTemporalWorkflowStarter()

    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=_lead(tags=("configured_tag",)),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(
                campaign_id=CAMPAIGN_ID,
                version_id=VERSION_ID,
                crm_enrollment_tag="configured_tag",
            )
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=FakeCampaignEnrollmentRepository(),
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=temporal,
        event_bus=FakeEventBus(),
        workspace_operational_control_repository=FakeWorkspaceOperationalControlRepository(None),
        commit=lambda: _record_commit(commit_calls),
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.STARTED
    assert result.campaign_id == CAMPAIGN_ID
    assert result.matched_tag == "configured_tag"
    assert commit_calls == ["commit"]
    assert len(temporal.calls) == 1


@pytest.mark.asyncio
async def test_returns_no_matching_campaign_when_tags_do_not_match_admin_config() -> None:
    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=_lead(tags=("some_other_tag",)),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(
                campaign_id=CAMPAIGN_ID,
                version_id=VERSION_ID,
                crm_enrollment_tag="configured_tag",
            )
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=FakeCampaignEnrollmentRepository(),
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=FakeTemporalWorkflowStarter(),
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.NO_MATCHING_CAMPAIGN
    assert result.campaign_id is None


@pytest.mark.asyncio
async def test_chooses_only_the_matching_campaign_when_multiple_are_active() -> None:
    configs = (
        _config(
            campaign_id=CAMPAIGN_ID,
            version_id=VERSION_ID,
            crm_enrollment_tag="non_matching",
        ),
        _config(
            campaign_id=CAMPAIGN_ID_2,
            version_id=VERSION_ID_2,
            crm_enrollment_tag="configured_tag",
        ),
    )
    enrollments = FakeCampaignEnrollmentRepository()

    result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=_lead(tags=("configured_tag",)),
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(configs),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=enrollments,
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=FakeTemporalWorkflowStarter(),
    )

    assert result.status == CRMTagCampaignEnrollmentStatus.STARTED
    assert result.campaign_id == CAMPAIGN_ID_2
    assert len(enrollments.enrollments) == 1
    saved = next(iter(enrollments.enrollments.values()))
    assert saved.campaign_id == CAMPAIGN_ID_2


def _config(
    *,
    campaign_id: UUID,
    version_id: UUID,
    crm_enrollment_tag: str | None,
) -> CampaignExecutionConfig:
    return CampaignExecutionConfig(
        campaign_id=campaign_id,
        campaign_version_id=version_id,
        workspace_id=WORKSPACE_ID,
        campaign_name="Configured Campaign",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(ContactChannel.EMAIL,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="UTC",
        sms_compliance_required=False,
        preflight_digest_enabled=True,
        crm_enrollment_tag=crm_enrollment_tag,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(
            CampaignCadenceStep(
                cadence_step_id=STEP_ID,
                workspace_id=WORKSPACE_ID,
                campaign_version_id=version_id,
                step_order=1,
                channel=ContactChannel.EMAIL,
                delay_hours=0,
                message_goal="Check in",
                template_key="email-1",
                max_attempts=1,
                created_at=NOW,
            ),
        ),
        created_at=NOW,
        published_at=NOW,
    )


def _contact_policy() -> WorkspaceContactPolicy:
    return WorkspaceContactPolicy(
        workspace_id=WORKSPACE_ID,
        sms_compliance_state=SmsComplianceState.APPROVED,
    )


def _lead(*, tags: tuple[str, ...]) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="Lead",
        assigned_agent_crm_id="agent-99",
        has_accountable_owner=True,
        tags=tags,
        primary_email="lead@example.com",
        has_email=True,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        do_not_contact=False,
    )


async def _record_commit(calls: list[str]) -> None:
    calls.append("commit")