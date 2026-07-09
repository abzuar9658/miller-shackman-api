from collections.abc import Mapping

from temporalio import activity

from app.application.services.llm.reply_classification import InboundReplyIntent
from app.application.use_cases.apply_inbound_workflow_transition import (
    InboundWorkflowTransitionOutcome,
    apply_inbound_workflow_transition,
)
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionOutcome,
    apply_workflow_state_transition,
)
from app.application.use_cases.campaign_cadence_execution import (
    FirstCadenceStepExecutionResult,
    FirstCadenceStepScheduleResult,
    execute_first_campaign_cadence_step,
    schedule_first_campaign_cadence_step,
)
from app.core.database import async_session_factory
from app.domain.workflows import WorkflowState, WorkflowTransitionReasonCode
from app.infrastructure.persistence.postgres.campaign_execution_repository import (
    PostgresCampaignExecutionRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import PostgresWorkspaceRepository
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from app.infrastructure.providers import build_email_provider, build_llm_client, build_sms_provider
from app.infrastructure.workflows.temporal.lead_nurture import (
    ExecuteFirstCadenceStepInput,
    ExecuteFirstCadenceStepResult,
    InboundReplySignal,
    PauseWorkflowSignal,
    ResumeWorkflowSignal,
    ScheduleFirstCadenceStepInput,
    ScheduleFirstCadenceStepResult,
    WorkflowSignalActivityResult,
)


@activity.defn(name="apply-inbound-workflow-transition")
async def apply_inbound_workflow_transition_activity(
    signal: InboundReplySignal,
) -> WorkflowSignalActivityResult:
    intent = _intent_or_none(signal.intent)
    if signal.intent is not None and intent is None:
        return WorkflowSignalActivityResult(
            status="skipped",
            skip_reason=f"Unsupported inbound intent: {signal.intent}",
        )

    async with async_session_factory() as session:
        outcome = await apply_inbound_workflow_transition(
            workspace_id=signal.workspace_id,
            lead_id=signal.lead_id,
            handoff_required=signal.handoff_required,
            opt_out_detected=signal.opt_out_detected,
            classification_rejected=signal.classification_rejected,
            lead_workflow_repository=PostgresLeadWorkflowRepository(session),
            workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
            now=signal.occurred_at,
            external_event_id=signal.external_event_id,
            conversation_id=signal.conversation_id,
            inbound_message_id=signal.inbound_message_id,
            handoff_id=signal.handoff_id,
            intent=intent,
            classification_reasons=signal.classification_reasons,
        )
        await session.commit()
    return _inbound_outcome_to_result(outcome)


@activity.defn(name="record-pause-workflow-signal")
async def record_pause_workflow_signal_activity(
    signal: PauseWorkflowSignal,
) -> WorkflowSignalActivityResult:
    async with async_session_factory() as session:
        outcome = await apply_workflow_state_transition(
            workspace_id=signal.workspace_id,
            lead_id=signal.lead_id,
            to_state=WorkflowState.PAUSED,
            reason_code=WorkflowTransitionReasonCode.MANUAL_PAUSE,
            lead_workflow_repository=PostgresLeadWorkflowRepository(session),
            workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
            now=signal.occurred_at,
            actor_user_id=signal.actor_user_id,
            external_event_id=signal.external_event_id,
            metadata=_reason_metadata(signal.reason),
            pause_reason=signal.reason,
        )
        await session.commit()
    return _state_outcome_to_result(outcome)


@activity.defn(name="record-resume-workflow-signal")
async def record_resume_workflow_signal_activity(
    signal: ResumeWorkflowSignal,
) -> WorkflowSignalActivityResult:
    if signal.actor_user_id is None or not signal.reason.strip():
        return WorkflowSignalActivityResult(
            status="skipped",
            skip_reason="Resume requires an authorized actor and a reason.",
        )

    async with async_session_factory() as session:
        outcome = await apply_workflow_state_transition(
            workspace_id=signal.workspace_id,
            lead_id=signal.lead_id,
            to_state=WorkflowState.ACTIVE_NURTURE,
            reason_code=WorkflowTransitionReasonCode.MANUAL_RESUME,
            lead_workflow_repository=PostgresLeadWorkflowRepository(session),
            workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
            now=signal.occurred_at,
            actor_user_id=signal.actor_user_id,
            external_event_id=signal.external_event_id,
            metadata=_reason_metadata(signal.reason),
            resume_reason=signal.reason,
        )
        await session.commit()
    return _state_outcome_to_result(outcome)


@activity.defn(name="schedule-first-campaign-cadence-step")
async def schedule_first_campaign_cadence_step_activity(
    input_: ScheduleFirstCadenceStepInput,
) -> ScheduleFirstCadenceStepResult:
    async with async_session_factory() as session:
        outcome = await schedule_first_campaign_cadence_step(
            workspace_id=input_.workspace_id,
            lead_id=input_.lead_id,
            campaign_version_id=input_.campaign_version_id,
            campaign_execution_repository=PostgresCampaignExecutionRepository(session),
            lead_workflow_repository=PostgresLeadWorkflowRepository(session),
            now=input_.occurred_at,
        )
        await session.commit()
    return _schedule_outcome_to_result(outcome)


@activity.defn(name="execute-first-campaign-cadence-step")
async def execute_first_campaign_cadence_step_activity(
    input_: ExecuteFirstCadenceStepInput,
) -> ExecuteFirstCadenceStepResult:
    async with async_session_factory() as session:
        outcome = await execute_first_campaign_cadence_step(
            workspace_id=input_.workspace_id,
            lead_id=input_.lead_id,
            campaign_version_id=input_.campaign_version_id,
            scheduled_for=input_.scheduled_for,
            campaign_execution_repository=PostgresCampaignExecutionRepository(session),
            workspace_repository=PostgresWorkspaceRepository(session),
            lead_repository=PostgresLeadRepository(session),
            lead_workflow_repository=PostgresLeadWorkflowRepository(session),
            workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
            message_repository=PostgresOutboundMessageRepository(session),
            llm_client=build_llm_client(),
            sms_provider=build_sms_provider(),
            email_provider=build_email_provider(),
            now=input_.occurred_at,
        )
        await session.commit()
    return _execution_outcome_to_result(outcome)


def _intent_or_none(raw_intent: str | None) -> InboundReplyIntent | None:
    if raw_intent is None:
        return None
    try:
        return InboundReplyIntent(raw_intent)
    except ValueError:
        return None


def _reason_metadata(reason: str) -> Mapping[str, object]:
    return {"reason": reason}


def _inbound_outcome_to_result(
    outcome: InboundWorkflowTransitionOutcome,
) -> WorkflowSignalActivityResult:
    return WorkflowSignalActivityResult(
        status=outcome.status.value,
        workflow_id=outcome.workflow.workflow_id if outcome.workflow is not None else None,
        transition_id=outcome.transition_id,
        skip_reason=outcome.skip_reason,
    )


def _state_outcome_to_result(
    outcome: WorkflowStateTransitionOutcome,
) -> WorkflowSignalActivityResult:
    return WorkflowSignalActivityResult(
        status=outcome.status.value,
        workflow_id=outcome.workflow.workflow_id if outcome.workflow is not None else None,
        transition_id=outcome.transition_id,
        skip_reason=outcome.skip_reason,
    )


def _schedule_outcome_to_result(
    outcome: FirstCadenceStepScheduleResult,
) -> ScheduleFirstCadenceStepResult:
    return ScheduleFirstCadenceStepResult(
        status=outcome.status.value,
        workflow_id=outcome.workflow.workflow_id if outcome.workflow is not None else None,
        cadence_step_id=outcome.cadence_step_id,
        scheduled_for=outcome.scheduled_for,
        skip_reason=outcome.skip_reason,
    )


def _execution_outcome_to_result(
    outcome: FirstCadenceStepExecutionResult,
) -> ExecuteFirstCadenceStepResult:
    return ExecuteFirstCadenceStepResult(
        status=outcome.status.value,
        workflow_id=outcome.workflow.workflow_id if outcome.workflow is not None else None,
        transition_id=outcome.transition_id,
        cadence_step_id=outcome.cadence_step_id,
        outbound_message_id=outcome.outbound_message_id,
        provider_message_id=outcome.provider_message_id,
        skip_reason=outcome.skip_reason,
    )
