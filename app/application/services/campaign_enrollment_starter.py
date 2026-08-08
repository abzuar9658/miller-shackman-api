from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from uuid import UUID, uuid4

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    LeadWorkflowRepository,
    WorkflowTransitionRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.ports.temporal import (
    TemporalWorkflowExecutionMode,
    TemporalWorkflowStarter,
)
from app.application.services.workspace_automation_control import (
    resolve_workspace_operational_control,
    workspace_automation_block_reason,
    workspace_automation_is_active,
)
from app.application.use_cases.campaign_enrollment_types import LeadStartResult, LeadStartStatus
from app.domain.campaigns.enrollment import (
    CampaignEnrollment,
    CampaignEnrollmentSource,
    CampaignEnrollmentStatus,
    build_enrollment_reason_codes,
)
from app.domain.common.ids import (
    CampaignId,
    CampaignVersionId,
    LeadId,
    PausedSearchTrackVersionId,
    UserId,
    WorkspaceId,
)
from app.domain.events import AggregateType, DomainEvent, DomainEventType
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
    initial_workflow_state: WorkflowState = WorkflowState.QUEUED,
    initial_transition_reason_code: WorkflowTransitionReasonCode = (
        WorkflowTransitionReasonCode.CAMPAIGN_ENROLLMENT_STARTED
    ),
    paused_search_track_version_id: PausedSearchTrackVersionId | None = None,
    execution_mode: TemporalWorkflowExecutionMode = (
        TemporalWorkflowExecutionMode.STANDARD_CADENCE
    ),
    event_bus: EventBus | None = None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None,
    commit: Callable[[], Awaitable[None]] | None = None,
) -> LeadStartResult:
    operational_control = await resolve_workspace_operational_control(
        workspace_id=workspace_id,
        workspace_operational_control_repository=workspace_operational_control_repository,
    )
    if not workspace_automation_is_active(operational_control):
        return LeadStartResult(
            lead_id=lead_id,
            status=LeadStartStatus.FAILED,
            error=workspace_automation_block_reason(operational_control),
        )

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
        state=initial_workflow_state,
        current_step_id=None,
        next_action_at=None,
        last_transition_at=now,
        pause_reason=None,
        resume_reason=None,
        paused_search_track_version_id=paused_search_track_version_id,
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
        to_state=initial_workflow_state,
        reason_code=initial_transition_reason_code,
        created_at=now,
        actor_user_id=actor_user_id,
        external_event_id=None,
        metadata=metadata or {},
    )

    try:
        await campaign_enrollment_repository.save(enrollment)
        await lead_workflow_repository.save(workflow)
        await workflow_transition_repository.append(transition)
        await _publish_enrollment_events(
            event_bus=event_bus,
            enrollment=enrollment,
            workflow=workflow,
            transition=transition,
            temporal_workflow_id=temporal_workflow_id,
            now=now,
        )
        if commit is not None:
            await commit()
        await temporal_workflow_starter.start_lead_nurture_workflow(
            workspace_id=workspace_id,
            lead_id=lead_id,
            campaign_version_id=campaign_version_id,
            temporal_workflow_id=temporal_workflow_id,
            workflow_id=workflow_id,
            execution_mode=execution_mode,
            paused_search_track_version_id=paused_search_track_version_id,
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


async def _publish_enrollment_events(
    *,
    event_bus: EventBus | None,
    enrollment: CampaignEnrollment,
    workflow: LeadWorkflow,
    transition: WorkflowTransition,
    temporal_workflow_id: str,
    now: datetime,
) -> None:
    if event_bus is None:
        return
    await event_bus.publish(
        DomainEvent(
            workspace_id=enrollment.workspace_id,
            aggregate_type=AggregateType.CAMPAIGN,
            aggregate_id=enrollment.campaign_id,
            event_type=DomainEventType.CAMPAIGN_ENROLLED,
            payload={
                "campaign_enrollment_id": str(enrollment.campaign_enrollment_id),
                "campaign_id": str(enrollment.campaign_id),
                "campaign_version_id": str(enrollment.campaign_version_id),
                "lead_id": str(enrollment.lead_id),
                "source": enrollment.source.value,
                "status": enrollment.status.value,
                "temporal_workflow_id": temporal_workflow_id,
                "occurred_at": now.isoformat(),
            },
        ),
    )
    await event_bus.publish(
        DomainEvent(
            workspace_id=workflow.workspace_id,
            aggregate_type=AggregateType.WORKFLOW,
            aggregate_id=workflow.workflow_id,
            event_type=DomainEventType.WORKFLOW_TRANSITIONED,
            payload={
                "workflow_id": str(workflow.workflow_id),
                "transition_id": str(transition.transition_id),
                "lead_id": str(workflow.lead_id),
                "campaign_id": str(workflow.campaign_id),
                "from_state": None,
                "to_state": transition.to_state.value,
                "reason_code": transition.reason_code.value,
                "occurred_at": now.isoformat(),
            },
        ),
    )
