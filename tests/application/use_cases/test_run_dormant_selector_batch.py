from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest

from app.application.ports.crm import CanonicalLead, CRMActivity, CRMAgent, CRMClient
from app.application.ports.dormant_candidates import DormantCandidateSelector
from app.application.use_cases.preflight_digest import (
    PreflightDigestPreparationStatus,
)
from app.application.use_cases.run_dormant_selector_batch import (
    DormantSelectorBatchResult,
    DormantSelectorBatchStatus,
    run_dormant_selector_batch,
)
from app.domain.campaigns.execution import CampaignExecutionConfig, CampaignVersionStatus
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import CampaignId, WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SmsComplianceState,
    WorkspaceContactPolicy,
)
from app.domain.leads.canonical import (
    ActivityReliability,
    CanonicalLeadRecord,
    CRMProvider,
    LeadType,
)
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCampaignExecutionRepository,
    FakeLeadWorkflowRepository,
    FakeWorkflowTransitionRepository,
    FakeWorkspaceContactPolicyRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeTemporalWorkflowStarter,
)
from tests.application.use_cases.test_preflight_digest import (
    FakeNotificationProvider,
    FakePreflightDigestRepository,
)

NOW = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
CAMPAIGN_ID = UUID("22222222-2222-2222-2222-222222222222")
CAMPAIGN_VERSION_ID = UUID("33333333-3333-3333-3333-333333333333")


class FakeDormantCandidateSelector(DormantCandidateSelector):
    def __init__(self, leads: tuple[CanonicalLeadRecord, ...]) -> None:
        self.leads = leads

    async def select_candidates(
        self,
        *,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
        threshold_days: int,
        limit: int,
        now: datetime,
    ) -> tuple[CanonicalLeadRecord, ...]:
        return self.leads[:limit]


class FakeCRMClient(CRMClient):
    def __init__(self, agent: CRMAgent | None = None) -> None:
        self.agent = agent

    async def get_assigned_agent(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
    ) -> CRMAgent | None:
        return self.agent

    async def validate_connection(self, workspace_id: UUID) -> bool:
        return True

    async def get_lead(self, workspace_id: UUID, crm_lead_id: str) -> CanonicalLead | None:
        return None

    async def search_leads(
        self,
        workspace_id: UUID,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[CanonicalLead]:
        return []

    async def get_recent_activity(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        limit: int = 50,
    ) -> list[CRMActivity]:
        return []

    async def add_note(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        content: str,
        subject: str | None = None,
    ) -> None:
        return None

    async def add_tag(self, workspace_id: UUID, crm_lead_id: str, tag: str) -> None:
        return None

    async def remove_tag(self, workspace_id: UUID, crm_lead_id: str, tag: str) -> None:
        return None

    async def update_custom_fields(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        fields: dict[str, str],
    ) -> None:
        return None

    async def subscribe_to_events(self, workspace_id: UUID, webhook_url: str) -> None:
        return None

    async def fetch_resource_by_uri(
        self, workspace_id: UUID, uri: str
    ) -> dict[str, object] | None:
        return None


def _lead(*, lead_id: UUID | None = None, has_assigned_agent: bool = True) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=lead_id or uuid4(),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id=f"crm-{lead_id or uuid4()}",
        facts_derived_at=NOW,
        source_payload_version="1",
        source_updated_at=NOW,
        assigned_agent_crm_id="agent-1" if has_assigned_agent else None,
        assigned_agent_name_present=has_assigned_agent,
        has_accountable_owner=has_assigned_agent,
        lead_type=LeadType.BUYER,
        primary_email="lead@example.com",
        has_email=True,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        sms_permission_status=ContactPermissionStatus.CONFIRMED,
        do_not_contact=False,
        last_meaningful_communication_at=NOW - timedelta(days=90),
        activity_reliability=ActivityReliability.RELIABLE,
    )


def _config(*, preflight_digest_enabled: bool = True) -> CampaignExecutionConfig:
    return CampaignExecutionConfig(
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        workspace_id=WORKSPACE_ID,
        campaign_name="Test Campaign",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(ContactChannel.EMAIL,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="UTC",
        sms_compliance_required=False,
        preflight_digest_enabled=preflight_digest_enabled,
        crm_enrollment_tag=None,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(),
        created_at=NOW,
        published_at=NOW,
    )


def _policy() -> WorkspaceContactPolicy:
    return WorkspaceContactPolicy(
        workspace_id=WORKSPACE_ID,
        sms_compliance_state=SmsComplianceState.APPROVED,
    )


class _Missing:
    pass


_MISSING = _Missing()


async def _run(
    *,
    leads: tuple[CanonicalLeadRecord, ...] = (),
    config: CampaignExecutionConfig | None | _Missing = _MISSING,
    policy: WorkspaceContactPolicy | None | _Missing = _MISSING,
    preflight_digest_enabled: bool = True,
    crm_agent: CRMAgent | None = None,
) -> DormantSelectorBatchResult:

    resolved_config: CampaignExecutionConfig | None = (
        _config(preflight_digest_enabled=preflight_digest_enabled)
        if isinstance(config, _Missing)
        else config
    )
    resolved_policy: WorkspaceContactPolicy | None = (
        _policy() if isinstance(policy, _Missing) else policy
    )
    return await run_dormant_selector_batch(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            config=resolved_config,
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            policy=resolved_policy,
        ),
        dormant_candidate_selector=FakeDormantCandidateSelector(leads),
        campaign_enrollment_repository=FakeCampaignEnrollmentRepository(),
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=FakeTemporalWorkflowStarter(),
        preflight_digest_repository=FakePreflightDigestRepository(),
        notification_provider=FakeNotificationProvider(),
        crm_client=FakeCRMClient(agent=crm_agent),
        now=NOW,
    )


@pytest.mark.asyncio
async def test_returns_campaign_inactive_when_config_missing() -> None:
    result = await _run(leads=(_lead(),), config=None)
    assert result.status == DormantSelectorBatchStatus.CAMPAIGN_INACTIVE


@pytest.mark.asyncio
async def test_returns_missing_policy_when_policy_missing() -> None:
    result = await _run(leads=(_lead(),), policy=None)
    assert result.status == DormantSelectorBatchStatus.MISSING_CONTACT_POLICY


@pytest.mark.asyncio
async def test_returns_no_candidates_when_selector_empty() -> None:
    result = await _run(leads=())
    assert result.status == DormantSelectorBatchStatus.NO_CANDIDATES


@pytest.mark.asyncio
async def test_starts_unassigned_lead_without_preflight_digest() -> None:
    lead = _lead(has_assigned_agent=False)
    result = await _run(leads=(lead,), preflight_digest_enabled=True)

    assert result.status == DormantSelectorBatchStatus.COMPLETED
    assert result.selected_count == 1
    assert result.started_count == 1
    assert result.started_lead_ids == (lead.lead_id,)
    assert result.digest_status == PreflightDigestPreparationStatus.NOT_REQUIRED.value


@pytest.mark.asyncio
async def test_issues_preflight_digest_and_holds_back_assigned_lead() -> None:
    lead = _lead(has_assigned_agent=True)
    agent = CRMAgent(crm_agent_id="agent-1", name="Agent", email="agent@example.com")
    result = await _run(leads=(lead,), crm_agent=agent)

    assert result.status == DormantSelectorBatchStatus.COMPLETED
    assert result.selected_count == 0
    assert result.held_back_count == 1
    assert result.started_count == 0
    assert result.digest_status == PreflightDigestPreparationStatus.ISSUED.value
    assert result.veto_window_expires_at is not None
