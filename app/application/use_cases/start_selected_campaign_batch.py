from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    LeadWorkflowRepository,
    WorkflowTransitionRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.application.services.campaign_enrollment_starter import start_single_campaign_enrollment
from app.application.use_cases.campaign_enrollment_types import LeadStartResult, LeadStartStatus
from app.domain.campaigns.enrollment import CampaignEnrollmentSource
from app.domain.common.ids import CampaignId, CampaignVersionId, LeadId, UserId, WorkspaceId


@dataclass(frozen=True)
class StartSelectedCampaignBatchResult:
    workspace_id: WorkspaceId
    campaign_id: CampaignId
    started_count: int
    already_enrolled_count: int
    failed_count: int
    lead_results: tuple[LeadStartResult, ...]


async def start_selected_campaign_batch(
    *,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    campaign_version_id: CampaignVersionId,
    lead_ids: Sequence[LeadId],
    source: CampaignEnrollmentSource,
    reason_codes: Sequence[str],
    actor_user_id: UserId | None,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    now: datetime,
    metadata: Mapping[str, object] | None = None,
    event_bus: EventBus | None = None,
) -> StartSelectedCampaignBatchResult:
    lead_results: list[LeadStartResult] = []
    started_count = 0
    already_enrolled_count = 0
    failed_count = 0

    for lead_id in lead_ids:
        existing = await campaign_enrollment_repository.get_by_lead_and_campaign(
            workspace_id=workspace_id,
            lead_id=lead_id,
            campaign_id=campaign_id,
        )
        if existing is not None:
            lead_results.append(
                LeadStartResult(
                    lead_id=lead_id,
                    status=LeadStartStatus.ALREADY_ENROLLED,
                    campaign_enrollment_id=existing.campaign_enrollment_id,
                ),
            )
            already_enrolled_count += 1
            continue

        result = await start_single_campaign_enrollment(
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            campaign_version_id=campaign_version_id,
            lead_id=lead_id,
            source=source,
            reason_codes=reason_codes,
            actor_user_id=actor_user_id,
            campaign_enrollment_repository=campaign_enrollment_repository,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            temporal_workflow_starter=temporal_workflow_starter,
            now=now,
            metadata=metadata,
            event_bus=event_bus,
        )
        lead_results.append(result)
        if result.status == LeadStartStatus.STARTED:
            started_count += 1
        else:
            failed_count += 1

    return StartSelectedCampaignBatchResult(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        started_count=started_count,
        already_enrolled_count=already_enrolled_count,
        failed_count=failed_count,
        lead_results=tuple(lead_results),
    )
