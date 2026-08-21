from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from app.application.ports.messaging import EmailMessage, SMSMessage
from app.application.ports.repositories import (
    CampaignExecutionRepository,
    InboundMessageRepository,
    LeadRepository,
    LeadWorkflowRepository,
    OutboundMessageRepository,
    OutboundSendReconciliationRepository,
    OutboundSendRequestRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceOperationalControlRepository,
    WorkspaceRepository,
)
from app.application.services.canonical_lead_inputs import contactability_facts_from_canonical_lead
from app.application.services.pre_send_facts import load_pre_send_history_facts
from app.application.services.pre_send_policy import build_pre_send_policy
from app.application.services.workspace_automation_control import workspace_automation_is_active
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.outbound_send_reconciliation import (
    OutboundSendReconciliation,
    OutboundSendReconciliationStatus,
)
from app.domain.campaigns.outbound_send_request import (
    OutboundSendRequest,
    OutboundSendRequestStatus,
)
from app.domain.campaigns.pre_send import (
    PreSendDecision,
    PreSendFacts,
    ScheduledMessageStatus,
    evaluate_pre_send_safety,
)
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.compliance.contactability import ContactChannel, evaluate_contactability
from app.domain.identity import WorkspaceStatus
from app.domain.leads import CanonicalLeadRecord
from app.domain.workflows import LeadWorkflow, WorkflowState


class LockingOutboundMessageRepository(OutboundMessageRepository, Protocol):
    async def get_by_id_for_update(
        self,
        workspace_id: UUID,
        message_id: UUID,
    ) -> OutboundMessage | None:
        raise NotImplementedError


class LockingOutboundSendRequestRepository(OutboundSendRequestRepository, Protocol):
    async def get_by_id_for_update(
        self,
        workspace_id: UUID,
        request_id: UUID,
    ) -> OutboundSendRequest | None:
        raise NotImplementedError


class OutboundSendRevalidationReason(StrEnum):
    LEAD_NOT_FOUND = "lead_not_found"
    WORKFLOW_NOT_FOUND = "workflow_not_found"
    WORKFLOW_MISMATCH = "workflow_mismatch"
    MESSAGE_NOT_FOUND = "message_not_found"
    MESSAGE_NOT_PENDING = "message_not_pending"
    REQUEST_NOT_FOUND = "request_not_found"
    REQUEST_NOT_DISPATCHING = "request_not_dispatching"
    REQUEST_CHANGED_AFTER_CLAIM = "request_changed_after_claim"
    RECONCILIATION_NOT_PENDING = "reconciliation_not_pending"
    WORKSPACE_NOT_ACTIVE = "workspace_not_active"
    WORKSPACE_CONTROL_UNAVAILABLE = "workspace_control_unavailable"
    WORKSPACE_AUTOMATION_BLOCKED = "workspace_automation_blocked"
    CONTACT_POLICY_UNAVAILABLE = "contact_policy_unavailable"
    CAMPAIGN_NOT_ACTIVE = "campaign_not_active"
    CADENCE_STEP_MISMATCH = "cadence_step_mismatch"
    DURABLE_PAYLOAD_MISMATCH = "durable_payload_mismatch"
    PRE_SEND_BLOCKED = "pre_send_blocked"


@dataclass(frozen=True)
class OutboundSendRevalidationResult:
    allowed: bool
    request: OutboundSendRequest
    message: OutboundMessage | None = None
    reasons: tuple[OutboundSendRevalidationReason, ...] = ()
    pre_send_decision: PreSendDecision | None = None

    @property
    def failure_reason(self) -> str:
        reasons = [reason.value for reason in self.reasons]
        if self.pre_send_decision is not None:
            reasons.extend(reason.value for reason in self.pre_send_decision.reasons)
        return "pre_provider_policy_rejected:" + ",".join(reasons)


async def revalidate_outbound_send_request(
    *,
    request: OutboundSendRequest,
    lead_repository: LeadRepository,
    workflow_repository: LeadWorkflowRepository,
    message_repository: LockingOutboundMessageRepository,
    request_repository: LockingOutboundSendRequestRepository,
    reconciliation_repository: OutboundSendReconciliationRepository,
    campaign_repository: CampaignExecutionRepository,
    workspace_repository: WorkspaceRepository,
    workspace_control_repository: WorkspaceOperationalControlRepository,
    contact_policy_repository: WorkspaceContactPolicyRepository,
    inbound_message_repository: InboundMessageRepository,
    now: datetime,
    recent_human_activity: bool = False,
) -> OutboundSendRevalidationResult:
    # The worker performs its live CRM refresh before entering this lock-holding final check.
    # The locks guarantee the verdict is computed on a consistent snapshot; the
    # dispatcher commits (releasing them) before the external provider call and
    # relies on the durable DISPATCHING claim to prevent double-dispatch.
    lead = await lead_repository.get_by_id_for_update(request.workspace_id, request.lead_id)
    if lead is None:
        return _blocked(request, OutboundSendRevalidationReason.LEAD_NOT_FOUND)

    workflow = await workflow_repository.get_latest_for_lead_for_update(
        request.workspace_id,
        request.lead_id,
    )
    if workflow is None:
        return _blocked(request, OutboundSendRevalidationReason.WORKFLOW_NOT_FOUND)

    message = await message_repository.get_by_id_for_update(
        request.workspace_id,
        request.outbound_message_id,
    )
    current_request = await request_repository.get_by_id_for_update(
        request.workspace_id,
        request.request_id,
    )
    reconciliation = await reconciliation_repository.get_by_id_for_update(
        request.workspace_id,
        request.reconciliation_id,
    )

    if message is None:
        return _blocked(
            current_request or request,
            OutboundSendRevalidationReason.MESSAGE_NOT_FOUND,
        )
    if current_request is None:
        return _blocked(request, OutboundSendRevalidationReason.REQUEST_NOT_FOUND, message)
    if current_request.status is not OutboundSendRequestStatus.DISPATCHING:
        return _blocked(
            current_request,
            OutboundSendRevalidationReason.REQUEST_NOT_DISPATCHING,
            message,
        )
    if current_request != request:
        return _blocked(
            current_request,
            OutboundSendRevalidationReason.REQUEST_CHANGED_AFTER_CLAIM,
            message,
        )
    if message.status is not OutboundMessageStatus.PENDING:
        return _blocked(
            current_request,
            OutboundSendRevalidationReason.MESSAGE_NOT_PENDING,
            message,
        )
    if not _workflow_matches(current_request, message, workflow):
        return _blocked(current_request, OutboundSendRevalidationReason.WORKFLOW_MISMATCH, message)
    if not _reconciliation_matches(current_request, message, reconciliation):
        return _blocked(
            current_request,
            OutboundSendRevalidationReason.RECONCILIATION_NOT_PENDING,
            message,
        )

    workspace = await workspace_repository.get_by_id(request.workspace_id)
    if workspace is None or workspace.status is not WorkspaceStatus.ACTIVE:
        return _blocked(
            current_request,
            OutboundSendRevalidationReason.WORKSPACE_NOT_ACTIVE,
            message,
        )
    control = await workspace_control_repository.get_by_workspace_id(request.workspace_id)
    if control is None:
        return _blocked(
            current_request,
            OutboundSendRevalidationReason.WORKSPACE_CONTROL_UNAVAILABLE,
            message,
        )
    if not workspace_automation_is_active(control):
        return _blocked(
            current_request,
            OutboundSendRevalidationReason.WORKSPACE_AUTOMATION_BLOCKED,
            message,
        )
    contact_policy = await contact_policy_repository.get_by_workspace_id(request.workspace_id)
    if contact_policy is None:
        return _blocked(
            current_request,
            OutboundSendRevalidationReason.CONTACT_POLICY_UNAVAILABLE,
            message,
        )
    campaign = await campaign_repository.get_active_for_campaign(
        request.workspace_id,
        message.campaign_id,
    )
    if (
        campaign is None
        or campaign.campaign_status is not CampaignStatus.ACTIVE
        or campaign.version_status is not CampaignVersionStatus.PUBLISHED
    ):
        return _blocked(
            current_request,
            OutboundSendRevalidationReason.CAMPAIGN_NOT_ACTIVE,
            message,
        )

    step = next(
        (
            item
            for item in campaign.cadence_steps
            if str(item.cadence_step_id) == message.cadence_step_id
        ),
        None,
    )
    if step is None or step.channel is not message.channel:
        return _blocked(
            current_request,
            OutboundSendRevalidationReason.CADENCE_STEP_MISMATCH,
            message,
        )
    if not _payload_matches(current_request, message, lead):
        return _blocked(
            current_request,
            OutboundSendRevalidationReason.DURABLE_PAYLOAD_MISMATCH,
            message,
        )

    history = await load_pre_send_history_facts(
        workspace_id=request.workspace_id,
        lead_id=request.lead_id,
        message=message,
        message_repository=message_repository,
        inbound_message_repository=inbound_message_repository,
    )
    contactability = evaluate_contactability(
        contactability_facts_from_canonical_lead(lead),
        message.channel,
        require_explicit_automated_permission=message.channel is ContactChannel.SMS,
    )
    policy = build_pre_send_policy(contact_policy, workspace.default_timezone)
    pre_send_decision = evaluate_pre_send_safety(
        PreSendFacts(
            channel=message.channel,
            campaign_status=campaign.campaign_status,
            workflow_state=workflow.state,
            message_status=ScheduledMessageStatus.PENDING,
            provider_send_status=message.provider_send_status,
            scheduled_message_version=message.message_version,
            current_message_version=message.message_version,
            channel_enabled=message.channel in campaign.enabled_channels,
            contactability_decision=contactability,
            handoff_active=workflow.state is WorkflowState.HUMAN_HANDOFF,
            human_owned=workflow.state is WorkflowState.HUMAN_OWNED,
            lead_replied_since_scheduled=(
                history.lead_replied_since_scheduled if history is not None else False
            ),
            recent_human_activity=(
                recent_human_activity
                or _recent_human_activity(lead.last_agent_activity_at, message)
            ),
            other_channel_sent_at=history.other_channel_sent_at if history else None,
            history_facts_available=history is not None,
        ),
        policy,
        now,
    )
    if not pre_send_decision.allowed:
        return OutboundSendRevalidationResult(
            allowed=False,
            request=current_request,
            message=message,
            reasons=(OutboundSendRevalidationReason.PRE_SEND_BLOCKED,),
            pre_send_decision=pre_send_decision,
        )
    return OutboundSendRevalidationResult(
        allowed=True,
        request=current_request,
        message=message,
        pre_send_decision=pre_send_decision,
    )


def _blocked(
    request: OutboundSendRequest,
    reason: OutboundSendRevalidationReason,
    message: OutboundMessage | None = None,
) -> OutboundSendRevalidationResult:
    return OutboundSendRevalidationResult(
        allowed=False,
        request=request,
        message=message,
        reasons=(reason,),
    )


def _workflow_matches(
    request: OutboundSendRequest,
    message: OutboundMessage,
    workflow: LeadWorkflow,
) -> bool:
    return (
        workflow.workflow_id == request.workflow_id
        and workflow.temporal_workflow_id == request.temporal_workflow_id
        and workflow.workspace_id == request.workspace_id
        and workflow.lead_id == request.lead_id == message.lead_id
        and workflow.campaign_id == message.campaign_id
    )


def _reconciliation_matches(
    request: OutboundSendRequest,
    message: OutboundMessage,
    reconciliation: OutboundSendReconciliation | None,
) -> bool:
    return (
        reconciliation is not None
        and reconciliation.status is OutboundSendReconciliationStatus.PENDING
        and reconciliation.outbound_message_id == message.message_id
        and reconciliation.workflow_id == request.workflow_id
        and reconciliation.idempotency_key == request.idempotency_key
        and reconciliation.provider_name == request.provider_name
    )


def _payload_matches(
    request: OutboundSendRequest,
    message: OutboundMessage,
    lead: CanonicalLeadRecord,
) -> bool:
    if (
        request.outbound_message_id != message.message_id
        or request.lead_id != message.lead_id
        or request.channel is not message.channel
        or request.idempotency_key != message.idempotency_key
    ):
        return False
    try:
        if request.channel is ContactChannel.SMS:
            sms_payload = SMSMessage.model_validate(request.provider_payload)
            return (
                lead.has_sms_capable_phone
                and sms_payload.to_phone == lead.primary_phone
                and sms_payload.body == message.body
                and sms_payload.idempotency_key == message.idempotency_key
            )
        email_payload = EmailMessage.model_validate(request.provider_payload)
        return (
            lead.has_email
            and email_payload.to_email == lead.primary_email
            and email_payload.subject == message.subject
            and email_payload.body == message.body
            and email_payload.html_body == message.html_body
            and email_payload.idempotency_key == message.idempotency_key
        )
    except ValidationError:
        return False


def _recent_human_activity(
    last_agent_activity_at: datetime | None,
    message: OutboundMessage,
) -> bool:
    comparison_time = message.scheduled_for or message.planned_at or message.created_at
    return last_agent_activity_at is not None and last_agent_activity_at > comparison_time