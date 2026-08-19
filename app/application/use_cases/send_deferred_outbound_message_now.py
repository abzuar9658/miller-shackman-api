from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.application.ports.crm import CRMClient
from app.application.ports.messaging import EmailProvider, SMSProvider
from app.application.ports.repositories import (
    CampaignAdminRepository,
    CampaignExecutionRepository,
    CRMAgentRepository,
    CrmConversationEventRepository,
    ExternalEventRepository,
    LeadRepository,
    LeadWorkflowRepository,
    OutboundMessageCRMCompletionRepository,
    OutboundMessageRepository,
    PausedSearchOccurrenceRepository,
    TemporalSignalOutboxRepository,
    UserRepository,
    WorkflowTransitionRepository,
    WorkspaceAgentCRMMappingRepository,
    WorkspaceAgentMappingConfigRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceMembershipRepository,
    WorkspaceOperationalControlRepository,
    WorkspaceRepository,
)
from app.application.services.internal_external_events import create_internal_external_event
from app.application.services.lead_nurture_rescheduling import (
    enqueue_lead_nurture_reschedule_signal,
)
from app.application.services.pre_send_crm_refresh import build_pre_send_crm_refresh_context
from app.application.services.pre_send_policy import build_pre_send_policy
from app.application.use_cases.campaign_cadence_execution import (
    _latest_inbound_conversation_text,
    _summary_text_for_outbound_conversation,
    advance_paused_search_workflow_after_outbound_send,
    advance_workflow_after_outbound_send,
    record_paused_search_occurrence_outcome,
)
from app.application.use_cases.complete_outbound_message_crm_sync import (
    complete_outbound_message_crm_sync,
)
from app.application.use_cases.lead_manual_enrollment import (
    active_published_campaign_version,
    manual_enrollment_permission_allowed,
)
from app.application.use_cases.send_outbound_message import (
    OutboundSendContext,
    SendOutboundMessageStatus,
    send_outbound_message,
)
from app.domain.campaigns.outbound_message import OutboundMessageStatus
from app.domain.campaigns.paused_search_occurrences import RecurringOccurrenceStatus
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.identity import AuthenticatedActor
from app.domain.workflows import WorkflowState


class SendDeferredMessageNowStatus(StrEnum):
    SENT = "sent"
    ALREADY_SENT = "already_sent"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"
    NOT_ACTIONABLE = "not_actionable"
    SEND_REJECTED = "send_rejected"
    SEND_FAILED = "send_failed"


@dataclass(frozen=True)
class SendDeferredMessageNowResult:
    status: SendDeferredMessageNowStatus
    outbound_message_id: UUID | None = None
    workflow_id: UUID | None = None
    reasons: tuple[str, ...] = ()
    signal_queued: bool = False



async def send_deferred_outbound_message_now(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    message_id: UUID,
    reason: str,
    lead_repository: LeadRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    message_repository: OutboundMessageRepository,
    campaign_admin_repository: CampaignAdminRepository,
    campaign_execution_repository: CampaignExecutionRepository,
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository,
    workspace_repository: WorkspaceRepository,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None,
    external_event_repository: ExternalEventRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    crm_conversation_event_repository: CrmConversationEventRepository | None = None,
    crm_client: CRMClient | None = None,
    crm_agent_repository: CRMAgentRepository | None = None,
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository | None = None,
    workspace_agent_mapping_config_repository: WorkspaceAgentMappingConfigRepository | None = None,
    workspace_membership_repository: WorkspaceMembershipRepository | None = None,
    user_repository: UserRepository | None = None,
    outbound_message_crm_completion_repository: (
        OutboundMessageCRMCompletionRepository | None
    ) = None,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None = None,
    commit: Callable[[], Awaitable[None]],
    sms_provider: SMSProvider,
    email_provider: EmailProvider,
    now: datetime,
) -> SendDeferredMessageNowResult:
    normalized_reason = reason.strip()
    if not normalized_reason:
        return SendDeferredMessageNowResult(
            status=SendDeferredMessageNowStatus.REJECTED,
            reasons=("reason_required",),
        )

    lead = await lead_repository.get_by_id_for_update(workspace_id, lead_id)
    if lead is None:
        return SendDeferredMessageNowResult(status=SendDeferredMessageNowStatus.NOT_FOUND)

    message = await message_repository.get_by_id_for_update(workspace_id, message_id)
    if message is None or message.lead_id != lead_id:
        return SendDeferredMessageNowResult(status=SendDeferredMessageNowStatus.NOT_FOUND)

    campaign = await campaign_admin_repository.get_campaign(workspace_id, message.campaign_id)
    version = await active_published_campaign_version(
        campaign_admin_repository, workspace_id, campaign
    )
    if campaign is None or version is None:
        return SendDeferredMessageNowResult(
            status=SendDeferredMessageNowStatus.NOT_ACTIONABLE,
            outbound_message_id=message.message_id,
            reasons=("missing_execution_context",),
        )
    if not manual_enrollment_permission_allowed(
        actor,
        lead,
        campaign_allows_assigned_agent_enrollment=version.allow_assigned_agent_manual_enrollment,
    ):
        return SendDeferredMessageNowResult(
            status=SendDeferredMessageNowStatus.REJECTED,
            outbound_message_id=message.message_id,
            reasons=("permission_denied",),
        )

    if message.status == OutboundMessageStatus.SENT:
        return SendDeferredMessageNowResult(
            status=SendDeferredMessageNowStatus.ALREADY_SENT,
            outbound_message_id=message.message_id,
            workflow_id=message.workflow_id,
        )
    if message.status != OutboundMessageStatus.PENDING:
        return SendDeferredMessageNowResult(
            status=SendDeferredMessageNowStatus.NOT_ACTIONABLE,
            outbound_message_id=message.message_id,
            reasons=("message_not_pending",),
        )
    if message.status_detail is None:
        return SendDeferredMessageNowResult(
            status=SendDeferredMessageNowStatus.NOT_ACTIONABLE,
            outbound_message_id=message.message_id,
            reasons=("message_not_deferred",),
        )
    if message.workflow_id is None:
        return SendDeferredMessageNowResult(
            status=SendDeferredMessageNowStatus.NOT_ACTIONABLE,
            outbound_message_id=message.message_id,
            reasons=("workflow_mismatch",),
        )

    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(
        workspace_id,
        lead_id,
    )
    if workflow is None or workflow.workflow_id != message.workflow_id:
        return SendDeferredMessageNowResult(
            status=SendDeferredMessageNowStatus.NOT_ACTIONABLE,
            outbound_message_id=message.message_id,
            reasons=("workflow_mismatch",),
        )
    if workflow.state != WorkflowState.ACTIVE_NURTURE:
        return SendDeferredMessageNowResult(
            status=SendDeferredMessageNowStatus.NOT_ACTIONABLE,
            outbound_message_id=message.message_id,
            workflow_id=workflow.workflow_id,
            reasons=("workflow_not_active",),
        )
    is_paused_search_step = workflow.paused_search_track_version_id is not None
    parked_step_id = (
        workflow.paused_search_track_step_id if is_paused_search_step else workflow.current_step_id
    )
    if parked_step_id is None or str(parked_step_id) != message.cadence_step_id:
        return SendDeferredMessageNowResult(
            status=SendDeferredMessageNowStatus.NOT_ACTIONABLE,
            outbound_message_id=message.message_id,
            workflow_id=workflow.workflow_id,
            reasons=("step_mismatch",),
        )

    config = await campaign_execution_repository.get_active_for_campaign(
        workspace_id,
        message.campaign_id,
    )
    workspace = await workspace_repository.get_by_id(workspace_id)
    workspace_contact_policy = await workspace_contact_policy_repository.get_by_workspace_id(
        workspace_id
    )
    if config is None or workspace is None or workspace_contact_policy is None:
        return SendDeferredMessageNowResult(
            status=SendDeferredMessageNowStatus.NOT_ACTIONABLE,
            outbound_message_id=message.message_id,
            workflow_id=workflow.workflow_id,
            reasons=("missing_execution_context",),
        )

    send_result = await send_outbound_message(
        workspace_id=workspace_id,
        idempotency_key=message.idempotency_key,
        context=OutboundSendContext(
            campaign_status=config.campaign_status,
            workflow_state=WorkflowState.ACTIVE_NURTURE,
            enabled_channels=(message.channel,),
            workspace_contact_policy=workspace_contact_policy,
            current_message_version=message.message_version,
            pre_send_policy=build_pre_send_policy(
                workspace_contact_policy,
                workspace.default_timezone,
            ),
        ),
        lead_repository=lead_repository,
        message_repository=message_repository,
        sms_provider=sms_provider,
        email_provider=email_provider,
        workspace_operational_control_repository=workspace_operational_control_repository,
        crm_refresh_context=build_pre_send_crm_refresh_context(
            crm_client=crm_client,
            crm_agent_repository=crm_agent_repository,
            workspace_agent_crm_mapping_repository=workspace_agent_crm_mapping_repository,
            workspace_agent_mapping_config_repository=workspace_agent_mapping_config_repository,
            workspace_membership_repository=workspace_membership_repository,
            user_repository=user_repository,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        ),
        now=now,
        confirmed_frequency_limit_override=True,
    )
    if send_result.status == SendOutboundMessageStatus.REJECTED:
        pre_send_reasons = (
            tuple(reason_code.value for reason_code in send_result.pre_send_decision.reasons)
            if send_result.pre_send_decision is not None
            else ()
        )
        return SendDeferredMessageNowResult(
            status=SendDeferredMessageNowStatus.SEND_REJECTED,
            outbound_message_id=message.message_id,
            workflow_id=workflow.workflow_id,
            reasons=tuple(reason.value for reason in send_result.reasons) + pre_send_reasons,
        )
    if send_result.status not in {
        SendOutboundMessageStatus.SENT,
        SendOutboundMessageStatus.ALREADY_SENT,
    }:
        return SendDeferredMessageNowResult(
            status=SendDeferredMessageNowStatus.SEND_FAILED,
            outbound_message_id=message.message_id,
            workflow_id=workflow.workflow_id,
            reasons=tuple(reason.value for reason in send_result.reasons),
        )

    if (
        send_result.message is not None
        and crm_client is not None
        and outbound_message_crm_completion_repository is not None
    ):
        handoff_config = (
            await workspace_handoff_config_repository.get_by_workspace_id(workspace_id)
            if workspace_handoff_config_repository is not None
            else None
        )
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

    cadence_step_uuid = UUID(message.cadence_step_id)
    if is_paused_search_step and workflow.paused_search_track_version_id is not None:
        occurrence = await paused_search_occurrence_repository.get_latest_for_step(
            workspace_id,
            workflow.workflow_id,
            workflow.paused_search_track_version_id,
            cadence_step_uuid,
        )
        if occurrence is not None and occurrence.status in {
            RecurringOccurrenceStatus.PLANNED,
            RecurringOccurrenceStatus.DEFERRED,
        }:
            # Close the deferred occurrence as sent so the scheduled retry does
            # not re-execute a step whose message already went out.
            workflow = await record_paused_search_occurrence_outcome(
                workspace_id=workspace_id,
                workflow=workflow,
                occurrence=occurrence,
                authored_channel=message.channel,
                send_result=send_result,
                occurrence_repository=paused_search_occurrence_repository,
                lead_workflow_repository=lead_workflow_repository,
                now=now,
            )
        advance_result = await advance_paused_search_workflow_after_outbound_send(
            workspace_id=workspace_id,
            lead_id=lead_id,
            workflow=workflow,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            cadence_steps=config.cadence_steps,
            cadence_step_id=cadence_step_uuid,
            send_result=send_result,
            now=now,
        )
    else:
        advance_result = await advance_workflow_after_outbound_send(
            workspace_id=workspace_id,
            lead_id=lead_id,
            workflow=workflow,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            cadence_steps=config.cadence_steps,
            cadence_step_id=cadence_step_uuid,
            send_result=send_result,
            now=now,
        )

    external_event = await create_internal_external_event(
        external_event_repository=external_event_repository,
        workspace_id=workspace_id,
        lead_id=lead_id,
        event_type="lead.deferred_outbound_message_send_now_confirmed",
        now=now,
        payload_redacted={
            "actor_user_id": str(actor.user_id),
            "outbound_message_id": str(message.message_id),
            "reason": normalized_reason,
        },
    )
    signal_queued = await enqueue_lead_nurture_reschedule_signal(
        workspace_id=workspace_id,
        lead_id=lead_id,
        reason="deferred_message_sent_now",
        occurred_at=now,
        lead_workflow_repository=lead_workflow_repository,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        actor_user_id=actor.user_id,
        external_event_id=external_event.external_event_id,
    )
    await commit()
    return SendDeferredMessageNowResult(
        status=(
            SendDeferredMessageNowStatus.SENT
            if send_result.status == SendOutboundMessageStatus.SENT
            else SendDeferredMessageNowStatus.ALREADY_SENT
        ),
        outbound_message_id=message.message_id,
        workflow_id=(
            advance_result.workflow.workflow_id
            if advance_result.workflow is not None
            else workflow.workflow_id
        ),
        signal_queued=signal_queued,
    )
