from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.repositories import (
    ExternalEventRepository,
    LeadRepository,
    LeadWorkflowRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
)
from app.application.ports.temporal import (
    LeadNurtureWorkflowSignaler,
    PauseLeadNurtureWorkflowSignal,
)
from app.application.services.canonical_lead_inputs import (
    contactability_facts_from_canonical_lead,
)
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionStatus,
    apply_workflow_state_transition,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance import (
    ContactChannel,
    ContactSuppressionKind,
    SuppressionType,
    WorkspaceContactPolicy,
    default_workspace_contact_policy,
    evaluate_contactability,
)
from app.domain.crm_sync import ExternalEvent, ExternalEventStatus
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import WorkflowState, WorkflowTransitionReasonCode


class ProcessContactSuppressionEventStatus(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"


class ProcessContactSuppressionEventReasonCode(StrEnum):
    DUPLICATE_EVENT = "duplicate_event"
    LEAD_NOT_FOUND = "lead_not_found"
    NO_WORKFLOW = "no_workflow"
    TRANSITION_SKIPPED = "transition_skipped"
    SIGNAL_DISPATCH_FAILED = "signal_dispatch_failed"


def _empty_payload() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True)
class ContactSuppressionEvent:
    workspace_id: WorkspaceId
    source_provider: str
    provider_event_id: str
    crm_provider: CRMProvider
    crm_lead_id: str
    suppression_kind: ContactSuppressionKind
    occurred_at: datetime
    provider_message_id: str | None = None
    payload_redacted: Mapping[str, object] = field(default_factory=_empty_payload)


@dataclass(frozen=True)
class ProcessContactSuppressionEventResult:
    status: ProcessContactSuppressionEventStatus
    external_event_id: UUID | None = None
    lead_id: LeadId | None = None
    workflow_id: UUID | None = None
    workflow_transition_id: UUID | None = None
    suppression_kind: ContactSuppressionKind | None = None
    workflow_state: WorkflowState | None = None
    suppression_applied: bool = False
    signal_sent: bool = False
    signal_failure_reason: str | None = None
    transition_skip_reason: str | None = None
    reasons: tuple[ProcessContactSuppressionEventReasonCode, ...] = ()


async def process_contact_suppression_event(
    *,
    event: ContactSuppressionEvent,
    lead_repository: LeadRepository,
    external_event_repository: ExternalEventRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository,
    lead_nurture_workflow_signaler: LeadNurtureWorkflowSignaler,
    now: datetime,
    external_event_id_factory: Callable[[], UUID] | None = None,
) -> ProcessContactSuppressionEventResult:
    existing = await external_event_repository.get_by_provider_event_id(
        event.workspace_id,
        event.source_provider,
        event.provider_event_id,
    )
    if existing is not None:
        return ProcessContactSuppressionEventResult(
            status=ProcessContactSuppressionEventStatus.DUPLICATE,
            external_event_id=existing.external_event_id,
            lead_id=existing.lead_id,
            reasons=(ProcessContactSuppressionEventReasonCode.DUPLICATE_EVENT,),
        )

    external_event = ExternalEvent(
        external_event_id=(external_event_id_factory or uuid4)(),
        workspace_id=event.workspace_id,
        provider=event.source_provider,
        event_type=_event_type(event.suppression_kind),
        provider_event_id=event.provider_event_id,
        crm_lead_id=event.crm_lead_id,
        lead_id=None,
        received_at=event.occurred_at,
        processed_at=None,
        status=ExternalEventStatus.PENDING,
        payload_redacted=dict(event.payload_redacted),
        failure_reason=None,
        created_at=now,
        updated_at=now,
    )

    lead = await lead_repository.get_by_crm_id(
        event.workspace_id,
        event.crm_provider,
        event.crm_lead_id,
    )
    if lead is None:
        saved_event = await external_event_repository.save(
            replace(
                external_event,
                status=ExternalEventStatus.IGNORED,
                processed_at=now,
                failure_reason=ProcessContactSuppressionEventReasonCode.LEAD_NOT_FOUND.value,
                updated_at=now,
            )
        )
        return ProcessContactSuppressionEventResult(
            status=ProcessContactSuppressionEventStatus.IGNORED,
            external_event_id=saved_event.external_event_id,
            suppression_kind=event.suppression_kind,
            reasons=(ProcessContactSuppressionEventReasonCode.LEAD_NOT_FOUND,),
        )

    saved_event = await external_event_repository.save(
        replace(external_event, lead_id=lead.lead_id)
    )

    updated_lead = await apply_contact_suppression_to_lead(
        lead=lead,
        suppression_kind=event.suppression_kind,
        source_provider=event.source_provider,
        source_event_id=event.provider_event_id,
        occurred_at=event.occurred_at,
        lead_repository=lead_repository,
    )
    suppression_applied = updated_lead != lead

    policy = await workspace_contact_policy_repository.get_by_workspace_id(event.workspace_id)
    target_state = _target_workflow_state(
        lead=updated_lead,
        suppression_kind=event.suppression_kind,
        policy=policy or default_workspace_contact_policy(event.workspace_id),
    )
    transition = await apply_workflow_state_transition(
        workspace_id=event.workspace_id,
        lead_id=updated_lead.lead_id,
        to_state=target_state,
        reason_code=WorkflowTransitionReasonCode.CONTACT_SUPPRESSION_DETECTED,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=event.occurred_at,
        external_event_id=saved_event.external_event_id,
        metadata=_suppression_metadata(event),
        pause_reason=event.suppression_kind.value,
    )

    reasons: list[ProcessContactSuppressionEventReasonCode] = []
    signal_sent = False
    signal_failure_reason: str | None = None
    transition_skip_reason: str | None = None

    if transition.status == WorkflowStateTransitionStatus.NO_WORKFLOW:
        reasons.append(ProcessContactSuppressionEventReasonCode.NO_WORKFLOW)
    elif transition.status == WorkflowStateTransitionStatus.SKIPPED:
        reasons.append(ProcessContactSuppressionEventReasonCode.TRANSITION_SKIPPED)
        transition_skip_reason = transition.skip_reason
    elif transition.workflow is not None:
        try:
            await lead_nurture_workflow_signaler.signal_pause_lead_nurture_workflow(
                temporal_workflow_id=transition.workflow.temporal_workflow_id,
                signal=PauseLeadNurtureWorkflowSignal(
                    workspace_id=event.workspace_id,
                    lead_id=updated_lead.lead_id,
                    occurred_at=event.occurred_at,
                    reason=event.suppression_kind.value,
                    external_event_id=saved_event.external_event_id,
                ),
            )
            signal_sent = True
        except Exception as exc:  # pragma: no cover - defensive branch
            reasons.append(ProcessContactSuppressionEventReasonCode.SIGNAL_DISPATCH_FAILED)
            signal_failure_reason = str(exc)

    await external_event_repository.save(
        replace(
            saved_event,
            status=ExternalEventStatus.PROCESSED,
            processed_at=now,
            updated_at=now,
        )
    )
    return ProcessContactSuppressionEventResult(
        status=ProcessContactSuppressionEventStatus.PROCESSED,
        external_event_id=saved_event.external_event_id,
        lead_id=updated_lead.lead_id,
        workflow_id=transition.workflow.workflow_id if transition.workflow is not None else None,
        workflow_transition_id=transition.transition_id,
        suppression_kind=event.suppression_kind,
        workflow_state=transition.workflow.state if transition.workflow is not None else None,
        suppression_applied=suppression_applied,
        signal_sent=signal_sent,
        signal_failure_reason=signal_failure_reason,
        transition_skip_reason=transition_skip_reason,
        reasons=tuple(reasons),
    )


async def apply_contact_suppression_to_lead(
    *,
    lead: CanonicalLeadRecord,
    suppression_kind: ContactSuppressionKind,
    source_provider: str,
    occurred_at: datetime,
    lead_repository: LeadRepository,
    source_event_id: str | None = None,
) -> CanonicalLeadRecord:
    updated_lead = _updated_lead_with_suppression(
        lead=lead,
        suppression_kind=suppression_kind,
        source_provider=source_provider,
        occurred_at=occurred_at,
        source_event_id=source_event_id,
    )
    if updated_lead == lead:
        return lead
    return await lead_repository.upsert(updated_lead)


def _updated_lead_with_suppression(
    *,
    lead: CanonicalLeadRecord,
    suppression_kind: ContactSuppressionKind,
    source_provider: str,
    occurred_at: datetime,
    source_event_id: str | None,
) -> CanonicalLeadRecord:
    permission_evidence = dict(lead.permission_evidence)
    evidence_prefix = suppression_kind.value
    permission_evidence[f"{evidence_prefix}_source_provider"] = source_provider
    permission_evidence[f"{evidence_prefix}_occurred_at"] = occurred_at.isoformat()
    if source_event_id is not None:
        permission_evidence[f"{evidence_prefix}_source_event_id"] = source_event_id

    suppressions = set(lead.suppression_types)

    if suppression_kind == ContactSuppressionKind.SMS_OPT_OUT:
        suppressions.add(SuppressionType.SMS_OPT_OUT)
        return replace(
            lead,
            sms_opted_out=True,
            suppression_types=frozenset(suppressions),
            permission_evidence=permission_evidence,
        )

    if suppression_kind == ContactSuppressionKind.EMAIL_UNSUBSCRIBED:
        suppressions.add(SuppressionType.EMAIL_UNSUBSCRIBED)
        return replace(
            lead,
            email_unsubscribed=True,
            suppression_types=frozenset(suppressions),
            permission_evidence=permission_evidence,
        )

    return replace(
        lead,
        do_not_contact=True,
        permission_evidence=permission_evidence,
    )


def _target_workflow_state(
    *,
    lead: CanonicalLeadRecord,
    suppression_kind: ContactSuppressionKind,
    policy: WorkspaceContactPolicy,
) -> WorkflowState:
    if suppression_kind == ContactSuppressionKind.DO_NOT_CONTACT:
        return WorkflowState.SUPPRESSED

    if _channel_sendable(lead, policy, ContactChannel.SMS):
        return WorkflowState.PAUSED
    if _channel_sendable(lead, policy, ContactChannel.EMAIL):
        return WorkflowState.PAUSED
    return WorkflowState.SUPPRESSED


def _channel_sendable(
    lead: CanonicalLeadRecord,
    policy: WorkspaceContactPolicy,
    channel: ContactChannel,
) -> bool:
    if channel == ContactChannel.SMS:
        if not lead.has_sms_capable_phone or lead.primary_phone is None:
            return False
    else:
        if not lead.has_email or lead.primary_email is None:
            return False

    decision = evaluate_contactability(
        contactability_facts_from_canonical_lead(lead),
        policy,
        channel,
    )
    return decision.allowed


def _event_type(suppression_kind: ContactSuppressionKind) -> str:
    return f"contact_suppression.{suppression_kind.value}"


def _suppression_metadata(event: ContactSuppressionEvent) -> dict[str, str]:
    metadata = {
        "source_provider": event.source_provider,
        "suppression_kind": event.suppression_kind.value,
    }
    if event.provider_message_id is not None:
        metadata["provider_message_id"] = event.provider_message_id
    return metadata
