from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import cast
from uuid import UUID

from app.application.ports.event_bus import EventBus
from app.application.ports.lead_read import LeadReadLeadRepository
from app.application.ports.repositories import (
    CampaignAdminRepository,
    CampaignEnrollmentRepository,
    LeadWorkflowRepository,
    WorkflowTransitionRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.application.services.campaign_enrollment_starter import start_single_campaign_enrollment
from app.application.services.lead_assignment import is_actor_assigned_to_lead
from app.application.use_cases.campaign_enrollment_types import LeadStartStatus
from app.domain.campaigns.admin import CampaignAdminCampaign, CampaignAdminVersion
from app.domain.campaigns.enrollment import CampaignEnrollmentSource
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import CampaignId, CampaignVersionId, LeadId, WorkspaceId
from app.domain.identity import (
    AuthenticatedActor,
    PermissionCapability,
    PermissionContext,
    WorkspaceMembershipRole,
    evaluate_permission,
)
from app.domain.leads import CanonicalLeadRecord


class LeadManualEnrollmentOptionsStatus(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


class LeadManualEnrollmentActionStatus(StrEnum):
    STARTED = "started"
    ALREADY_ENROLLED = "already_enrolled"
    FAILED = "failed"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


class LeadManualEnrollmentReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    LEAD_NOT_FOUND = "lead_not_found"
    CAMPAIGN_NOT_FOUND = "campaign_not_found"
    NO_CAMPAIGNS_CONFIGURED = "no_campaigns_configured"
    NO_ACTIVE_CAMPAIGNS = "no_active_campaigns"
    NO_ACTIVE_PUBLISHED_CAMPAIGNS = "no_active_published_campaigns"
    LEAD_ALREADY_ENROLLED_IN_AVAILABLE_CAMPAIGNS = (
        "lead_already_enrolled_in_available_campaigns"
    )
    CAMPAIGNS_DISALLOW_AGENT_MANUAL_ENROLLMENT = (
        "campaigns_disallow_agent_manual_enrollment"
    )
    NO_STARTABLE_CAMPAIGNS = "no_startable_campaigns"


@dataclass(frozen=True)
class LeadManualEnrollmentOption:
    campaign_id: CampaignId
    campaign_version_id: CampaignVersionId
    campaign_name: str
    enabled_channels: tuple[str, ...]
    preflight_digest_enabled: bool


@dataclass(frozen=True)
class LeadManualEnrollmentOptionsResult:
    status: LeadManualEnrollmentOptionsStatus
    campaigns: tuple[LeadManualEnrollmentOption, ...] = ()
    reasons: tuple[LeadManualEnrollmentReasonCode, ...] = ()
    total_campaign_count: int = 0
    active_campaign_count: int = 0
    active_published_campaign_count: int = 0
    already_enrolled_campaign_count: int = 0


@dataclass(frozen=True)
class StartLeadManualEnrollmentResult:
    status: LeadManualEnrollmentActionStatus
    campaign_id: CampaignId | None = None
    campaign_version_id: CampaignVersionId | None = None
    campaign_enrollment_id: UUID | None = None
    workflow_id: UUID | None = None
    temporal_workflow_id: str | None = None
    reasons: tuple[LeadManualEnrollmentReasonCode, ...] = ()
    error: str | None = None


async def list_lead_manual_enrollment_options(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    lead_repository: LeadReadLeadRepository,
    campaign_admin_repository: CampaignAdminRepository,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
) -> LeadManualEnrollmentOptionsResult:
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return LeadManualEnrollmentOptionsResult(
            status=LeadManualEnrollmentOptionsStatus.NOT_FOUND,
            reasons=(LeadManualEnrollmentReasonCode.LEAD_NOT_FOUND,),
        )
    if not _permission_allowed(actor, lead, campaign_allows_assigned_agent_enrollment=True):
        return LeadManualEnrollmentOptionsResult(
            status=LeadManualEnrollmentOptionsStatus.REJECTED,
            reasons=(LeadManualEnrollmentReasonCode.PERMISSION_DENIED,),
        )

    options: list[LeadManualEnrollmentOption] = []
    total_campaign_count = 0
    active_campaign_count = 0
    active_published_campaign_count = 0
    already_enrolled_campaign_count = 0
    permission_blocked_campaign_count = 0

    for campaign in await campaign_admin_repository.list_campaigns(workspace_id):
        total_campaign_count += 1
        if campaign.status == CampaignStatus.ACTIVE:
            active_campaign_count += 1

        version = await _active_published_version(campaign_admin_repository, workspace_id, campaign)
        if version is None:
            continue
        active_published_campaign_count += 1

        if not _permission_allowed(
            actor,
            lead,
            campaign_allows_assigned_agent_enrollment=version.allow_assigned_agent_manual_enrollment,
        ):
            permission_blocked_campaign_count += 1
            continue

        existing = await campaign_enrollment_repository.get_by_lead_and_campaign(
            workspace_id=workspace_id,
            lead_id=lead_id,
            campaign_id=campaign.campaign_id,
        )
        if existing is not None:
            already_enrolled_campaign_count += 1
            continue
        options.append(
            LeadManualEnrollmentOption(
                campaign_id=campaign.campaign_id,
                campaign_version_id=version.campaign_version_id,
                campaign_name=campaign.name,
                enabled_channels=tuple(channel.value for channel in version.enabled_channels),
                preflight_digest_enabled=version.preflight_digest_enabled,
            )
        )
    reasons: tuple[LeadManualEnrollmentReasonCode, ...] = ()
    if len(options) == 0:
        if total_campaign_count == 0:
            reasons = (LeadManualEnrollmentReasonCode.NO_CAMPAIGNS_CONFIGURED,)
        elif active_campaign_count == 0:
            reasons = (LeadManualEnrollmentReasonCode.NO_ACTIVE_CAMPAIGNS,)
        elif active_published_campaign_count == 0:
            reasons = (LeadManualEnrollmentReasonCode.NO_ACTIVE_PUBLISHED_CAMPAIGNS,)
        elif permission_blocked_campaign_count == active_published_campaign_count:
            reasons = (
                LeadManualEnrollmentReasonCode.CAMPAIGNS_DISALLOW_AGENT_MANUAL_ENROLLMENT,
            )
        elif already_enrolled_campaign_count > 0 and (
            already_enrolled_campaign_count + permission_blocked_campaign_count
            >= active_published_campaign_count
        ):
            reasons = (
                LeadManualEnrollmentReasonCode.LEAD_ALREADY_ENROLLED_IN_AVAILABLE_CAMPAIGNS,
            )
        else:
            reasons = (LeadManualEnrollmentReasonCode.NO_STARTABLE_CAMPAIGNS,)

    return LeadManualEnrollmentOptionsResult(
        status=LeadManualEnrollmentOptionsStatus.OK,
        campaigns=tuple(options),
        reasons=reasons,
        total_campaign_count=total_campaign_count,
        active_campaign_count=active_campaign_count,
        active_published_campaign_count=active_published_campaign_count,
        already_enrolled_campaign_count=already_enrolled_campaign_count,
    )


async def start_lead_manual_enrollment(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    campaign_id: CampaignId,
    lead_repository: LeadReadLeadRepository,
    campaign_admin_repository: CampaignAdminRepository,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    event_bus: EventBus | None,
    now: datetime,
) -> StartLeadManualEnrollmentResult:
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.NOT_FOUND,
            reasons=(LeadManualEnrollmentReasonCode.LEAD_NOT_FOUND,),
        )
    campaign = await campaign_admin_repository.get_campaign(workspace_id, campaign_id)
    version = await _active_published_version(campaign_admin_repository, workspace_id, campaign)
    if campaign is None or version is None:
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.NOT_FOUND,
            reasons=(LeadManualEnrollmentReasonCode.CAMPAIGN_NOT_FOUND,),
        )
    if not _permission_allowed(
        actor,
        lead,
        campaign_allows_assigned_agent_enrollment=version.allow_assigned_agent_manual_enrollment,
    ):
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.REJECTED,
            reasons=(LeadManualEnrollmentReasonCode.PERMISSION_DENIED,),
        )

    existing = await campaign_enrollment_repository.get_by_lead_and_campaign(
        workspace_id=workspace_id,
        lead_id=lead_id,
        campaign_id=campaign_id,
    )
    if existing is not None:
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.ALREADY_ENROLLED,
            campaign_id=campaign_id,
            campaign_version_id=version.campaign_version_id,
            campaign_enrollment_id=existing.campaign_enrollment_id,
        )

    result = await start_single_campaign_enrollment(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        campaign_version_id=version.campaign_version_id,
        lead_id=lead_id,
        source=_enrollment_source(actor),
        reason_codes=(),
        actor_user_id=actor.user_id,
        campaign_enrollment_repository=campaign_enrollment_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        now=now,
        event_bus=event_bus,
    )
    return StartLeadManualEnrollmentResult(
        status=(
            LeadManualEnrollmentActionStatus.STARTED
            if result.status == LeadStartStatus.STARTED
            else LeadManualEnrollmentActionStatus.FAILED
        ),
        campaign_id=campaign_id,
        campaign_version_id=version.campaign_version_id,
        campaign_enrollment_id=result.campaign_enrollment_id,
        workflow_id=result.workflow_id,
        temporal_workflow_id=result.temporal_workflow_id,
        error=result.error,
    )


async def _active_published_version(
    campaign_admin_repository: CampaignAdminRepository,
    workspace_id: WorkspaceId,
    campaign: CampaignAdminCampaign | None,
) -> CampaignAdminVersion | None:
    if (
        campaign is None
        or campaign.status != CampaignStatus.ACTIVE
        or campaign.active_version_id is None
    ):
        return None
    version = cast(
        CampaignAdminVersion | None,
        await campaign_admin_repository.get_version(workspace_id, campaign.active_version_id),
    )
    if version is None or version.status != CampaignVersionStatus.PUBLISHED:
        return None
    return version


def _permission_allowed(
    actor: AuthenticatedActor,
    lead: CanonicalLeadRecord,
    *,
    campaign_allows_assigned_agent_enrollment: bool,
) -> bool:
    context = PermissionContext(
        acts_on_assigned_lead=is_actor_assigned_to_lead(actor, lead),
        campaign_allows_assigned_agent_enrollment=campaign_allows_assigned_agent_enrollment,
    )
    if evaluate_permission(actor, PermissionCapability.ENROLL_ANY_ELIGIBLE_LEAD, context).allowed:
        return True
    return evaluate_permission(
        actor,
        PermissionCapability.ENROLL_OWN_LEAD_WHEN_CAMPAIGN_ALLOWS,
        context,
    ).allowed


def _enrollment_source(actor: AuthenticatedActor) -> CampaignEnrollmentSource:
    return (
        CampaignEnrollmentSource.MANUAL_AGENT
        if actor.active_role == WorkspaceMembershipRole.ASSIGNED_AGENT
        else CampaignEnrollmentSource.MANUAL_ADMIN
    )