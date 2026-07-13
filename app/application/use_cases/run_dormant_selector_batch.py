from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from app.application.ports.crm import CRMClient
from app.application.ports.dormant_candidates import DormantCandidateSelector
from app.application.ports.event_bus import EventBus
from app.application.ports.notifications import NotificationProvider
from app.application.ports.preflight_digest import PreflightDigestRepository
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    CampaignExecutionRepository,
    LeadWorkflowRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.application.services.canonical_lead_inputs import (
    contactability_facts_from_canonical_lead,
    enrollment_facts_from_canonical_lead,
    start_candidate_from_canonical_lead,
)
from app.application.use_cases.preflight_digest import (
    PreflightDigestCandidate,
    PreflightDigestPreparationResult,
    PreflightDigestPreparationStatus,
    campaign_start_context_from_digest,
    prepare_preflight_digest,
)
from app.application.use_cases.start_selected_campaign_batch import (
    start_selected_campaign_batch,
)
from app.domain.campaigns.enrollment import CampaignEnrollmentSource
from app.domain.campaigns.start_queue import (
    CampaignStartCandidate,
    CampaignStartContext,
    CampaignStartPolicy,
    CampaignStatus,
    evaluate_campaign_start_batch,
)
from app.domain.common.ids import CampaignId, LeadId, WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    WorkspaceContactPolicy,
    evaluate_contactability,
)
from app.domain.compliance.enrollment import (
    CampaignEnrollmentPolicy,
    EnrollmentSource,
    evaluate_campaign_enrollment,
)
from app.domain.leads import CanonicalLeadRecord

DEFAULT_VETO_WINDOW_HOURS = 24
DEFAULT_CANDIDATE_BUFFER_FACTOR = 2


class DormantSelectorBatchStatus(StrEnum):
    COMPLETED = "completed"
    CAMPAIGN_INACTIVE = "campaign_inactive"
    MISSING_CONTACT_POLICY = "missing_contact_policy"
    NO_CANDIDATES = "no_candidates"


@dataclass(frozen=True)
class DormantSelectorBatchResult:
    status: DormantSelectorBatchStatus
    workspace_id: WorkspaceId
    campaign_id: CampaignId
    batch_id: str
    digest_required: bool
    digest_id: str | None
    digest_status: str | None
    selected_count: int
    held_back_count: int
    started_count: int
    started_lead_ids: tuple[LeadId, ...]
    veto_window_expires_at: datetime | None
    reason: str | None = None


async def run_dormant_selector_batch(
    *,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    batch_id: str | None = None,
    campaign_execution_repository: CampaignExecutionRepository,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository,
    dormant_candidate_selector: DormantCandidateSelector,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    preflight_digest_repository: PreflightDigestRepository,
    notification_provider: NotificationProvider,
    crm_client: CRMClient,
    now: datetime,
    event_bus: EventBus | None = None,
) -> DormantSelectorBatchResult:
    batch_id = batch_id or str(uuid4())
    config = await campaign_execution_repository.get_active_for_campaign(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
    )
    if config is None or config.campaign_status != CampaignStatus.ACTIVE:
        return _result(
            status=DormantSelectorBatchStatus.CAMPAIGN_INACTIVE,
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            batch_id=batch_id,
            reason="campaign is not active or has no published version",
        )

    contact_policy = await workspace_contact_policy_repository.get_by_workspace_id(
        workspace_id=workspace_id,
    )
    if contact_policy is None:
        return _result(
            status=DormantSelectorBatchStatus.MISSING_CONTACT_POLICY,
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            batch_id=batch_id,
            reason="workspace contact policy is missing",
        )

    candidates = await dormant_candidate_selector.select_candidates(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        threshold_days=config.dormant_threshold_days,
        limit=config.daily_start_cap * DEFAULT_CANDIDATE_BUFFER_FACTOR,
        now=now,
    )
    if not candidates:
        return _result(
            status=DormantSelectorBatchStatus.NO_CANDIDATES,
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            batch_id=batch_id,
            reason="no dormant candidates found",
        )

    start_policy = CampaignStartPolicy(
        daily_start_cap=config.daily_start_cap,
        require_preflight_digest_for_first_batch=config.preflight_digest_enabled,
        veto_window_hours=DEFAULT_VETO_WINDOW_HOURS,
        agentless_dormant_threshold_days=config.dormant_threshold_days,
    )

    started_today_count = await campaign_enrollment_repository.count_started_today(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        now=now,
    )
    initial_context = _initial_context(
        campaign_status=config.campaign_status,
        started_today_count=started_today_count,
    )

    start_candidates, digest_candidates = await _evaluate_candidates(
        candidates=candidates,
        enabled_channels=config.enabled_channels,
        contact_policy=contact_policy,
        crm_client=crm_client,
        workspace_id=workspace_id,
        now=now,
    )

    digest_result = await _prepare_digest_if_needed(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        batch_id=batch_id,
        digest_candidates=digest_candidates,
        start_policy=start_policy,
        initial_context=initial_context,
        preflight_digest_repository=preflight_digest_repository,
        notification_provider=notification_provider,
        now=now,
    )

    digest = await preflight_digest_repository.get_digest(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        batch_id=batch_id,
    )
    final_context = campaign_start_context_from_digest(
        campaign_status=config.campaign_status,
        digest=digest,
        started_today_count=started_today_count,
        is_first_batch=True,
    )

    start_decision = evaluate_campaign_start_batch(
        start_candidates,
        start_policy,
        final_context,
        now,
    )

    started_lead_ids = tuple(
        decision.lead_id for decision in start_decision.selected if decision.selected
    )
    if started_lead_ids:
        start_result = await start_selected_campaign_batch(
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            campaign_version_id=config.campaign_version_id,
            lead_ids=started_lead_ids,
            source=CampaignEnrollmentSource.DORMANT_SELECTOR,
            reason_codes=(),
            actor_user_id=None,
            campaign_enrollment_repository=campaign_enrollment_repository,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            temporal_workflow_starter=temporal_workflow_starter,
            now=now,
            event_bus=event_bus,
        )
        started_count = start_result.started_count
    else:
        started_count = 0

    return _result(
        status=DormantSelectorBatchStatus.COMPLETED,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        batch_id=batch_id,
        digest_required=start_decision.digest_required,
        digest_id=digest_result.digest_id if digest_result else None,
        digest_status=digest_result.status.value if digest_result else None,
        selected_count=len(started_lead_ids),
        held_back_count=len(start_decision.held_back),
        started_count=started_count,
        started_lead_ids=started_lead_ids,
        veto_window_expires_at=start_decision.veto_window_expires_at,
    )


def _result(
    *,
    status: DormantSelectorBatchStatus,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    batch_id: str,
    digest_required: bool = False,
    digest_id: str | None = None,
    digest_status: str | None = None,
    selected_count: int = 0,
    held_back_count: int = 0,
    started_count: int = 0,
    started_lead_ids: tuple[LeadId, ...] = (),
    veto_window_expires_at: datetime | None = None,
    reason: str | None = None,
) -> DormantSelectorBatchResult:
    return DormantSelectorBatchResult(
        status=status,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        batch_id=batch_id,
        digest_required=digest_required,
        digest_id=digest_id,
        digest_status=digest_status,
        selected_count=selected_count,
        held_back_count=held_back_count,
        started_count=started_count,
        started_lead_ids=started_lead_ids,
        veto_window_expires_at=veto_window_expires_at,
        reason=reason,
    )


def _initial_context(
    *,
    campaign_status: CampaignStatus,
    started_today_count: int,
) -> CampaignStartContext:
    return CampaignStartContext(
        campaign_status=campaign_status,
        started_today_count=started_today_count,
        is_first_batch=True,
    )


async def _evaluate_candidates(
    *,
    candidates: tuple[CanonicalLeadRecord, ...],
    enabled_channels: tuple[ContactChannel, ...],
    contact_policy: WorkspaceContactPolicy,
    crm_client: CRMClient,
    workspace_id: WorkspaceId,
    now: datetime,
) -> tuple[list[CampaignStartCandidate], list[PreflightDigestCandidate]]:
    start_candidates: list[CampaignStartCandidate] = []
    digest_candidates: list[PreflightDigestCandidate] = []
    for lead in candidates:
        contactability_facts = contactability_facts_from_canonical_lead(lead)
        channel_contactability = {
            channel: evaluate_contactability(contactability_facts, contact_policy, channel)
            for channel in enabled_channels
        }
        enrollment_facts = enrollment_facts_from_canonical_lead(
            lead,
            enrollment_sources=frozenset({EnrollmentSource.DORMANT_SELECTOR}),
            enabled_channels=frozenset(enabled_channels),
            channel_contactability=channel_contactability,
        )
        enrollment_policy = CampaignEnrollmentPolicy()
        enrollment_decision = evaluate_campaign_enrollment(
            enrollment_facts,
            enrollment_policy,
            now,
        )
        if not enrollment_decision.eligible:
            continue

        start_candidate = start_candidate_from_canonical_lead(
            lead,
            enrollment_decision=enrollment_decision,
            now=now,
        )
        start_candidates.append(start_candidate)

        if start_candidate.has_assigned_agent:
            agent = await crm_client.get_assigned_agent(workspace_id, lead.crm_lead_id)
            if agent is not None and agent.email:
                digest_candidates.append(
                    PreflightDigestCandidate(
                        start_candidate=start_candidate,
                        recipient_id=agent.crm_agent_id,
                        recipient_destination=agent.email,
                        lead_display_name=lead.primary_email or lead.crm_lead_id,
                    )
                )

    return start_candidates, digest_candidates


async def _prepare_digest_if_needed(
    *,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    batch_id: str,
    digest_candidates: list[PreflightDigestCandidate],
    start_policy: CampaignStartPolicy,
    initial_context: CampaignStartContext,
    preflight_digest_repository: PreflightDigestRepository,
    notification_provider: NotificationProvider,
    now: datetime,
) -> PreflightDigestPreparationResult:

    if not digest_candidates or not start_policy.require_preflight_digest_for_first_batch:
        return PreflightDigestPreparationResult(
            status=PreflightDigestPreparationStatus.NOT_REQUIRED,
        )

    return await prepare_preflight_digest(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        batch_id=batch_id,
        candidates=tuple(digest_candidates),
        start_policy=start_policy,
        start_context=initial_context,
        repository=preflight_digest_repository,
        notification_provider=notification_provider,
        now=now,
    )
