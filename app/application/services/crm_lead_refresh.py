from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import cast

import structlog

from app.application.ports.crm import CRMClient
from app.application.ports.crm_sync import CanonicalLeadRefreshSource
from app.application.ports.event_bus import EventBus
from app.application.ports.llm import LLMClient
from app.application.ports.notifications import NotificationProvider
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    CampaignExecutionRepository,
    CrmConversationEventRepository,
    HandoffCompletionRepository,
    HandoffRepository,
    LeadClassificationArtifactRepository,
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadRoutingReviewRepository,
    LeadWorkflowRepository,
    PausedSearchTrackAssignmentRepository,
    PausedSearchTrackRepository,
    UserRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.application.use_cases.process_crm_tag_campaign_enrollment import (
    CRMTagCampaignEnrollmentResult,
    process_crm_tag_campaign_enrollment,
)
from app.domain.common.ids import WorkspaceId
from app.domain.leads import CanonicalLeadRecord, CRMProvider, preserve_app_owned_lead_state

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CrmTagEnrollmentDependencies:
    campaign_execution_repository: CampaignExecutionRepository
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository
    campaign_enrollment_repository: CampaignEnrollmentRepository
    lead_workflow_repository: LeadWorkflowRepository
    workflow_transition_repository: WorkflowTransitionRepository
    temporal_workflow_starter: TemporalWorkflowStarter
    lead_repository: LeadRepository
    paused_search_track_repository: PausedSearchTrackRepository
    artifact_repository: LeadClassificationArtifactRepository
    crm_conversation_event_repository: CrmConversationEventRepository
    workspace_llm_config_repository: WorkspaceLLMConfigRepository
    llm_client: LLMClient
    event_bus: EventBus | None = None
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None = None
    handoff_repository: HandoffRepository | None = None
    handoff_completion_repository: HandoffCompletionRepository | None = None
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None = None
    crm_client: CRMClient | None = None
    notification_provider: NotificationProvider | None = None
    user_repository: UserRepository | None = None
    routing_review_repository: LeadRoutingReviewRepository | None = None
    commit: Callable[[], Awaitable[None]] | None = None
    rollback: Callable[[], Awaitable[None]] | None = None
    default_openrouter_model: str = "openai/gpt-4o-mini"


async def run_crm_tag_enrollment(
    *,
    workspace_id: WorkspaceId,
    lead: CanonicalLeadRecord,
    observed_at: datetime,
    now: datetime,
    deps: CrmTagEnrollmentDependencies,
) -> CRMTagCampaignEnrollmentResult:
    return await process_crm_tag_campaign_enrollment(
        workspace_id=workspace_id,
        lead=lead,
        observed_at=observed_at,
        now=now,
        campaign_execution_repository=deps.campaign_execution_repository,
        workspace_contact_policy_repository=deps.workspace_contact_policy_repository,
        campaign_enrollment_repository=deps.campaign_enrollment_repository,
        lead_workflow_repository=deps.lead_workflow_repository,
        workflow_transition_repository=deps.workflow_transition_repository,
        temporal_workflow_starter=deps.temporal_workflow_starter,
        lead_repository=deps.lead_repository,
        paused_search_history_repository=cast(
            LeadPausedSearchHistoryRepository,
            deps.lead_repository,
        ),
        paused_search_track_repository=deps.paused_search_track_repository,
        paused_search_track_assignment_repository=(
            deps.paused_search_track_assignment_repository
        ),
        artifact_repository=deps.artifact_repository,
        crm_conversation_event_repository=deps.crm_conversation_event_repository,
        workspace_llm_config_repository=deps.workspace_llm_config_repository,
        llm_client=deps.llm_client,
        event_bus=deps.event_bus,
        workspace_operational_control_repository=(
            deps.workspace_operational_control_repository
        ),
        handoff_repository=deps.handoff_repository,
        handoff_completion_repository=deps.handoff_completion_repository,
        workspace_handoff_config_repository=deps.workspace_handoff_config_repository,
        crm_client=deps.crm_client,
        notification_provider=deps.notification_provider,
        user_repository=deps.user_repository,
        commit=deps.commit,
        rollback=deps.rollback,
        default_openrouter_model=deps.default_openrouter_model,
        routing_review_repository=deps.routing_review_repository,
    )


def crm_tag_enrollment_observed_at(lead: CanonicalLeadRecord) -> datetime:
    return lead.source_updated_at or lead.crm_updated_at or lead.facts_derived_at


class CrmLeadRefreshStatus(StrEnum):
    REFRESHED = "refreshed"
    LEAD_NOT_FOUND = "lead_not_found"
    FAILED = "failed"


@dataclass(frozen=True)
class CrmLeadRefreshResult:
    status: CrmLeadRefreshStatus
    lead: CanonicalLeadRecord | None = None
    enrollment: CRMTagCampaignEnrollmentResult | None = None
    enrollment_error: str | None = None
    failure_reason: str | None = None


async def refresh_lead_from_crm(
    *,
    workspace_id: WorkspaceId,
    crm_provider: CRMProvider,
    crm_lead_id: str,
    lead_refresh_source: CanonicalLeadRefreshSource,
    lead_repository: LeadRepository,
    now: datetime,
    enrollment_deps: CrmTagEnrollmentDependencies | None = None,
) -> CrmLeadRefreshResult:
    """Fetch the latest CRM snapshot for one lead, upsert it locally, and
    re-evaluate tag-based campaign enrollment.

    App-owned paused-search state on the existing record is preserved, matching
    the webhook and sync paths. Enrollment runs only when its dependencies are
    provided; an enrollment failure never discards the refreshed lead.
    """
    existing = await lead_repository.get_by_crm_id(workspace_id, crm_provider, crm_lead_id)
    try:
        snapshot = await lead_refresh_source.get_lead_snapshot(
            workspace_id=workspace_id,
            crm_lead_id=crm_lead_id,
            mapped_custom_field_keys=(
                tuple(existing.mapped_custom_fields.keys()) if existing is not None else ()
            ),
        )
    except Exception as exc:
        return CrmLeadRefreshResult(
            status=CrmLeadRefreshStatus.FAILED,
            lead=existing,
            failure_reason=str(exc) or exc.__class__.__name__,
        )
    if snapshot is None:
        return CrmLeadRefreshResult(
            status=CrmLeadRefreshStatus.LEAD_NOT_FOUND,
            lead=existing,
        )
    saved = await lead_repository.upsert(preserve_app_owned_lead_state(snapshot, existing))
    if enrollment_deps is None:
        return CrmLeadRefreshResult(status=CrmLeadRefreshStatus.REFRESHED, lead=saved)
    try:
        enrollment = await run_crm_tag_enrollment(
            workspace_id=workspace_id,
            lead=saved,
            observed_at=crm_tag_enrollment_observed_at(saved),
            now=now,
            deps=enrollment_deps,
        )
    except Exception as exc:
        logger.warning(
            "crm_lead_refresh_enrollment_failed",
            workspace_id=str(workspace_id),
            crm_lead_id=crm_lead_id,
            error=str(exc) or exc.__class__.__name__,
        )
        return CrmLeadRefreshResult(
            status=CrmLeadRefreshStatus.REFRESHED,
            lead=saved,
            enrollment_error=str(exc) or exc.__class__.__name__,
        )
    return CrmLeadRefreshResult(
        status=CrmLeadRefreshStatus.REFRESHED,
        lead=saved,
        enrollment=enrollment,
    )
