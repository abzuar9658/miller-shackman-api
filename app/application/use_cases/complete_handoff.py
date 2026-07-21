from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.application.ports.crm import CRMClient
from app.application.ports.notifications import HandoffNotification, NotificationProvider
from app.application.ports.repositories import (
    HandoffCompletionRepository,
    HandoffRepository,
    LeadRepository,
    WorkspaceHandoffConfigRepository,
)
from app.application.services.crm_snapshot import build_crm_snapshot_custom_fields
from app.domain.common.ids import WorkspaceId
from app.domain.conversations import (
    Handoff,
    HandoffCompletionRecord,
    HandoffStatus,
    default_workspace_handoff_config,
)
from app.domain.leads import CanonicalLeadRecord


class HandoffCompletionStatus(StrEnum):
    COMPLETED = "completed"
    ALREADY_COMPLETED = "already_completed"
    RETRYABLE_FAILURE = "retryable_failure"
    HANDOFF_NOT_FOUND = "handoff_not_found"
    LEAD_NOT_FOUND = "lead_not_found"
    MISSING_NOTIFICATION_DESTINATION = "missing_notification_destination"


@dataclass(frozen=True)
class HandoffCompletionResult:
    status: HandoffCompletionStatus
    handoff_id: UUID
    completed_at: datetime | None = None
    failure_reason: str | None = None


async def complete_handoff(
    *,
    workspace_id: WorkspaceId,
    handoff_id: UUID,
    handoff_repository: HandoffRepository,
    handoff_completion_repository: HandoffCompletionRepository,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository,
    lead_repository: LeadRepository,
    crm_client: CRMClient,
    notification_provider: NotificationProvider,
    now: datetime,
) -> HandoffCompletionResult:
    handoff = await handoff_repository.get_by_id(workspace_id, handoff_id)
    if handoff is None:
        return HandoffCompletionResult(
            status=HandoffCompletionStatus.HANDOFF_NOT_FOUND,
            handoff_id=handoff_id,
            failure_reason=HandoffCompletionStatus.HANDOFF_NOT_FOUND.value,
        )

    lead = await lead_repository.get_by_id(workspace_id, handoff.lead_id)
    if lead is None:
        return HandoffCompletionResult(
            status=HandoffCompletionStatus.LEAD_NOT_FOUND,
            handoff_id=handoff_id,
            failure_reason=HandoffCompletionStatus.LEAD_NOT_FOUND.value,
        )

    existing = await handoff_completion_repository.get_by_handoff_id(workspace_id, handoff_id)
    if existing is not None and existing.completed_at is not None:
        return HandoffCompletionResult(
            status=HandoffCompletionStatus.ALREADY_COMPLETED,
            handoff_id=handoff_id,
            completed_at=existing.completed_at,
        )

    config = await workspace_handoff_config_repository.get_by_workspace_id(workspace_id)
    handoff_config = config or default_workspace_handoff_config(workspace_id)
    record = existing or HandoffCompletionRecord(
        handoff_id=handoff.handoff_id,
        workspace_id=workspace_id,
        notification_idempotency_key=_notification_idempotency_key(handoff.handoff_id),
    )
    record = await handoff_completion_repository.save(
        replace(record, last_attempted_at=now, failure_reason=None),
    )

    assigned_agent = await crm_client.get_assigned_agent(workspace_id, lead.crm_lead_id)
    recipient_destination = (
        assigned_agent.email
        if assigned_agent is not None and assigned_agent.email
        else handoff_config.fallback_recipient_email
    )
    recipient_id = (
        assigned_agent.crm_agent_id
        if assigned_agent is not None
        else handoff_config.fallback_recipient_email
    )
    if recipient_destination is None or recipient_id is None:
        saved = await handoff_completion_repository.save(
            replace(
                record,
                notification_recipient_destination=recipient_destination,
                notification_recipient_id=recipient_id,
                failure_reason=HandoffCompletionStatus.MISSING_NOTIFICATION_DESTINATION.value,
                last_attempted_at=now,
            ),
        )
        return HandoffCompletionResult(
            status=HandoffCompletionStatus.MISSING_NOTIFICATION_DESTINATION,
            handoff_id=handoff_id,
            failure_reason=saved.failure_reason,
        )

    if record.notification_sent_at is None:
        send_result = await notification_provider.send_handoff_notification(
            _handoff_notification(
                handoff=handoff,
                lead=lead,
                recipient_id=recipient_id,
                recipient_destination=recipient_destination,
                assigned_agent_name=assigned_agent.name if assigned_agent is not None else None,
                idempotency_key=record.notification_idempotency_key,
            ),
        )
        if send_result.uncertain or not send_result.accepted:
            saved = await handoff_completion_repository.save(
                replace(
                    record,
                    notification_recipient_id=recipient_id,
                    notification_recipient_destination=recipient_destination,
                    notification_provider_reference=send_result.provider_reference,
                    failure_reason="notification_uncertain"
                    if send_result.uncertain
                    else "notification_failed",
                    last_attempted_at=now,
                ),
            )
            return HandoffCompletionResult(
                status=HandoffCompletionStatus.RETRYABLE_FAILURE,
                handoff_id=handoff_id,
                failure_reason=saved.failure_reason,
            )
        record = await handoff_completion_repository.save(
            replace(
                record,
                notification_recipient_id=recipient_id,
                notification_recipient_destination=recipient_destination,
                notification_provider_reference=send_result.provider_reference,
                notification_sent_at=now,
                failure_reason=None,
                last_attempted_at=now,
            ),
        )
        handoff = await handoff_repository.save(
            replace(handoff, status=HandoffStatus.NOTIFIED, notified_at=now),
        )

    try:
        if record.crm_note_written_at is None:
            subject, content = _crm_handoff_note(handoff, lead)
            await crm_client.add_note(
                workspace_id,
                lead.crm_lead_id,
                content,
                subject=subject,
            )
            record = await handoff_completion_repository.save(
                replace(
                    record, crm_note_written_at=now, last_attempted_at=now, failure_reason=None
                ),
            )
        if handoff_config.crm_handoff_tag and record.crm_tag_applied_at is None:
            await crm_client.add_tag(workspace_id, lead.crm_lead_id, handoff_config.crm_handoff_tag)
            record = await handoff_completion_repository.save(
                replace(record, crm_tag_applied_at=now, last_attempted_at=now, failure_reason=None),
            )
        custom_fields = (
            dict(handoff_config.crm_custom_fields)
            if handoff_config.crm_custom_fields and record.crm_custom_fields_updated_at is None
            else {}
        )
        snapshot_fields = (
            build_crm_snapshot_custom_fields(
                handoff_config,
                summary_text=handoff.summary,
                status="human_handoff_required",
                latest_inbound_text=handoff.latest_inbound_text,
                last_activity_at=handoff.created_at,
            )
            if record.crm_snapshot_updated_at is None
            else {}
        )
        fields_to_update = {**custom_fields, **snapshot_fields}
        if fields_to_update:
            await crm_client.update_custom_fields(
                workspace_id,
                lead.crm_lead_id,
                fields_to_update,
            )
            record = await handoff_completion_repository.save(
                replace(
                    record,
                    crm_custom_fields_updated_at=(
                        now if custom_fields else record.crm_custom_fields_updated_at
                    ),
                    crm_snapshot_updated_at=(
                        now if snapshot_fields else record.crm_snapshot_updated_at
                    ),
                    last_attempted_at=now,
                    failure_reason=None,
                ),
            )
    except Exception as exc:
        saved = await handoff_completion_repository.save(
            replace(record, failure_reason=str(exc), last_attempted_at=now),
        )
        return HandoffCompletionResult(
            status=HandoffCompletionStatus.RETRYABLE_FAILURE,
            handoff_id=handoff_id,
            failure_reason=saved.failure_reason,
        )

    completed = await handoff_completion_repository.save(
        replace(record, completed_at=now, last_attempted_at=now, failure_reason=None),
    )
    return HandoffCompletionResult(
        status=HandoffCompletionStatus.COMPLETED,
        handoff_id=handoff_id,
        completed_at=completed.completed_at,
    )


def _notification_idempotency_key(handoff_id: UUID) -> str:
    return f"handoff:{handoff_id}:agent-notification:v1"


def _handoff_notification(
    *,
    handoff: Handoff,
    lead: CanonicalLeadRecord,
    recipient_id: str,
    recipient_destination: str,
    assigned_agent_name: str | None,
    idempotency_key: str,
) -> HandoffNotification:
    return HandoffNotification(
        workspace_id=handoff.workspace_id,
        handoff_id=handoff.handoff_id,
        lead_id=handoff.lead_id,
        recipient_id=recipient_id,
        recipient_destination=recipient_destination,
        lead_display_name=_lead_display_name(lead),
        lead_primary_email=lead.primary_email,
        lead_primary_phone=lead.primary_phone,
        handoff_reason=handoff.reason_code,
        latest_inbound_text=handoff.latest_inbound_text or "",
        summary=handoff.summary,
        preferences=dict(handoff.preferences),
        assigned_agent_name=assigned_agent_name,
        recommended_next_action=(
            "Review the latest reply, contact the lead directly, and decide whether "
            "to resume or keep AI paused."
        ),
        idempotency_key=idempotency_key,
    )


def _crm_handoff_note(handoff: Handoff, lead: CanonicalLeadRecord) -> tuple[str, str]:
    subject = "AI HANDOFF"
    preference_lines = (
        "\n".join(f"- {key}: {value}" for key, value in sorted(handoff.preferences.items()))
        or "- none extracted"
    )
    content = (
        f"{subject}\n"
        f"Lead: {_lead_display_name(lead)}\n"
        f"Reason: {handoff.reason_code.value}\n"
        f"Latest inbound: {handoff.latest_inbound_text}\n\n"
        f"Conversation summary:\n{handoff.summary}\n\n"
        f"Extracted preferences:\n{preference_lines}"
    )
    return subject, content


def _lead_display_name(lead: CanonicalLeadRecord) -> str:
    return lead.primary_email or lead.primary_phone or lead.crm_lead_id
