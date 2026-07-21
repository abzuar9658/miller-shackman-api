from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.application.ports.crm import CRMClient
from app.application.ports.repositories import OutboundMessageCRMCompletionRepository
from app.application.services.crm_snapshot import build_crm_snapshot_custom_fields
from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageCRMCompletionRecord,
)
from app.domain.conversations import WorkspaceHandoffConfig
from app.domain.leads import CanonicalLeadRecord


class CompleteOutboundMessageCRMSyncStatus(StrEnum):
    COMPLETED = "completed"
    ALREADY_COMPLETED = "already_completed"
    RETRYABLE_FAILURE = "retryable_failure"


@dataclass(frozen=True)
class CompleteOutboundMessageCRMSyncResult:
    status: CompleteOutboundMessageCRMSyncStatus
    outbound_message_id: UUID
    completed_at: datetime | None = None
    failure_reason: str | None = None


async def complete_outbound_message_crm_sync(
    *,
    lead: CanonicalLeadRecord,
    outbound_message: OutboundMessage,
    crm_sync_completion_repository: OutboundMessageCRMCompletionRepository,
    crm_client: CRMClient,
    now: datetime,
    summary_text: str | None = None,
    latest_inbound_text: str | None = None,
    workspace_handoff_config: WorkspaceHandoffConfig | None = None,
    snapshot_status: str | None = None,
) -> CompleteOutboundMessageCRMSyncResult:
    existing = await crm_sync_completion_repository.get_by_outbound_message_id(
        lead.workspace_id,
        outbound_message.message_id,
    )
    if existing is not None and existing.completed_at is not None:
        return CompleteOutboundMessageCRMSyncResult(
            status=CompleteOutboundMessageCRMSyncStatus.ALREADY_COMPLETED,
            outbound_message_id=outbound_message.message_id,
            completed_at=existing.completed_at,
        )

    record = existing or OutboundMessageCRMCompletionRecord(
        outbound_message_id=outbound_message.message_id,
        workspace_id=lead.workspace_id,
        crm_note_idempotency_key=_crm_note_idempotency_key(outbound_message.message_id),
    )
    record = await crm_sync_completion_repository.save(
        replace(record, last_attempted_at=now, failure_reason=None),
    )

    try:
        if record.crm_note_written_at is None:
            subject, content = _crm_outbound_note(
                lead=lead,
                outbound_message=outbound_message,
                summary_text=summary_text,
                latest_inbound_text=latest_inbound_text,
            )
            await crm_client.add_note(
                lead.workspace_id,
                lead.crm_lead_id,
                content,
                subject=subject,
            )
            record = await crm_sync_completion_repository.save(
                replace(
                    record,
                    crm_note_written_at=now,
                    last_attempted_at=now,
                    failure_reason=None,
                ),
            )
        snapshot_fields = build_crm_snapshot_custom_fields(
            workspace_handoff_config,
            summary_text=summary_text,
            status=snapshot_status,
            latest_inbound_text=latest_inbound_text,
            latest_outbound_text=outbound_message.body,
            last_activity_at=outbound_message.sent_at or outbound_message.updated_at,
        )
        if snapshot_fields and record.crm_snapshot_updated_at is None:
            await crm_client.update_custom_fields(
                lead.workspace_id,
                lead.crm_lead_id,
                snapshot_fields,
            )
            record = await crm_sync_completion_repository.save(
                replace(
                    record,
                    crm_snapshot_updated_at=now,
                    last_attempted_at=now,
                    failure_reason=None,
                ),
            )
    except Exception as exc:
        saved = await crm_sync_completion_repository.save(
            replace(record, failure_reason=str(exc), last_attempted_at=now),
        )
        return CompleteOutboundMessageCRMSyncResult(
            status=CompleteOutboundMessageCRMSyncStatus.RETRYABLE_FAILURE,
            outbound_message_id=outbound_message.message_id,
            failure_reason=saved.failure_reason,
        )

    completed = await crm_sync_completion_repository.save(
        replace(record, completed_at=now, last_attempted_at=now, failure_reason=None),
    )
    return CompleteOutboundMessageCRMSyncResult(
        status=CompleteOutboundMessageCRMSyncStatus.COMPLETED,
        outbound_message_id=outbound_message.message_id,
        completed_at=completed.completed_at,
    )


def _crm_note_idempotency_key(outbound_message_id: UUID) -> str:
    return f"outbound-message:{outbound_message_id}:crm-note:v1"


def _crm_outbound_note(
    *,
    lead: CanonicalLeadRecord,
    outbound_message: OutboundMessage,
    summary_text: str | None,
    latest_inbound_text: str | None,
) -> tuple[str, str]:
    channel = outbound_message.channel.value.upper()
    subject = f"AI OUTBOUND · {channel}"
    lines = [
        subject,
        f"Lead: {_lead_display_name(lead)}",
        f"Sent at: {(outbound_message.sent_at or outbound_message.updated_at).isoformat()}",
    ]
    if outbound_message.subject:
        lines.append(f"Subject: {outbound_message.subject}")
    if outbound_message.provider_message_id:
        lines.append(f"Provider message id: {outbound_message.provider_message_id}")
    if latest_inbound_text:
        lines.extend(("", "Latest inbound:", latest_inbound_text))
    if summary_text:
        lines.extend(("", "Conversation summary:", summary_text))
    lines.extend(("", "Message:", outbound_message.body))
    return subject, "\n".join(lines)


def _lead_display_name(lead: CanonicalLeadRecord) -> str:
    return lead.primary_email or lead.primary_phone or lead.crm_lead_id