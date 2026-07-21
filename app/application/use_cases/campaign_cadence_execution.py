from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.crm import CRMClient
from app.application.ports.lead_activity import LeadActivityRepository
from app.application.ports.listing_search import ListingSearchClient
from app.application.ports.listing_sources import ListingSnapshotRepository, ListingSourceRepository
from app.application.ports.llm import LLMClient
from app.application.ports.messaging import EmailProvider, SMSProvider
from app.application.ports.rejected_draft_review import RejectedDraftReviewRepository
from app.application.ports.repositories import (
    CampaignExecutionRepository,
    CrmConversationEventRepository,
    LeadRepository,
    LeadWorkflowRepository,
    OutboundMessageCRMCompletionRepository,
    OutboundMessageRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceOperationalControlRepository,
    WorkspaceOutboundDraftingConfigRepository,
    WorkspaceRepository,
)
from app.application.services.workspace_automation_control import (
    resolve_workspace_operational_control,
    workspace_automation_block_reason,
    workspace_automation_is_active,
)
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionStatus,
    apply_workflow_state_transition,
)
from app.application.use_cases.complete_outbound_message_crm_sync import (
    complete_outbound_message_crm_sync,
)
from app.application.use_cases.plan_next_outbound_message import (
    PlanNextOutboundMessageContext,
    plan_next_outbound_message_for_lead,
)
from app.application.use_cases.plan_outbound_message import (
    ChannelEvaluation,
    PlanOutboundMessageResult,
    PlanOutboundMessageStatus,
)
from app.application.use_cases.send_outbound_message import (
    OutboundSendContext,
    SendOutboundMessageResult,
    SendOutboundMessageStatus,
    send_outbound_message,
)
from app.domain.campaigns.execution import CampaignCadenceStep
from app.domain.campaigns.pre_send import PreSendPolicy
from app.domain.campaigns.rejected_draft_review import (
    RejectedDraftReview,
    RejectedDraftReviewStatus,
)
from app.domain.common.ids import CampaignVersionId, LeadId, WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    WorkspaceContactPolicy,
    default_workspace_contact_policy,
)
from app.domain.conversations import CrmConversationEventDirection, WorkspaceHandoffConfig
from app.domain.workflows import LeadWorkflow, WorkflowState, WorkflowTransitionReasonCode


class CadenceStepScheduleStatus(StrEnum):
    SCHEDULED = "scheduled"
    NO_WORKFLOW = "no_workflow"
    MISSING_CAMPAIGN_CONFIG = "missing_campaign_config"
    NO_CADENCE_STEP = "no_cadence_step"


class CadenceStepExecutionStatus(StrEnum):
    SENT = "sent"
    ALREADY_SENT = "already_sent"
    ALREADY_WAITING_FOR_RESPONSE = "already_waiting_for_response"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    SKIPPED = "skipped"
    NO_WORKFLOW = "no_workflow"
    MISSING_CAMPAIGN_CONFIG = "missing_campaign_config"
    NO_CADENCE_STEP = "no_cadence_step"
    MISSING_WORKSPACE = "missing_workspace"


@dataclass(frozen=True)
class CadenceStepScheduleResult:
    status: CadenceStepScheduleStatus
    workflow: LeadWorkflow | None = None
    cadence_step_id: UUID | None = None
    scheduled_for: datetime | None = None
    skip_reason: str | None = None


@dataclass(frozen=True)
class CadenceStepExecutionResult:
    status: CadenceStepExecutionStatus
    workflow: LeadWorkflow | None = None
    transition_id: UUID | None = None
    cadence_step_id: UUID | None = None
    outbound_message_id: UUID | None = None
    provider_message_id: str | None = None
    skip_reason: str | None = None
    has_more_steps: bool = False


async def schedule_next_campaign_cadence_step(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    campaign_version_id: CampaignVersionId,
    campaign_execution_repository: CampaignExecutionRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    now: datetime,
) -> CadenceStepScheduleResult:
    config = await campaign_execution_repository.get_by_version_id(
        workspace_id, campaign_version_id
    )
    if config is None:
        return CadenceStepScheduleResult(
            status=CadenceStepScheduleStatus.MISSING_CAMPAIGN_CONFIG,
        )

    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(workspace_id, lead_id)
    if workflow is None:
        return CadenceStepScheduleResult(status=CadenceStepScheduleStatus.NO_WORKFLOW)

    step = _scheduled_or_initial_step(config.cadence_steps, workflow.current_step_id)
    if step is None:
        return CadenceStepScheduleResult(status=CadenceStepScheduleStatus.NO_CADENCE_STEP)

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

    return CadenceStepScheduleResult(
        status=CadenceStepScheduleStatus.SCHEDULED,
        workflow=workflow,
        cadence_step_id=step.cadence_step_id,
        scheduled_for=scheduled_for,
    )


async def execute_campaign_cadence_step(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    campaign_version_id: CampaignVersionId,
    cadence_step_id: UUID,
    scheduled_for: datetime,
    campaign_execution_repository: CampaignExecutionRepository,
    workspace_repository: WorkspaceRepository,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None = None,
    workspace_outbound_drafting_config_repository: WorkspaceOutboundDraftingConfigRepository
    | None = None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None,
    lead_repository: LeadRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    message_repository: OutboundMessageRepository,
    rejected_draft_review_repository: RejectedDraftReviewRepository | None = None,
    lead_activity_repository: LeadActivityRepository | None = None,
    crm_conversation_event_repository: CrmConversationEventRepository | None = None,
    listing_source_repository: ListingSourceRepository | None = None,
    listing_snapshot_repository: ListingSnapshotRepository | None = None,
    listing_search_client: ListingSearchClient | None = None,
    listing_enrichment_enabled: bool = False,
    listing_cache_ttl: timedelta = timedelta(hours=6),
    listing_max_results: int = 3,
    llm_client: LLMClient,
    sms_provider: SMSProvider,
    email_provider: EmailProvider,
    crm_client: CRMClient | None = None,
    outbound_message_crm_completion_repository: (
        OutboundMessageCRMCompletionRepository | None
    ) = None,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None = None,
    now: datetime,
    default_openrouter_model: str = "openai/gpt-4o-mini",
    workspace_automation_defer_interval: timedelta = timedelta(minutes=15),
) -> CadenceStepExecutionResult:
    config = await campaign_execution_repository.get_by_version_id(
        workspace_id, campaign_version_id
    )
    if config is None:
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.MISSING_CAMPAIGN_CONFIG,
        )

    step = _step_by_id(config.cadence_steps, cadence_step_id)
    if step is None:
        return CadenceStepExecutionResult(status=CadenceStepExecutionStatus.NO_CADENCE_STEP)

    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(workspace_id, lead_id)
    if workflow is None:
        return CadenceStepExecutionResult(status=CadenceStepExecutionStatus.NO_WORKFLOW)

    if workflow.current_step_id not in {None, step.cadence_step_id}:
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.SKIPPED,
            workflow=workflow,
            cadence_step_id=step.cadence_step_id,
            skip_reason="Workflow cursor does not match the scheduled cadence step.",
        )

    if (
        workflow.state == WorkflowState.WAITING_FOR_RESPONSE
        and workflow.current_step_id == step.cadence_step_id
        and workflow.next_action_at is None
    ):
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.ALREADY_WAITING_FOR_RESPONSE,
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
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.SKIPPED,
            workflow=workflow,
            cadence_step_id=step.cadence_step_id,
            skip_reason=f"Workflow is not sendable from state {workflow.state.value}.",
        )

    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.MISSING_WORKSPACE,
            workflow=workflow,
            cadence_step_id=step.cadence_step_id,
        )

    operational_control = await resolve_workspace_operational_control(
        workspace_id=workspace_id,
        workspace_operational_control_repository=workspace_operational_control_repository,
    )
    if not workspace_automation_is_active(operational_control):
        deferred_until = now + workspace_automation_defer_interval
        workflow = await lead_workflow_repository.save(
            replace(
                workflow,
                current_step_id=step.cadence_step_id,
                next_action_at=deferred_until,
                updated_at=now,
            )
        )
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.DEFERRED,
            workflow=workflow,
            cadence_step_id=step.cadence_step_id,
            skip_reason=workspace_automation_block_reason(operational_control),
            has_more_steps=True,
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

    if workflow.current_step_id != step.cadence_step_id or workflow.next_action_at != scheduled_for:
        workflow = await lead_workflow_repository.save(
            replace(
                workflow,
                current_step_id=step.cadence_step_id,
                next_action_at=scheduled_for,
                updated_at=now,
            )
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
            return CadenceStepExecutionResult(
                status=CadenceStepExecutionStatus.SKIPPED,
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
        lead_activity_repository=lead_activity_repository,
        crm_conversation_event_repository=crm_conversation_event_repository,
        llm_client=llm_client,
        now=now,
        workspace_llm_config_repository=workspace_llm_config_repository,
        workspace_outbound_drafting_config_repository=workspace_outbound_drafting_config_repository,
        default_openrouter_model=default_openrouter_model,
        listing_source_repository=listing_source_repository,
        listing_snapshot_repository=listing_snapshot_repository,
        listing_search_client=listing_search_client,
        listing_enrichment_enabled=listing_enrichment_enabled,
        listing_cache_ttl=listing_cache_ttl,
        listing_max_results=listing_max_results,
    )
    if plan_result.status == PlanOutboundMessageStatus.REJECTED or plan_result.message is None:
        block_metadata = _planning_block_metadata(
            cadence_step_id=step.cadence_step_id,
            plan_result=plan_result,
        )
        blocked_result = await _pause_after_block(
            workspace_id=workspace_id,
            lead_id=lead_id,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            cadence_step_id=step.cadence_step_id,
            now=now,
            reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED,
            skip_reason=str(block_metadata.get("explanation", _reason_values(plan_result.reasons))),
            metadata=block_metadata,
            status=CadenceStepExecutionStatus.REJECTED,
        )
        if (
            rejected_draft_review_repository is not None
            and blocked_result.transition_id is not None
            and workflow is not None
            and _should_persist_rejected_draft_review(plan_result)
        ):
            await rejected_draft_review_repository.save(
                _rejected_draft_review(
                    workspace_id=workspace_id,
                    workflow_id=workflow.workflow_id,
                    transition_id=blocked_result.transition_id,
                    campaign_id=config.campaign_id,
                    campaign_version_id=campaign_version_id,
                    lead_id=lead_id,
                    cadence_step_id=step.cadence_step_id,
                    channel=step.channel,
                    plan_result=plan_result,
                    now=now,
                )
            )
        return blocked_result

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
        workspace_operational_control_repository=workspace_operational_control_repository,
        now=now,
    )
    if send_result.status in {
        SendOutboundMessageStatus.SENT,
        SendOutboundMessageStatus.ALREADY_SENT,
    }:
        if (
            send_result.message is not None
            and crm_client is not None
            and outbound_message_crm_completion_repository is not None
        ):
            lead = await lead_repository.get_by_id(workspace_id, lead_id)
            handoff_config = await _load_workspace_handoff_config(
                workspace_id=workspace_id,
                workspace_handoff_config_repository=workspace_handoff_config_repository,
            )
            if lead is not None:
                await complete_outbound_message_crm_sync(
                    lead=lead,
                    outbound_message=send_result.message,
                    crm_sync_completion_repository=outbound_message_crm_completion_repository,
                    crm_client=crm_client,
                    now=now,
                    summary_text=_summary_text_for_outbound_conversation(send_result.message),
                    latest_inbound_text=await _latest_inbound_conversation_text(
                        workspace_id=workspace_id,
                        lead_id=lead_id,
                        crm_conversation_event_repository=crm_conversation_event_repository,
                    ),
                    workspace_handoff_config=handoff_config,
                    snapshot_status="waiting_for_response",
                )
        return await advance_workflow_after_outbound_send(
            workspace_id=workspace_id,
            lead_id=lead_id,
            workflow=workflow,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            cadence_steps=config.cadence_steps,
            cadence_step_id=step.cadence_step_id,
            send_result=send_result,
            now=now,
        )

    block_metadata = _send_block_metadata(
        cadence_step_id=step.cadence_step_id,
        send_result=send_result,
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
        skip_reason=str(block_metadata.get("explanation", _reason_values(send_result.reasons))),
        metadata=block_metadata,
        status={
            SendOutboundMessageStatus.REJECTED: CadenceStepExecutionStatus.REJECTED,
            SendOutboundMessageStatus.FAILED: CadenceStepExecutionStatus.FAILED,
            SendOutboundMessageStatus.UNCERTAIN: CadenceStepExecutionStatus.UNCERTAIN,
        }.get(send_result.status, CadenceStepExecutionStatus.FAILED),
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
    metadata: Mapping[str, object] | None = None,
    status: CadenceStepExecutionStatus,
) -> CadenceStepExecutionResult:
    transition_metadata: dict[str, object] = {
        "cadence_step_id": str(cadence_step_id),
        "reason": skip_reason,
    }
    if metadata is not None:
        transition_metadata.update(metadata)

    outcome = await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=lead_id,
        to_state=WorkflowState.PAUSED,
        reason_code=reason_code,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=now,
        metadata=transition_metadata,
        pause_reason="cadence_step_blocked",
    )
    return CadenceStepExecutionResult(
        status=status,
        workflow=outcome.workflow,
        transition_id=outcome.transition_id,
        cadence_step_id=cadence_step_id,
        skip_reason=skip_reason or outcome.skip_reason,
    )


async def advance_workflow_after_outbound_send(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    workflow: LeadWorkflow,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    cadence_steps: tuple[CampaignCadenceStep, ...],
    cadence_step_id: UUID,
    send_result: SendOutboundMessageResult,
    now: datetime,
) -> CadenceStepExecutionResult:
    waiting_outcome = await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=lead_id,
        to_state=WorkflowState.WAITING_FOR_RESPONSE,
        reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_SENT,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=now,
        metadata={
            "cadence_step_id": str(cadence_step_id),
            "outbound_message_id": (
                str(send_result.message.message_id) if send_result.message else None
            ),
        },
    )
    if (
        waiting_outcome.status != WorkflowStateTransitionStatus.UPDATED
        or waiting_outcome.workflow is None
    ):
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.SKIPPED,
            workflow=waiting_outcome.workflow or workflow,
            transition_id=waiting_outcome.transition_id,
            cadence_step_id=cadence_step_id,
            outbound_message_id=send_result.message.message_id if send_result.message else None,
            provider_message_id=(
                send_result.message.provider_message_id if send_result.message else None
            ),
            skip_reason=waiting_outcome.skip_reason,
        )

    next_step = _next_step(cadence_steps, cadence_step_id)
    workflow_outcome = await lead_workflow_repository.save(
        replace(
            waiting_outcome.workflow,
            current_step_id=next_step.cadence_step_id if next_step is not None else cadence_step_id,
            next_action_at=None,
            updated_at=now,
        )
    )
    return CadenceStepExecutionResult(
        status=(
            CadenceStepExecutionStatus.SENT
            if send_result.status == SendOutboundMessageStatus.SENT
            else CadenceStepExecutionStatus.ALREADY_SENT
        ),
        workflow=workflow_outcome,
        transition_id=waiting_outcome.transition_id,
        cadence_step_id=cadence_step_id,
        outbound_message_id=send_result.message.message_id if send_result.message else None,
        provider_message_id=(
            send_result.message.provider_message_id if send_result.message else None
        ),
        has_more_steps=next_step is not None,
    )


def _scheduled_or_initial_step(
    steps: tuple[CampaignCadenceStep, ...],
    current_step_id: UUID | None,
) -> CampaignCadenceStep | None:
    if not steps:
        return None
    if current_step_id is None:
        return steps[0]
    return _step_by_id(steps, current_step_id)


async def _load_workspace_handoff_config(
    *,
    workspace_id: WorkspaceId,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None,
) -> WorkspaceHandoffConfig | None:
    if workspace_handoff_config_repository is None:
        return None
    return await workspace_handoff_config_repository.get_by_workspace_id(workspace_id)


async def _latest_inbound_conversation_text(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    crm_conversation_event_repository: CrmConversationEventRepository | None,
) -> str | None:
    if crm_conversation_event_repository is None:
        return None
    events = await crm_conversation_event_repository.list_for_lead(
        workspace_id,
        lead_id,
        limit=24,
    )
    for event in events:
        if event.direction != CrmConversationEventDirection.INBOUND or event.content is None:
            continue
        content = event.content.strip()
        if content:
            return content
    return None


def _summary_text_for_outbound_conversation(message: object) -> str | None:
    notes = getattr(message, "draft_personalization_notes", ())
    if not isinstance(notes, tuple):
        return None
    normalized_notes = [note.strip() for note in notes if isinstance(note, str) and note.strip()]
    if not normalized_notes:
        return None
    return "\n".join(normalized_notes)


def _step_by_id(
    steps: tuple[CampaignCadenceStep, ...],
    cadence_step_id: UUID,
) -> CampaignCadenceStep | None:
    for step in steps:
        if step.cadence_step_id == cadence_step_id:
            return step
    return None


def _next_step(
    steps: tuple[CampaignCadenceStep, ...],
    current_step_id: UUID,
) -> CampaignCadenceStep | None:
    for index, step in enumerate(steps):
        if step.cadence_step_id == current_step_id:
            next_index = index + 1
            return steps[next_index] if next_index < len(steps) else None
    return None


def _pre_send_policy(
    workspace_contact_policy: WorkspaceContactPolicy,
    timezone: str,
) -> PreSendPolicy:
    if not workspace_contact_policy.quiet_hours_enabled:
        return PreSendPolicy(
            allowed_send_start_hour=0,
            allowed_send_end_hour=24,
            timezone=timezone,
        )

    quiet_hours_start = workspace_contact_policy.quiet_hours_start
    quiet_hours_end = workspace_contact_policy.quiet_hours_end
    return PreSendPolicy(
        allowed_send_start_hour=quiet_hours_start.hour if quiet_hours_start else 10,
        allowed_send_end_hour=quiet_hours_end.hour if quiet_hours_end else 17,
        timezone=timezone,
    )


def _reason_values(reasons: tuple[StrEnum, ...]) -> str:
    return ", ".join(reason.value for reason in reasons)


def _reason_value_list(reasons: tuple[StrEnum, ...]) -> list[str]:
    return [reason.value for reason in reasons]


def _planning_block_metadata(
    *,
    cadence_step_id: UUID,
    plan_result: PlanOutboundMessageResult,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "cadence_step_id": str(cadence_step_id),
        "block_stage": "planning",
        "reason": _reason_values(plan_result.reasons),
        "reason_codes": _reason_value_list(plan_result.reasons),
    }
    if plan_result.selected_channel is not None:
        metadata["selected_channel"] = plan_result.selected_channel.value
    if plan_result.channel_evaluations:
        metadata["evaluated_channels"] = [
            evaluation.channel.value for evaluation in plan_result.channel_evaluations
        ]
        blocked_outcomes = [
            evaluation.outcome.value
            for evaluation in plan_result.channel_evaluations
            if evaluation.outcome.value != "selected"
        ]
        if blocked_outcomes:
            metadata["channel_block_outcomes"] = blocked_outcomes
    if plan_result.pre_send_decision is not None:
        metadata["pre_send_reasons"] = _reason_value_list(plan_result.pre_send_decision.reasons)
        if plan_result.pre_send_decision.next_allowed_at is not None:
            metadata["next_allowed_at"] = plan_result.pre_send_decision.next_allowed_at.isoformat()
    elif plan_result.channel_evaluations:
        pre_send_reasons = _planning_pre_send_reasons(plan_result.channel_evaluations)
        if pre_send_reasons:
            metadata["pre_send_reasons"] = pre_send_reasons
        next_allowed_at = _planning_next_allowed_at(plan_result.channel_evaluations)
        if next_allowed_at is not None:
            metadata["next_allowed_at"] = next_allowed_at.isoformat()
    if plan_result.draft_result is not None:
        metadata["draft_status"] = plan_result.draft_result.status.value
        metadata["draft_reasons"] = _reason_value_list(plan_result.draft_reasons)
        metadata["draft_safety_flags"] = list(plan_result.draft_result.safety_flags)
        if plan_result.draft_result.confidence is not None:
            metadata["draft_confidence"] = plan_result.draft_result.confidence
        if plan_result.draft_result.model is not None:
            metadata["draft_model"] = plan_result.draft_result.model
        metadata["draft_prompt_version"] = plan_result.draft_result.prompt_version
    metadata["explanation"] = _planning_block_explanation(plan_result)
    return _compact_metadata(metadata)


def _send_block_metadata(
    *,
    cadence_step_id: UUID,
    send_result: SendOutboundMessageResult,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "cadence_step_id": str(cadence_step_id),
        "block_stage": "sending",
        "reason": _reason_values(send_result.reasons),
        "reason_codes": _reason_value_list(send_result.reasons),
    }
    if send_result.message is not None:
        metadata["selected_channel"] = send_result.message.channel.value
        metadata["message_status"] = send_result.message.status.value
        metadata["provider_send_status"] = send_result.message.provider_send_status.value
    if send_result.pre_send_decision is not None:
        metadata["pre_send_reasons"] = _reason_value_list(send_result.pre_send_decision.reasons)
        if send_result.pre_send_decision.next_allowed_at is not None:
            metadata["next_allowed_at"] = send_result.pre_send_decision.next_allowed_at.isoformat()
    metadata["explanation"] = _send_block_explanation(send_result)
    return _compact_metadata(metadata)


def _planning_block_explanation(plan_result: PlanOutboundMessageResult) -> str:
    parts = [f"Planning blocked: {_humanized_reason_values(plan_result.reasons)}."]
    if plan_result.channel_evaluations:
        considered_channels = _humanized_strings(
            evaluation.channel.value for evaluation in plan_result.channel_evaluations
        )
        parts.append(f"Channels considered: {considered_channels}.")
    if plan_result.draft_reasons:
        parts.append(
            f"Draft validation failed: {_humanized_reason_values(plan_result.draft_reasons)}."
        )
    if plan_result.draft_result is not None and plan_result.draft_result.safety_flags:
        parts.append(f"Safety flags: {_humanized_strings(plan_result.draft_result.safety_flags)}.")
    planning_pre_send_reasons = (
        _reason_value_list(plan_result.pre_send_decision.reasons)
        if plan_result.pre_send_decision is not None
        else _planning_pre_send_reasons(plan_result.channel_evaluations)
    )
    if planning_pre_send_reasons:
        parts.append(
            f"Pre-send checks blocked the message: {_humanized_strings(planning_pre_send_reasons)}."
        )
    next_allowed_at = (
        plan_result.pre_send_decision.next_allowed_at
        if plan_result.pre_send_decision is not None
        else _planning_next_allowed_at(plan_result.channel_evaluations)
    )
    if next_allowed_at is not None:
        parts.append(f"Next eligible send time: {next_allowed_at.isoformat()}.")
    return " ".join(parts)


def _send_block_explanation(send_result: SendOutboundMessageResult) -> str:
    parts = [f"Sending blocked: {_humanized_reason_values(send_result.reasons)}."]
    if send_result.pre_send_decision is not None and send_result.pre_send_decision.reasons:
        parts.append(
            "Pre-send checks blocked delivery: "
            f"{_humanized_reason_values(send_result.pre_send_decision.reasons)}."
        )
    if send_result.pre_send_decision is not None and send_result.pre_send_decision.next_allowed_at:
        parts.append(
            f"Next eligible send time: {send_result.pre_send_decision.next_allowed_at.isoformat()}."
        )
    return " ".join(parts)


def _humanized_reason_values(reasons: tuple[StrEnum, ...]) -> str:
    return _humanized_strings(reason.value for reason in reasons)


def _planning_pre_send_reasons(channel_evaluations: tuple[ChannelEvaluation, ...]) -> list[str]:
    return list(
        dict.fromkeys(
            reason.value
            for evaluation in channel_evaluations
            for reason in evaluation.pre_send_reasons
        )
    )


def _planning_next_allowed_at(
    channel_evaluations: tuple[ChannelEvaluation, ...],
) -> datetime | None:
    for evaluation in channel_evaluations:
        if evaluation.next_allowed_at is not None:
            return evaluation.next_allowed_at
    return None


def _should_persist_rejected_draft_review(plan_result: PlanOutboundMessageResult) -> bool:
    return plan_result.draft_result is not None and any(
        reason.value == "draft_rejected" for reason in plan_result.reasons
    )


def _rejected_draft_review(
    *,
    workspace_id: WorkspaceId,
    workflow_id: UUID,
    transition_id: UUID,
    campaign_id: UUID,
    campaign_version_id: UUID,
    lead_id: LeadId,
    cadence_step_id: UUID,
    channel: ContactChannel,
    plan_result: PlanOutboundMessageResult,
    now: datetime,
) -> RejectedDraftReview:
    assert plan_result.draft_result is not None
    review_blockers = _review_blockers(plan_result)
    return RejectedDraftReview(
        review_id=uuid4(),
        workspace_id=workspace_id,
        lead_id=lead_id,
        workflow_id=workflow_id,
        workflow_transition_id=transition_id,
        campaign_id=campaign_id,
        campaign_version_id=campaign_version_id,
        cadence_step_id=cadence_step_id,
        channel=channel,
        status=RejectedDraftReviewStatus.PENDING_REVIEW,
        reason_codes=tuple(reason.value for reason in plan_result.reasons),
        draft_reason_codes=tuple(reason.value for reason in plan_result.draft_reasons),
        review_blockers=review_blockers,
        draft_safety_flags=tuple(plan_result.draft_result.safety_flags),
        draft_personalization_notes=tuple(plan_result.draft_result.personalization_notes),
        draft_body=plan_result.draft_result.body,
        draft_subject=plan_result.draft_result.subject,
        raw_llm_response_text=plan_result.draft_result.raw_llm_response_text,
        validation_error=plan_result.draft_result.validation_error,
        explanation=_planning_block_explanation(plan_result),
        draft_confidence=plan_result.draft_result.confidence,
        draft_model=plan_result.draft_result.model,
        draft_prompt_version=plan_result.draft_result.prompt_version,
        draft_latency_ms=plan_result.draft_result.latency_ms,
        draft_usage_tokens=plan_result.draft_result.usage_tokens,
        message_version=1,
        can_approve_send=not review_blockers,
        created_at=now,
        updated_at=now,
    )


def _review_blockers(plan_result: PlanOutboundMessageResult) -> tuple[str, ...]:
    blockers: list[str] = []
    draft_result = plan_result.draft_result
    if draft_result is None:
        blockers.append("missing_draft_result")
    else:
        if draft_result.body is None:
            blockers.append("missing_draft_body")
        if draft_result.reasons:
            blockers.extend(
                reason.value for reason in draft_result.reasons if reason.value != "low_confidence"
            )
        if draft_result.safety_flags:
            blockers.append("safety_flags_present")
    return tuple(dict.fromkeys(blockers))


def _humanized_strings(values: Iterable[str]) -> str:
    return ", ".join(str(value).replace("_", " ") for value in values)


def _compact_metadata(metadata: dict[str, object]) -> dict[str, object]:
    compacted: dict[str, object] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        if isinstance(value, (list, tuple)) and len(value) == 0:
            continue
        compacted[key] = value
    return compacted
