from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    LeadWorkflowRepository,
    PausedSearchTrackAssignmentRepository,
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
from app.domain.campaigns.enrollment_admission import (
    EnrollmentAdmissionOutcome,
    evaluate_lead_enrollment_admission,
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
    reentry_reason: str | None = None,
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
    paused_search_track_assignment_repository: (
        PausedSearchTrackAssignmentRepository | None
    ) = None,
    commit: Callable[[], Awaitable[None]] | None = None,
    rollback: Callable[[], Awaitable[None]] | None = None,
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

    latest_workflow = await lead_workflow_repository.get_latest_for_lead_for_update(
        workspace_id,
        lead_id,
    )
    enrolling_paused_search = paused_search_track_version_id is not None
    has_active_paused_search_assignment = False
    if not enrolling_paused_search and paused_search_track_assignment_repository is not None:
        active_assignment = (
            await paused_search_track_assignment_repository.get_active_for_lead_for_update(
                workspace_id, lead_id
            )
        )
        has_active_paused_search_assignment = active_assignment is not None
    admission = evaluate_lead_enrollment_admission(
        campaign_id=campaign_id,
        source=source,
        latest_workflow=latest_workflow,
        enrolling_paused_search=enrolling_paused_search,
        has_active_paused_search_assignment=has_active_paused_search_assignment,
    )
    if not admission.admitted:
        return LeadStartResult(
            lead_id=lead_id,
            status=_admission_start_status(admission.outcome),
            workflow_id=latest_workflow.workflow_id if latest_workflow is not None else None,
            error=admission.reason,
        )
    normalized_reentry_reason = reentry_reason.strip() if reentry_reason else ""
    if admission.requires_reentry_reason and not normalized_reentry_reason:
        return LeadStartResult(
            lead_id=lead_id,
            status=LeadStartStatus.REENTRY_REASON_REQUIRED,
            workflow_id=latest_workflow.workflow_id if latest_workflow is not None else None,
            error="A reason is required for admin re-entry after a terminal workflow.",
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

    transition_metadata = dict(metadata or {})
    if normalized_reentry_reason:
        transition_metadata["manual_reentry_reason"] = normalized_reentry_reason

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
        metadata=transition_metadata,
    )

    try:
        enrollment = await campaign_enrollment_repository.save(enrollment)
        campaign_enrollment_id = enrollment.campaign_enrollment_id
        if workflow.campaign_enrollment_id != campaign_enrollment_id:
            workflow = replace(workflow, campaign_enrollment_id=campaign_enrollment_id)
        await lead_workflow_repository.save(workflow)
    except Exception as error:
        race_result = await _recover_enrollment_race(
            error=error,
            rollback=rollback,
            workspace_id=workspace_id,
            lead_id=lead_id,
            campaign_id=campaign_id,
            source=source,
            lead_workflow_repository=lead_workflow_repository,
        )
        if race_result is not None:
            return race_result
        return LeadStartResult(
            lead_id=lead_id,
            status=LeadStartStatus.FAILED,
            campaign_enrollment_id=campaign_enrollment_id,
            workflow_id=workflow_id,
            temporal_workflow_id=temporal_workflow_id,
            error=str(error),
        )

    try:
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
    except Exception as error:
        if rollback is not None:
            await rollback()
        return LeadStartResult(
            lead_id=lead_id,
            status=LeadStartStatus.FAILED,
            campaign_enrollment_id=campaign_enrollment_id,
            workflow_id=workflow_id,
            temporal_workflow_id=temporal_workflow_id,
            error=str(error),
        )

    try:
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


async def _recover_enrollment_race(
    *,
    error: Exception,
    rollback: Callable[[], Awaitable[None]] | None,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    campaign_id: CampaignId,
    source: CampaignEnrollmentSource,
    lead_workflow_repository: LeadWorkflowRepository,
) -> LeadStartResult | None:
    if rollback is None:
        return None
    try:
        await rollback()
        latest_workflow = await lead_workflow_repository.get_latest_for_lead_for_update(
            workspace_id,
            lead_id,
        )
    except Exception:
        return None
    admission = evaluate_lead_enrollment_admission(
        campaign_id=campaign_id,
        source=source,
        latest_workflow=latest_workflow,
    )
    if latest_workflow is None or admission.admitted:
        return None
    return LeadStartResult(
        lead_id=lead_id,
        status=_admission_start_status(admission.outcome),
        workflow_id=latest_workflow.workflow_id,
        error=admission.reason or str(error),
    )


def _admission_start_status(outcome: EnrollmentAdmissionOutcome) -> LeadStartStatus:
    if outcome == EnrollmentAdmissionOutcome.ALREADY_ACTIVE_IN_CAMPAIGN:
        return LeadStartStatus.ALREADY_ENROLLED
    if outcome == EnrollmentAdmissionOutcome.TERMINAL_REQUIRES_MANUAL_ENROLLMENT:
        return LeadStartStatus.TERMINAL_REQUIRES_MANUAL_ENROLLMENT
    if outcome == EnrollmentAdmissionOutcome.PAUSED_SEARCH_TRACK_ASSIGNED:
        return LeadStartStatus.PAUSED_SEARCH_TRACK_ASSIGNED
    return LeadStartStatus.ALREADY_ACTIVE_ELSEWHERE


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
