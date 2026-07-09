from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from app.application.ports.llm import LLMClient
from app.application.ports.messaging import EmailProvider, SMSProvider
from app.application.ports.repositories import (
    CampaignExecutionRepository,
    LeadRepository,
    LeadWorkflowRepository,
    OutboundMessageRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceRepository,
)
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionStatus,
    apply_workflow_state_transition,
)
from app.application.use_cases.plan_next_outbound_message import (
    PlanNextOutboundMessageContext,
    plan_next_outbound_message_for_lead,
)
from app.application.use_cases.plan_outbound_message import PlanOutboundMessageStatus
from app.application.use_cases.send_outbound_message import (
    OutboundSendContext,
    SendOutboundMessageStatus,
    send_outbound_message,
)
from app.domain.campaigns.execution import CampaignCadenceStep
from app.domain.campaigns.pre_send import PreSendPolicy
from app.domain.common.ids import CampaignVersionId, LeadId, WorkspaceId
from app.domain.compliance.contactability import (
    WorkspaceContactPolicy,
    default_workspace_contact_policy,
)
from app.domain.workflows import LeadWorkflow, WorkflowState, WorkflowTransitionReasonCode


class FirstCadenceStepScheduleStatus(StrEnum):
    SCHEDULED = "scheduled"
    NO_WORKFLOW = "no_workflow"
    MISSING_CAMPAIGN_CONFIG = "missing_campaign_config"
    NO_CADENCE_STEP = "no_cadence_step"


class FirstCadenceStepExecutionStatus(StrEnum):
    SENT = "sent"
    ALREADY_SENT = "already_sent"
    ALREADY_WAITING_FOR_RESPONSE = "already_waiting_for_response"
    REJECTED = "rejected"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    SKIPPED = "skipped"
    NO_WORKFLOW = "no_workflow"
    MISSING_CAMPAIGN_CONFIG = "missing_campaign_config"
    NO_CADENCE_STEP = "no_cadence_step"
    MISSING_WORKSPACE = "missing_workspace"


@dataclass(frozen=True)
class FirstCadenceStepScheduleResult:
    status: FirstCadenceStepScheduleStatus
    workflow: LeadWorkflow | None = None
    cadence_step_id: UUID | None = None
    scheduled_for: datetime | None = None
    skip_reason: str | None = None


@dataclass(frozen=True)
class FirstCadenceStepExecutionResult:
    status: FirstCadenceStepExecutionStatus
    workflow: LeadWorkflow | None = None
    transition_id: UUID | None = None
    cadence_step_id: UUID | None = None
    outbound_message_id: UUID | None = None
    provider_message_id: str | None = None
    skip_reason: str | None = None


async def schedule_first_campaign_cadence_step(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    campaign_version_id: CampaignVersionId,
    campaign_execution_repository: CampaignExecutionRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    now: datetime,
) -> FirstCadenceStepScheduleResult:
    config = await campaign_execution_repository.get_by_version_id(
        workspace_id, campaign_version_id
    )
    if config is None:
        return FirstCadenceStepScheduleResult(
            status=FirstCadenceStepScheduleStatus.MISSING_CAMPAIGN_CONFIG,
        )

    step = _first_step(config.cadence_steps)
    if step is None:
        return FirstCadenceStepScheduleResult(status=FirstCadenceStepScheduleStatus.NO_CADENCE_STEP)

    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(workspace_id, lead_id)
    if workflow is None:
        return FirstCadenceStepScheduleResult(status=FirstCadenceStepScheduleStatus.NO_WORKFLOW)

    scheduled_for = workflow.next_action_at
    if workflow.current_step_id != step.cadence_step_id or scheduled_for is None:
        scheduled_for = now + timedelta(hours=step.delay_hours)
        workflow = await lead_workflow_repository.save(
            replace(
                workflow,
                current_step_id=step.cadence_step_id,
                next_action_at=scheduled_for,
                updated_at=now,
            )
        )

    return FirstCadenceStepScheduleResult(
        status=FirstCadenceStepScheduleStatus.SCHEDULED,
        workflow=workflow,
        cadence_step_id=step.cadence_step_id,
        scheduled_for=scheduled_for,
    )


async def execute_first_campaign_cadence_step(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    campaign_version_id: CampaignVersionId,
    scheduled_for: datetime,
    campaign_execution_repository: CampaignExecutionRepository,
    workspace_repository: WorkspaceRepository,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository,
    lead_repository: LeadRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    message_repository: OutboundMessageRepository,
    llm_client: LLMClient,
    sms_provider: SMSProvider,
    email_provider: EmailProvider,
    now: datetime,
) -> FirstCadenceStepExecutionResult:
    config = await campaign_execution_repository.get_by_version_id(
        workspace_id, campaign_version_id
    )
    if config is None:
        return FirstCadenceStepExecutionResult(
            status=FirstCadenceStepExecutionStatus.MISSING_CAMPAIGN_CONFIG,
        )

    step = _first_step(config.cadence_steps)
    if step is None:
        return FirstCadenceStepExecutionResult(
            status=FirstCadenceStepExecutionStatus.NO_CADENCE_STEP
        )

    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(workspace_id, lead_id)
    if workflow is None:
        return FirstCadenceStepExecutionResult(status=FirstCadenceStepExecutionStatus.NO_WORKFLOW)

    if (
        workflow.state == WorkflowState.WAITING_FOR_RESPONSE
        and workflow.current_step_id == step.cadence_step_id
    ):
        return FirstCadenceStepExecutionResult(
            status=FirstCadenceStepExecutionStatus.ALREADY_WAITING_FOR_RESPONSE,
            workflow=workflow,
            cadence_step_id=step.cadence_step_id,
        )

    if workflow.state in {
        WorkflowState.PAUSED,
        WorkflowState.HUMAN_HANDOFF,
        WorkflowState.HUMAN_OWNED,
        WorkflowState.COMPLETED,
        WorkflowState.SUPPRESSED,
        WorkflowState.CLOSED,
    }:
        return FirstCadenceStepExecutionResult(
            status=FirstCadenceStepExecutionStatus.SKIPPED,
            workflow=workflow,
            cadence_step_id=step.cadence_step_id,
            skip_reason=f"Workflow is not sendable from state {workflow.state.value}.",
        )

    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return FirstCadenceStepExecutionResult(
            status=FirstCadenceStepExecutionStatus.MISSING_WORKSPACE,
            workflow=workflow,
            cadence_step_id=step.cadence_step_id,
        )

    workspace_contact_policy = await workspace_contact_policy_repository.get_by_workspace_id(
        workspace_id,
    )
    if workspace_contact_policy is None:
        workspace_contact_policy = default_workspace_contact_policy(workspace_id)

    pre_send_policy = _pre_send_policy(
        workspace_contact_policy,
        workspace.default_timezone,
    )

    if workflow.state != WorkflowState.ACTIVE_NURTURE:
        active_outcome = await apply_workflow_state_transition(
            workspace_id=workspace_id,
            lead_id=lead_id,
            to_state=WorkflowState.ACTIVE_NURTURE,
            reason_code=WorkflowTransitionReasonCode.CADENCE_STEP_STARTED,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            now=now,
            metadata={"cadence_step_id": str(step.cadence_step_id)},
        )
        if (
            active_outcome.status != WorkflowStateTransitionStatus.UPDATED
            or active_outcome.workflow is None
        ):
            return FirstCadenceStepExecutionResult(
                status=FirstCadenceStepExecutionStatus.SKIPPED,
                workflow=active_outcome.workflow or workflow,
                cadence_step_id=step.cadence_step_id,
                skip_reason=active_outcome.skip_reason,
            )

    planning_context = PlanNextOutboundMessageContext(
        campaign_status=config.campaign_status,
        workflow_state=WorkflowState.ACTIVE_NURTURE,
        enabled_channels=(step.channel,),
        workspace_contact_policy=workspace_contact_policy,
        campaign_goal=step.message_goal,
        brokerage_name=workspace.name,
        cadence_step_id=str(step.cadence_step_id),
        scheduled_for=scheduled_for,
        pre_send_policy=pre_send_policy,
    )
    plan_result = await plan_next_outbound_message_for_lead(
        workspace_id=workspace_id,
        lead_id=lead_id,
        campaign_id=config.campaign_id,
        context=planning_context,
        lead_repository=lead_repository,
        message_repository=message_repository,
        llm_client=llm_client,
        now=now,
    )
    if plan_result.status == PlanOutboundMessageStatus.REJECTED or plan_result.message is None:
        return await _pause_after_block(
            workspace_id=workspace_id,
            lead_id=lead_id,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            cadence_step_id=step.cadence_step_id,
            now=now,
            reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED,
            skip_reason=_reason_values(plan_result.reasons),
            status=FirstCadenceStepExecutionStatus.REJECTED,
        )

    send_context = OutboundSendContext(
        campaign_status=config.campaign_status,
        workflow_state=WorkflowState.ACTIVE_NURTURE,
        enabled_channels=(step.channel,),
        workspace_contact_policy=workspace_contact_policy,
        current_message_version=plan_result.message.message_version,
        pre_send_policy=pre_send_policy,
    )
    send_result = await send_outbound_message(
        workspace_id=workspace_id,
        idempotency_key=plan_result.message.idempotency_key,
        context=send_context,
        lead_repository=lead_repository,
        message_repository=message_repository,
        sms_provider=sms_provider,
        email_provider=email_provider,
        now=now,
    )
    if send_result.status in {
        SendOutboundMessageStatus.SENT,
        SendOutboundMessageStatus.ALREADY_SENT,
    }:
        waiting_outcome = await apply_workflow_state_transition(
            workspace_id=workspace_id,
            lead_id=lead_id,
            to_state=WorkflowState.WAITING_FOR_RESPONSE,
            reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_SENT,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            now=now,
            metadata={
                "cadence_step_id": str(step.cadence_step_id),
                "outbound_message_id": str(send_result.message.message_id)
                if send_result.message
                else None,
            },
        )
        workflow_outcome = waiting_outcome.workflow
        if (
            waiting_outcome.status == WorkflowStateTransitionStatus.UPDATED
            and workflow_outcome is not None
        ):
            workflow_outcome = await lead_workflow_repository.save(
                replace(workflow_outcome, next_action_at=None, updated_at=now)
            )
        return FirstCadenceStepExecutionResult(
            status=(
                FirstCadenceStepExecutionStatus.SENT
                if send_result.status == SendOutboundMessageStatus.SENT
                else FirstCadenceStepExecutionStatus.ALREADY_SENT
            ),
            workflow=workflow_outcome,
            transition_id=waiting_outcome.transition_id,
            cadence_step_id=step.cadence_step_id,
            outbound_message_id=send_result.message.message_id if send_result.message else None,
            provider_message_id=send_result.message.provider_message_id
            if send_result.message
            else None,
        )

    return await _pause_after_block(
        workspace_id=workspace_id,
        lead_id=lead_id,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        cadence_step_id=step.cadence_step_id,
        now=now,
        reason_code=(
            WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED
            if send_result.status == SendOutboundMessageStatus.REJECTED
            else WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_FAILED
        ),
        skip_reason=_reason_values(send_result.reasons),
        status={
            SendOutboundMessageStatus.REJECTED: FirstCadenceStepExecutionStatus.REJECTED,
            SendOutboundMessageStatus.FAILED: FirstCadenceStepExecutionStatus.FAILED,
            SendOutboundMessageStatus.UNCERTAIN: FirstCadenceStepExecutionStatus.UNCERTAIN,
        }.get(send_result.status, FirstCadenceStepExecutionStatus.FAILED),
    )


async def _pause_after_block(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    cadence_step_id: UUID,
    now: datetime,
    reason_code: WorkflowTransitionReasonCode,
    skip_reason: str,
    status: FirstCadenceStepExecutionStatus,
) -> FirstCadenceStepExecutionResult:
    outcome = await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=lead_id,
        to_state=WorkflowState.PAUSED,
        reason_code=reason_code,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=now,
        metadata={"cadence_step_id": str(cadence_step_id), "reason": skip_reason},
        pause_reason="cadence_step_blocked",
    )
    return FirstCadenceStepExecutionResult(
        status=status,
        workflow=outcome.workflow,
        transition_id=outcome.transition_id,
        cadence_step_id=cadence_step_id,
        skip_reason=skip_reason or outcome.skip_reason,
    )


def _first_step(steps: tuple[CampaignCadenceStep, ...]) -> CampaignCadenceStep | None:
    return steps[0] if steps else None


def _pre_send_policy(
    workspace_contact_policy: WorkspaceContactPolicy,
    timezone: str,
) -> PreSendPolicy:
    quiet_hours_start = workspace_contact_policy.quiet_hours_start
    quiet_hours_end = workspace_contact_policy.quiet_hours_end
    return PreSendPolicy(
        allowed_send_start_hour=quiet_hours_start.hour if quiet_hours_start else 10,
        allowed_send_end_hour=quiet_hours_end.hour if quiet_hours_end else 17,
        timezone=timezone,
    )


def _reason_values(reasons: tuple[StrEnum, ...]) -> str:
    return ", ".join(reason.value for reason in reasons)
