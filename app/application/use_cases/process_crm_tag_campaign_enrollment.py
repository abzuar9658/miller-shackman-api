from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    CampaignExecutionRepository,
    LeadWorkflowRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.application.services.canonical_lead_inputs import (
    contactability_facts_from_canonical_lead,
    enrollment_facts_from_canonical_lead,
    start_candidate_from_canonical_lead,
)
from app.application.use_cases.campaign_enrollment_types import LeadStartStatus
from app.application.use_cases.start_selected_campaign_batch import start_selected_campaign_batch
from app.domain.campaigns.enrollment import CampaignEnrollmentSource
from app.domain.campaigns.execution import CampaignExecutionConfig
from app.domain.campaigns.start_queue import (
    CampaignStartContext,
    CampaignStartPolicy,
    evaluate_campaign_start_batch,
)
from app.domain.common.ids import CampaignId, CampaignVersionId, LeadId, WorkspaceId
from app.domain.compliance.contactability import evaluate_contactability
from app.domain.compliance.enrollment import (
    CampaignEnrollmentPolicy,
    EnrollmentSource,
    evaluate_campaign_enrollment,
)
from app.domain.leads import CanonicalLeadRecord

DEFAULT_VETO_WINDOW_HOURS = 24


class CRMTagCampaignEnrollmentStatus(StrEnum):
    NO_MATCHING_CAMPAIGN = "no_matching_campaign"
    MISSING_CONTACT_POLICY = "missing_contact_policy"
    NOT_ELIGIBLE = "not_eligible"
    HELD = "held"
    STARTED = "started"
    ALREADY_ENROLLED = "already_enrolled"
    FAILED = "failed"


@dataclass(frozen=True)
class CRMTagCampaignEnrollmentResult:
    status: CRMTagCampaignEnrollmentStatus
    workspace_id: WorkspaceId
    lead_id: LeadId
    campaign_id: CampaignId | None = None
    campaign_version_id: CampaignVersionId | None = None
    matched_tag: str | None = None
    reason_codes: tuple[str, ...] = ()
    campaign_enrollment_id: UUID | None = None
    workflow_id: UUID | None = None
    temporal_workflow_id: str | None = None
    error: str | None = None


async def process_crm_tag_campaign_enrollment(
    *,
    workspace_id: WorkspaceId,
    lead: CanonicalLeadRecord,
    observed_at: datetime,
    now: datetime,
    campaign_execution_repository: CampaignExecutionRepository,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    event_bus: EventBus | None = None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None,
    commit: Callable[[], Awaitable[None]] | None = None,
) -> CRMTagCampaignEnrollmentResult:
    configs = await campaign_execution_repository.list_active_for_workspace(workspace_id)
    matched_config = _matching_campaign_config(configs, lead.tags)
    if matched_config is None:
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.NO_MATCHING_CAMPAIGN,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
        )

    contact_policy = await workspace_contact_policy_repository.get_by_workspace_id(workspace_id)
    if contact_policy is None:
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.MISSING_CONTACT_POLICY,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
        )

    enabled_channels = frozenset(matched_config.enabled_channels)
    contactability_facts = contactability_facts_from_canonical_lead(lead)
    channel_contactability = {
        channel: evaluate_contactability(contactability_facts, contact_policy, channel)
        for channel in enabled_channels
    }
    enrollment_facts = enrollment_facts_from_canonical_lead(
        lead,
        enrollment_sources=frozenset({EnrollmentSource.CRM_TAG}),
        enabled_channels=enabled_channels,
        channel_contactability=channel_contactability,
        enrollment_tag_observed_at=observed_at,
    )
    enrollment_decision = evaluate_campaign_enrollment(
        enrollment_facts,
        CampaignEnrollmentPolicy(),
        now,
    )
    if not enrollment_decision.eligible:
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.NOT_ELIGIBLE,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
            reason_codes=tuple(reason.value for reason in enrollment_decision.reasons),
        )

    start_candidate = start_candidate_from_canonical_lead(
        lead,
        enrollment_decision=enrollment_decision,
        now=now,
    )
    start_policy = CampaignStartPolicy(
        daily_start_cap=matched_config.daily_start_cap,
        require_preflight_digest_for_first_batch=matched_config.preflight_digest_enabled,
        veto_window_hours=DEFAULT_VETO_WINDOW_HOURS,
        agentless_dormant_threshold_days=matched_config.dormant_threshold_days,
    )
    started_today_count = await campaign_enrollment_repository.count_started_today(
        workspace_id=workspace_id,
        campaign_id=matched_config.campaign_id,
        started_since=now,
    )
    start_decision = evaluate_campaign_start_batch(
        [start_candidate],
        start_policy,
        CampaignStartContext(
            campaign_status=matched_config.campaign_status,
            started_today_count=started_today_count,
            is_first_batch=True,
        ),
        now,
    )
    if not start_decision.selected:
        held = start_decision.held_back[0] if start_decision.held_back else None
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.HELD,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
            reason_codes=tuple(reason.value for reason in held.reasons) if held else (),
        )

    start_result = await start_selected_campaign_batch(
        workspace_id=workspace_id,
        campaign_id=matched_config.campaign_id,
        campaign_version_id=matched_config.campaign_version_id,
        lead_ids=[lead.lead_id],
        source=CampaignEnrollmentSource.CRM_TAG,
        reason_codes=(),
        actor_user_id=None,
        campaign_enrollment_repository=campaign_enrollment_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        event_bus=event_bus,
        workspace_operational_control_repository=workspace_operational_control_repository,
        commit=commit,
        now=now,
    )
    lead_result = start_result.lead_results[0] if start_result.lead_results else None
    if lead_result is not None and lead_result.status == LeadStartStatus.STARTED:
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.STARTED,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
            campaign_enrollment_id=lead_result.campaign_enrollment_id,
            workflow_id=lead_result.workflow_id,
            temporal_workflow_id=lead_result.temporal_workflow_id,
        )
    if lead_result is not None and lead_result.status == LeadStartStatus.ALREADY_ENROLLED:
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.ALREADY_ENROLLED,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
            campaign_enrollment_id=lead_result.campaign_enrollment_id,
        )
    return CRMTagCampaignEnrollmentResult(
        status=CRMTagCampaignEnrollmentStatus.FAILED,
        workspace_id=workspace_id,
        lead_id=lead.lead_id,
        campaign_id=matched_config.campaign_id,
        campaign_version_id=matched_config.campaign_version_id,
        matched_tag=matched_config.crm_enrollment_tag,
        error=lead_result.error if lead_result is not None else "failed to start enrollment",
    )


def _matching_campaign_config(
    configs: tuple[CampaignExecutionConfig, ...],
    lead_tags: tuple[str, ...],
) -> CampaignExecutionConfig | None:
    normalized_tags = {_normalized_tag(tag) for tag in lead_tags}
    normalized_tags.discard(None)
    for config in configs:
        configured_tag = _normalized_tag(config.crm_enrollment_tag)
        if configured_tag is None:
            continue
        if configured_tag in normalized_tags:
            return config
    return None


def _normalized_tag(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None