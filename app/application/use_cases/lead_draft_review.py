from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4

from app.application.ports.crm import CRMClient
from app.application.ports.crm_sync import CanonicalLeadRefreshSource
from app.application.ports.messaging import EmailProvider, SMSProvider
from app.application.ports.rejected_draft_review import RejectedDraftReviewRepository
from app.application.ports.repositories import (
    CampaignExecutionRepository,
    CRMAgentRepository,
    CrmConversationEventRepository,
    ExternalEventRepository,
    LeadRepository,
    LeadWorkflowRepository,
    OutboundMessageCRMCompletionRepository,
    OutboundMessageRepository,
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
from app.application.use_cases.campaign_cadence_execution import (
    _latest_inbound_conversation_text,
    _pre_send_policy,
    _summary_text_for_outbound_conversation,
    advance_workflow_after_outbound_send,
)
from app.application.use_cases.complete_outbound_message_crm_sync import (
    complete_outbound_message_crm_sync,
)
from app.application.use_cases.lead_resume import _resume_permission
from app.application.use_cases.plan_outbound_message import _outbound_idempotency_key
from app.application.use_cases.send_outbound_message import (
    OutboundSendContext,
    PreSendCRMRefreshContext,
    SendOutboundMessageStatus,
    send_outbound_message,
)
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.pre_send import ProviderSendStatus, WorkflowState
from app.domain.campaigns.rejected_draft_review import RejectedDraftReviewStatus
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.identity import AuthenticatedActor
from app.domain.workflows import TemporalSignalName, TemporalSignalOutboxEntry


class ApproveRejectedDraftReviewStatus(StrEnum):
    SENT = "sent"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"
    NOT_APPROVABLE = "not_approvable"
    NOT_ACTIONABLE = "not_actionable"
    SEND_REJECTED = "send_rejected"
    SEND_FAILED = "send_failed"


@dataclass(frozen=True)
class ApproveRejectedDraftReviewResult:
    status: ApproveRejectedDraftReviewStatus
    review_id: UUID | None = None
    outbound_message_id: UUID | None = None
    workflow_id: UUID | None = None
    reasons: tuple[str, ...] = ()
    signal_queued: bool = False


async def approve_rejected_draft_review_and_send(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    review_id: UUID,
    reason: str,
    lead_repository: LeadRepository,
    review_repository: RejectedDraftReviewRepository,
    workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    campaign_execution_repository: CampaignExecutionRepository,
    workspace_repository: WorkspaceRepository,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None,
    message_repository: OutboundMessageRepository,
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
) -> ApproveRejectedDraftReviewResult:
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return ApproveRejectedDraftReviewResult(status=ApproveRejectedDraftReviewStatus.NOT_FOUND)
    if not _resume_permission(actor, lead, resume_reason_provided=bool(reason.strip())).allowed:
        return ApproveRejectedDraftReviewResult(
            status=ApproveRejectedDraftReviewStatus.REJECTED,
            reasons=("permission_denied",),
        )

    review = await review_repository.get_by_id_for_update(workspace_id, review_id)
    if review is None or review.lead_id != lead_id:
        return ApproveRejectedDraftReviewResult(status=ApproveRejectedDraftReviewStatus.NOT_FOUND)
    if review.status != RejectedDraftReviewStatus.PENDING_REVIEW:
        return ApproveRejectedDraftReviewResult(
            status=ApproveRejectedDraftReviewStatus.NOT_ACTIONABLE,
            review_id=review.review_id,
            reasons=("review_not_pending",),
        )
    if not review.can_approve_send or review.draft_body is None:
        return ApproveRejectedDraftReviewResult(
            status=ApproveRejectedDraftReviewStatus.NOT_APPROVABLE,
            review_id=review.review_id,
            reasons=review.review_blockers,
        )

    workflow = await workflow_repository.get_latest_for_lead_for_update(
        workspace_id,
        lead_id,
    )
    if (
        workflow is None
        or workflow.workflow_id != review.workflow_id
        or workflow.state != WorkflowState.PAUSED
    ):
        return ApproveRejectedDraftReviewResult(
            status=ApproveRejectedDraftReviewStatus.NOT_ACTIONABLE,
            review_id=review.review_id,
            reasons=("workflow_not_paused_for_review",),
        )
    config = await campaign_execution_repository.get_by_version_id(
        workspace_id,
        review.campaign_version_id,
    )
    workspace = await workspace_repository.get_by_id(workspace_id)
    if config is None or workspace is None:
        return ApproveRejectedDraftReviewResult(
            status=ApproveRejectedDraftReviewStatus.NOT_ACTIONABLE,
            review_id=review.review_id,
            reasons=("missing_execution_context",),
        )
    workspace_contact_policy = await workspace_contact_policy_repository.get_by_workspace_id(
        workspace_id
    )
    if workspace_contact_policy is None:
        return ApproveRejectedDraftReviewResult(
            status=ApproveRejectedDraftReviewStatus.NOT_ACTIONABLE,
            review_id=review.review_id,
            reasons=("missing_workspace_contact_policy",),
        )

    message = await message_repository.save(
        OutboundMessage(
            message_id=uuid4(),
            workspace_id=workspace_id,
            lead_id=lead_id,
            campaign_id=review.campaign_id,
            cadence_step_id=str(review.cadence_step_id),
            channel=review.channel,
            status=OutboundMessageStatus.PENDING,
            idempotency_key=_outbound_idempotency_key(
                workspace_id=workspace_id,
                campaign_id=review.campaign_id,
                lead_id=lead_id,
                cadence_step_id=str(review.cadence_step_id),
                channel=review.channel,
                message_version=review.message_version,
            ),
            body=review.draft_body,
            subject=review.draft_subject,
            planned_at=now,
            created_at=now,
            updated_at=now,
            message_version=review.message_version,
            draft_prompt_version=review.draft_prompt_version,
            draft_model=review.draft_model,
            draft_latency_ms=review.draft_latency_ms,
            draft_usage_tokens=review.draft_usage_tokens,
            draft_confidence=review.draft_confidence,
            draft_personalization_notes=review.draft_personalization_notes,
            draft_safety_flags=review.draft_safety_flags,
            provider_send_status=ProviderSendStatus.NOT_ATTEMPTED,
        )
    )
    send_result = await send_outbound_message(
        workspace_id=workspace_id,
        idempotency_key=message.idempotency_key,
        context=OutboundSendContext(
            campaign_status=config.campaign_status,
            workflow_state=WorkflowState.ACTIVE_NURTURE,
            enabled_channels=(review.channel,),
            workspace_contact_policy=workspace_contact_policy,
            current_message_version=message.message_version,
            pre_send_policy=_pre_send_policy(workspace_contact_policy, workspace.default_timezone),
        ),
        lead_repository=lead_repository,
        message_repository=message_repository,
        sms_provider=sms_provider,
        email_provider=email_provider,
        workspace_operational_control_repository=workspace_operational_control_repository,
        crm_refresh_context=_pre_send_crm_refresh_context(
            crm_client=crm_client,
            crm_agent_repository=crm_agent_repository,
            workspace_agent_crm_mapping_repository=workspace_agent_crm_mapping_repository,
            workspace_agent_mapping_config_repository=workspace_agent_mapping_config_repository,
            workspace_membership_repository=workspace_membership_repository,
            user_repository=user_repository,
            workflow_repository=workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        ),
        now=now,
    )
    if send_result.status not in {
        SendOutboundMessageStatus.SENT,
        SendOutboundMessageStatus.ALREADY_SENT,
    }:
        return ApproveRejectedDraftReviewResult(
            status=(
                ApproveRejectedDraftReviewStatus.SEND_REJECTED
                if send_result.status == SendOutboundMessageStatus.REJECTED
                else ApproveRejectedDraftReviewStatus.SEND_FAILED
            ),
            review_id=review.review_id,
            outbound_message_id=send_result.message.message_id if send_result.message else None,
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

    workflow_result = await advance_workflow_after_outbound_send(
        workspace_id=workspace_id,
        lead_id=lead_id,
        workflow=workflow,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        cadence_steps=config.cadence_steps,
        cadence_step_id=review.cadence_step_id,
        send_result=send_result,
        now=now,
    )
    await review_repository.save(
        replace(
            review,
            status=RejectedDraftReviewStatus.APPROVED_SENT,
            reviewed_by_user_id=actor.user_id,
            reviewed_at=now,
            review_note=reason.strip(),
            outbound_message_id=send_result.message.message_id if send_result.message else None,
            updated_at=now,
        )
    )
    external_event = await create_internal_external_event(
        external_event_repository=external_event_repository,
        workspace_id=workspace_id,
        lead_id=lead_id,
        event_type="lead.rejected_draft_review_unblock_requested",
        now=now,
        payload_redacted={"actor_user_id": str(actor.user_id), "review_id": str(review.review_id)},
    )
    await temporal_signal_outbox_repository.append(
        TemporalSignalOutboxEntry(
            temporal_signal_id=uuid4(),
            workspace_id=workspace_id,
            workflow_id=workflow.workflow_id,
            temporal_workflow_id=workflow.temporal_workflow_id,
            signal_name=TemporalSignalName.BLOCKED_REVIEW_COMPLETED,
            payload={
                "lead_id": str(lead_id),
                "occurred_at": now.isoformat(),
                "reason": reason.strip(),
                "actor_user_id": str(actor.user_id),
                "external_event_id": str(external_event.external_event_id),
            },
            idempotency_key=f"blocked-review-completed:{external_event.external_event_id}",
            available_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    await commit()
    return ApproveRejectedDraftReviewResult(
        status=ApproveRejectedDraftReviewStatus.SENT,
        review_id=review.review_id,
        outbound_message_id=send_result.message.message_id if send_result.message else None,
        workflow_id=(
            workflow_result.workflow.workflow_id
            if workflow_result.workflow
            else workflow.workflow_id
        ),
        signal_queued=True,
    )


def _pre_send_crm_refresh_context(
    *,
    crm_client: CRMClient | None,
    crm_agent_repository: CRMAgentRepository | None,
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository | None,
    workspace_agent_mapping_config_repository: WorkspaceAgentMappingConfigRepository | None,
    workspace_membership_repository: WorkspaceMembershipRepository | None,
    user_repository: UserRepository | None,
    workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
) -> PreSendCRMRefreshContext | None:
    if not all(
        dependency is not None
        for dependency in (
            crm_client,
            crm_agent_repository,
            workspace_agent_crm_mapping_repository,
            workspace_agent_mapping_config_repository,
            workspace_membership_repository,
            user_repository,
        )
    ):
        return None
    assert crm_client is not None
    assert crm_agent_repository is not None
    assert workspace_agent_crm_mapping_repository is not None
    assert workspace_agent_mapping_config_repository is not None
    assert workspace_membership_repository is not None
    assert user_repository is not None
    return PreSendCRMRefreshContext(
        lead_refresh_source=cast(CanonicalLeadRefreshSource, crm_client),
        crm_activity_source=crm_client,
        crm_agent_repository=crm_agent_repository,
        workspace_agent_crm_mapping_repository=workspace_agent_crm_mapping_repository,
        workspace_agent_mapping_config_repository=workspace_agent_mapping_config_repository,
        workspace_membership_repository=workspace_membership_repository,
        user_repository=user_repository,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
    )
