from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.repositories import (
    ExternalEventRepository,
    LeadRepository,
    LeadWorkflowRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
)
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionStatus,
    apply_workflow_state_transition,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.crm_sync import ExternalEvent, ExternalEventStatus
from app.domain.leads import CRMProvider
from app.domain.workflows import (
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    WorkflowState,
    WorkflowTransitionReasonCode,
)


class CRMHumanActivityKind(StrEnum):
    NOTE_ADDED = "crm_note_added"
    ACTIVITY_CREATED = "crm_activity_created"
    LEAD_REASSIGNED = "crm_lead_reassigned"
    STAGE_CHANGED = "crm_stage_changed"
    STATUS_CHANGED = "crm_status_changed"


class ProcessCRMHumanActivityEventStatus(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"


class ProcessCRMHumanActivityEventReasonCode(StrEnum):
    DUPLICATE_EVENT = "duplicate_event"
    LEAD_NOT_FOUND = "lead_not_found"
    UNSUPPORTED_PROVIDER = "unsupported_provider"
    NOT_MEANINGFUL_HUMAN_ACTIVITY = "not_meaningful_human_activity"
    NO_WORKFLOW = "no_workflow"
    TRANSITION_SKIPPED = "transition_skipped"


def _empty_payload() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True)
class CRMHumanActivityEvent:
    workspace_id: WorkspaceId
    provider: str
    provider_event_id: str
    crm_lead_id: str
    occurred_at: datetime
    event_type: str
    activity_type: str | None = None
    crm_activity_id: str | None = None
    actor_agent_id: str | None = None
    changed_field: str | None = None
    previous_value_redacted: str | None = None
    new_value_redacted: str | None = None
    payload_redacted: Mapping[str, object] = field(default_factory=_empty_payload)


@dataclass(frozen=True)
class ProcessCRMHumanActivityEventResult:
    status: ProcessCRMHumanActivityEventStatus
    external_event_id: UUID | None = None
    lead_id: LeadId | None = None
    workflow_id: UUID | None = None
    workflow_transition_id: UUID | None = None
    activity_kind: CRMHumanActivityKind | None = None
    pause_reason: str | None = None
    pause_requested: bool = False
    signal_queued: bool = False
    transition_skip_reason: str | None = None
    reasons: tuple[ProcessCRMHumanActivityEventReasonCode, ...] = ()


async def process_crm_human_activity_event(
    *,
    event: CRMHumanActivityEvent,
    lead_repository: LeadRepository,
    external_event_repository: ExternalEventRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    now: datetime,
    external_event_id_factory: Callable[[], UUID] | None = None,
) -> ProcessCRMHumanActivityEventResult:
    existing = await external_event_repository.get_by_provider_event_id(
        event.workspace_id,
        event.provider,
        event.provider_event_id,
    )
    if existing is not None:
        return ProcessCRMHumanActivityEventResult(
            status=ProcessCRMHumanActivityEventStatus.DUPLICATE,
            external_event_id=existing.external_event_id,
            lead_id=existing.lead_id,
            reasons=(ProcessCRMHumanActivityEventReasonCode.DUPLICATE_EVENT,),
        )

    provider = _crm_provider(event.provider)
    external_event = ExternalEvent(
        external_event_id=(external_event_id_factory or uuid4)(),
        workspace_id=event.workspace_id,
        provider=event.provider,
        event_type=event.event_type,
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

    if provider is None:
        saved_event = await external_event_repository.save(
            replace(
                external_event,
                status=ExternalEventStatus.IGNORED,
                processed_at=now,
                failure_reason=ProcessCRMHumanActivityEventReasonCode.UNSUPPORTED_PROVIDER.value,
                updated_at=now,
            )
        )
        return ProcessCRMHumanActivityEventResult(
            status=ProcessCRMHumanActivityEventStatus.IGNORED,
            external_event_id=saved_event.external_event_id,
            reasons=(ProcessCRMHumanActivityEventReasonCode.UNSUPPORTED_PROVIDER,),
        )

    lead = await lead_repository.get_by_crm_id(event.workspace_id, provider, event.crm_lead_id)
    if lead is None:
        saved_event = await external_event_repository.save(
            replace(
                external_event,
                status=ExternalEventStatus.IGNORED,
                processed_at=now,
                failure_reason=ProcessCRMHumanActivityEventReasonCode.LEAD_NOT_FOUND.value,
                updated_at=now,
            )
        )
        return ProcessCRMHumanActivityEventResult(
            status=ProcessCRMHumanActivityEventStatus.IGNORED,
            external_event_id=saved_event.external_event_id,
            reasons=(ProcessCRMHumanActivityEventReasonCode.LEAD_NOT_FOUND,),
        )

    saved_event = await external_event_repository.save(
        replace(external_event, lead_id=lead.lead_id)
    )
    activity_kind = _meaningful_human_activity_kind(event)
    if activity_kind is None:
        ignored_event = await external_event_repository.save(
            replace(
                saved_event,
                status=ExternalEventStatus.IGNORED,
                processed_at=now,
                failure_reason=ProcessCRMHumanActivityEventReasonCode.NOT_MEANINGFUL_HUMAN_ACTIVITY.value,
                updated_at=now,
            )
        )
        return ProcessCRMHumanActivityEventResult(
            status=ProcessCRMHumanActivityEventStatus.IGNORED,
            external_event_id=ignored_event.external_event_id,
            lead_id=lead.lead_id,
            reasons=(ProcessCRMHumanActivityEventReasonCode.NOT_MEANINGFUL_HUMAN_ACTIVITY,),
        )

    if lead.last_agent_activity_at is None or event.occurred_at > lead.last_agent_activity_at:
        await lead_repository.upsert(replace(lead, last_agent_activity_at=event.occurred_at))

    transition = await apply_workflow_state_transition(
        workspace_id=event.workspace_id,
        lead_id=lead.lead_id,
        to_state=WorkflowState.PAUSED,
        reason_code=WorkflowTransitionReasonCode.CRM_HUMAN_ACTIVITY_DETECTED,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=event.occurred_at,
        external_event_id=saved_event.external_event_id,
        metadata=_activity_metadata(event, activity_kind),
        pause_reason=activity_kind.value,
    )

    reasons: list[ProcessCRMHumanActivityEventReasonCode] = []
    signal_queued = False
    transition_skip_reason: str | None = None
    pause_requested = transition.status == WorkflowStateTransitionStatus.UPDATED

    if transition.status == WorkflowStateTransitionStatus.NO_WORKFLOW:
        reasons.append(ProcessCRMHumanActivityEventReasonCode.NO_WORKFLOW)
    elif transition.status == WorkflowStateTransitionStatus.SKIPPED:
        reasons.append(ProcessCRMHumanActivityEventReasonCode.TRANSITION_SKIPPED)
        transition_skip_reason = transition.skip_reason
    elif transition.workflow is not None:
        await temporal_signal_outbox_repository.append(
            TemporalSignalOutboxEntry(
                temporal_signal_id=uuid4(),
                workspace_id=event.workspace_id,
                workflow_id=transition.workflow.workflow_id,
                temporal_workflow_id=transition.workflow.temporal_workflow_id,
                signal_name=TemporalSignalName.PAUSE_REQUESTED,
                payload={
                    "lead_id": str(lead.lead_id),
                    "occurred_at": event.occurred_at.isoformat(),
                    "reason": activity_kind.value,
                    "external_event_id": str(saved_event.external_event_id),
                },
                idempotency_key=f"pause-requested:{saved_event.external_event_id}",
                available_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        signal_queued = True

    processed_event = await external_event_repository.save(
        replace(
            saved_event,
            status=ExternalEventStatus.PROCESSED,
            processed_at=now,
            updated_at=now,
        )
    )
    return ProcessCRMHumanActivityEventResult(
        status=ProcessCRMHumanActivityEventStatus.PROCESSED,
        external_event_id=processed_event.external_event_id,
        lead_id=lead.lead_id,
        workflow_id=transition.workflow.workflow_id if transition.workflow is not None else None,
        workflow_transition_id=transition.transition_id,
        activity_kind=activity_kind,
        pause_reason=activity_kind.value,
        pause_requested=pause_requested,
        signal_queued=signal_queued,
        transition_skip_reason=transition_skip_reason,
        reasons=tuple(reasons),
    )


def _crm_provider(provider: str) -> CRMProvider | None:
    try:
        return CRMProvider(provider)
    except ValueError:
        return None


def _meaningful_human_activity_kind(
    event: CRMHumanActivityEvent,
) -> CRMHumanActivityKind | None:
    event_type = _normalize(event.event_type)
    activity_type = _normalize(event.activity_type)
    changed_field = _normalize(event.changed_field)

    if event_type in {"note_added", "note_created"} or activity_type in {
        "note",
        "note_added",
        "note_created",
    }:
        return CRMHumanActivityKind.NOTE_ADDED
    if event_type in {"activity_created", "manual_activity_created"}:
        return CRMHumanActivityKind.ACTIVITY_CREATED
    if event_type in {"stage_changed", "lead_stage_changed"} or changed_field in {
        "stage",
        "lead_stage",
    }:
        return CRMHumanActivityKind.STAGE_CHANGED
    if event_type in {"status_changed", "lead_status_changed"} or changed_field in {
        "status",
        "lead_status",
    }:
        return CRMHumanActivityKind.STATUS_CHANGED
    return None


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized or None


def _activity_metadata(
    event: CRMHumanActivityEvent,
    activity_kind: CRMHumanActivityKind,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "human_activity_kind": activity_kind.value,
        "crm_event_type": event.event_type,
    }
    if event.activity_type is not None:
        metadata["crm_activity_type"] = event.activity_type
    if event.crm_activity_id is not None:
        metadata["crm_activity_id"] = event.crm_activity_id
    if event.actor_agent_id is not None:
        metadata["crm_actor_agent_id"] = event.actor_agent_id
    if event.changed_field is not None:
        metadata["changed_field"] = event.changed_field
    if event.previous_value_redacted is not None:
        metadata["previous_value_redacted"] = event.previous_value_redacted
    if event.new_value_redacted is not None:
        metadata["new_value_redacted"] = event.new_value_redacted
    return metadata
