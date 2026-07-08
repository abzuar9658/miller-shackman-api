from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID, uuid4

from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    LeadWorkflowRepository,
    WorkflowTransitionRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.application.use_cases.campaign_enrollment_types import LeadStartResult, LeadStartStatus
from app.domain.campaigns.enrollment import (
    CampaignEnrollment,
    CampaignEnrollmentSource,
    CampaignEnrollmentStatus,
    build_enrollment_reason_codes,
)
from app.domain.common.ids import CampaignId, CampaignVersionId, LeadId, UserId, WorkspaceId
from app.domain.workflows import (
    LeadWorkflow,
    WorkflowState,
    WorkflowTransition,
    WorkflowTransitionReasonCode,
)


async def start_single_campaign_enrollment(
    *,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    campaign_version_id: CampaignVersionId,
    lead_id: LeadId,
    source: CampaignEnrollmentSource,
    reason_codes: Sequence[str],
    actor_user_id: UserId | None,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    now: datetime,
    campaign_enrollment_id: UUID | None = None,
    workflow_id: UUID | None = None,
    transition_id: UUID | None = None,
    temporal_workflow_id: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> LeadStartResult:
    campaign_enrollment_id = campaign_enrollment_id or uuid4()
    workflow_id = workflow_id or uuid4()
    transition_id = transition_id or uuid4()
    temporal_workflow_id = temporal_workflow_id or _default_temporal_workflow_id(
        lead_id,
        campaign_enrollment_id,
    )

    enrollment = CampaignEnrollment(
        campaign_enrollment_id=campaign_enrollment_id,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        campaign_version_id=campaign_version_id,
        lead_id=lead_id,
        source=source,
        status=CampaignEnrollmentStatus.QUEUED,
        eligible_at=now,
        enrolled_at=now,
        started_at=None,
        ended_at=None,
        created_by_user_id=actor_user_id,
        reason_codes=build_enrollment_reason_codes(source=source, additional_reasons=reason_codes),
        created_at=now,
        updated_at=now,
    )

    workflow = LeadWorkflow(
        workflow_id=workflow_id,
        temporal_workflow_id=temporal_workflow_id,
        workspace_id=workspace_id,
        campaign_enrollment_id=campaign_enrollment_id,
        campaign_id=campaign_id,
        lead_id=lead_id,
        state=WorkflowState.QUEUED,
        current_step_id=None,
        next_action_at=None,
        last_transition_at=now,
        pause_reason=None,
        resume_reason=None,
        state_version=1,
        created_at=now,
        updated_at=now,
    )

    transition = WorkflowTransition(
        transition_id=transition_id,
        workspace_id=workspace_id,
        workflow_id=workflow_id,
        lead_id=lead_id,
        campaign_id=campaign_id,
        from_state=None,
        to_state=WorkflowState.QUEUED,
        reason_code=WorkflowTransitionReasonCode.CAMPAIGN_ENROLLMENT_STARTED,
        created_at=now,
        actor_user_id=actor_user_id,
        external_event_id=None,
        metadata=metadata or {},
    )

    try:
        await campaign_enrollment_repository.save(enrollment)
        await lead_workflow_repository.save(workflow)
        await workflow_transition_repository.append(transition)
        await temporal_workflow_starter.start_lead_nurture_workflow(
            workspace_id=workspace_id,
            lead_id=lead_id,
            temporal_workflow_id=temporal_workflow_id,
        )
    except Exception as error:
        return LeadStartResult(
            lead_id=lead_id,
            status=LeadStartStatus.FAILED,
            campaign_enrollment_id=campaign_enrollment_id,
            workflow_id=workflow_id,
            temporal_workflow_id=temporal_workflow_id,
            error=str(error),
        )

    return LeadStartResult(
        lead_id=lead_id,
        status=LeadStartStatus.STARTED,
        campaign_enrollment_id=campaign_enrollment_id,
        workflow_id=workflow_id,
        temporal_workflow_id=temporal_workflow_id,
    )


def _default_temporal_workflow_id(lead_id: LeadId, campaign_enrollment_id: UUID) -> str:
    return f"lead-nurture:{lead_id}:{campaign_enrollment_id}"
