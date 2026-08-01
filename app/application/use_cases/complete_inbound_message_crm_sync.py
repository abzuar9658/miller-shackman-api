from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.application.ports.crm import CanonicalLead, CRMActivity, CRMClient
from app.application.ports.repositories import InboundMessageCRMCompletionRepository
from app.application.services.crm_attention_tag_sync import (
    remove_conflicting_crm_tag_if_present,
)
from app.application.services.crm_snapshot import build_crm_snapshot_custom_fields
from app.application.services.llm.reply_classification import InboundReplyIntent
from app.application.use_cases.evaluate_inbound_action import InboundAction
from app.domain.conversations import (
    InboundMessage,
    InboundMessageCRMCompletionRecord,
    WorkspaceHandoffConfig,
)
from app.domain.leads import CanonicalLeadRecord


class CompleteInboundMessageCRMSyncStatus(StrEnum):
    COMPLETED = "completed"
    ALREADY_COMPLETED = "already_completed"
    RETRYABLE_FAILURE = "retryable_failure"
    CRM_LEAD_NOT_FOUND = "crm_lead_not_found"


@dataclass(frozen=True)
class CompleteInboundMessageCRMSyncResult:
    status: CompleteInboundMessageCRMSyncStatus
    inbound_message_id: UUID
    completed_at: datetime | None = None
    failure_reason: str | None = None


async def complete_inbound_message_crm_sync(
    *,
    lead: CanonicalLeadRecord,
    inbound_message: InboundMessage,
    summary_text: str | None,
    crm_sync_completion_repository: InboundMessageCRMCompletionRepository,
    crm_client: CRMClient,
    now: datetime,
    intent: InboundReplyIntent | None = None,
    handoff_required: bool,
    opt_out_detected: bool,
    inbound_action: InboundAction,
    review_tag: str | None = None,
    classification_rejected: bool = False,
    write_inbound_note: bool = True,
    workspace_handoff_config: WorkspaceHandoffConfig | None = None,
    snapshot_status: str | None = None,
    activity_limit: int = 20,
) -> CompleteInboundMessageCRMSyncResult:
    existing = await crm_sync_completion_repository.get_by_inbound_message_id(
        lead.workspace_id,
        inbound_message.inbound_message_id,
    )
    if existing is not None and existing.completed_at is not None:
        return CompleteInboundMessageCRMSyncResult(
            status=CompleteInboundMessageCRMSyncStatus.ALREADY_COMPLETED,
            inbound_message_id=inbound_message.inbound_message_id,
            completed_at=existing.completed_at,
        )

    record = existing or InboundMessageCRMCompletionRecord(
        inbound_message_id=inbound_message.inbound_message_id,
        workspace_id=lead.workspace_id,
        crm_note_idempotency_key=_crm_note_idempotency_key(inbound_message.inbound_message_id),
    )
    record = await crm_sync_completion_repository.save(
        replace(record, last_attempted_at=now, failure_reason=None),
    )

    try:
        refreshed_lead = await crm_client.get_lead(lead.workspace_id, lead.crm_lead_id)
        recent_activity = await crm_client.get_recent_activity(
            lead.workspace_id,
            lead.crm_lead_id,
            limit=activity_limit,
        )
        latest_activity_at = _latest_activity_at(recent_activity)
        crm_updates_detected = _crm_updates_detected(
            inbound_message=inbound_message,
            lead_updated_at=refreshed_lead.updated_at if refreshed_lead is not None else None,
            latest_activity_at=latest_activity_at,
        )
        record = await crm_sync_completion_repository.save(
            replace(
                record,
                crm_refreshed_at=now,
                crm_lead_updated_at=(
                    refreshed_lead.updated_at if refreshed_lead is not None else None
                ),
                crm_latest_activity_at=latest_activity_at,
                crm_updates_detected=crm_updates_detected,
                last_attempted_at=now,
                failure_reason=None,
            ),
        )
        if refreshed_lead is None:
            saved = await crm_sync_completion_repository.save(
                replace(
                    record,
                    failure_reason=CompleteInboundMessageCRMSyncStatus.CRM_LEAD_NOT_FOUND.value,
                    last_attempted_at=now,
                )
            )
            return CompleteInboundMessageCRMSyncResult(
                status=CompleteInboundMessageCRMSyncStatus.CRM_LEAD_NOT_FOUND,
                inbound_message_id=inbound_message.inbound_message_id,
                failure_reason=saved.failure_reason,
            )
        if write_inbound_note and record.crm_note_written_at is None:
            subject, content = _crm_inbound_note(
                refreshed_lead=refreshed_lead,
                inbound_message=inbound_message,
                summary_text=summary_text,
                intent=intent,
                handoff_required=handoff_required,
                opt_out_detected=opt_out_detected,
                inbound_action=inbound_action,
                classification_rejected=classification_rejected,
                crm_updates_detected=crm_updates_detected,
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
        if review_tag:
            await remove_conflicting_crm_tag_if_present(
                crm_client=crm_client,
                workspace_id=lead.workspace_id,
                crm_lead_id=lead.crm_lead_id,
                existing_tags=refreshed_lead.tags,
                active_tag=review_tag,
                conflicting_tag=(
                    workspace_handoff_config.crm_handoff_tag
                    if workspace_handoff_config is not None
                    else None
                ),
            )
        if review_tag and record.crm_review_tag_applied_at is None:
            await crm_client.add_tag(lead.workspace_id, lead.crm_lead_id, review_tag)
            record = await crm_sync_completion_repository.save(
                replace(
                    record,
                    crm_review_tag_applied_at=now,
                    last_attempted_at=now,
                    failure_reason=None,
                ),
            )
        snapshot_fields = build_crm_snapshot_custom_fields(
            workspace_handoff_config,
            summary_text=summary_text,
            status=snapshot_status,
            latest_inbound_text=inbound_message.body,
            last_activity_at=inbound_message.received_at,
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
        return CompleteInboundMessageCRMSyncResult(
            status=CompleteInboundMessageCRMSyncStatus.RETRYABLE_FAILURE,
            inbound_message_id=inbound_message.inbound_message_id,
            failure_reason=saved.failure_reason,
        )

    completed = await crm_sync_completion_repository.save(
        replace(record, completed_at=now, last_attempted_at=now, failure_reason=None),
    )
    return CompleteInboundMessageCRMSyncResult(
        status=CompleteInboundMessageCRMSyncStatus.COMPLETED,
        inbound_message_id=inbound_message.inbound_message_id,
        completed_at=completed.completed_at,
    )


def _latest_activity_at(activities: list[CRMActivity]) -> datetime | None:
    if not activities:
        return None
    return max(activity.timestamp for activity in activities)


def _crm_updates_detected(
    *,
    inbound_message: InboundMessage,
    lead_updated_at: datetime | None,
    latest_activity_at: datetime | None,
) -> bool:
    return any(
        timestamp is not None and timestamp > inbound_message.received_at
        for timestamp in (lead_updated_at, latest_activity_at)
    )


def _crm_note_idempotency_key(inbound_message_id: UUID) -> str:
    return f"inbound-message:{inbound_message_id}:crm-note:v1"


def _crm_inbound_note(
    *,
    refreshed_lead: CanonicalLead,
    inbound_message: InboundMessage,
    summary_text: str | None,
    intent: InboundReplyIntent | None,
    handoff_required: bool,
    opt_out_detected: bool,
    inbound_action: InboundAction,
    classification_rejected: bool,
    crm_updates_detected: bool,
) -> tuple[str, str]:
    display_name = _lead_display_name(refreshed_lead)
    channel = inbound_message.channel.value.upper()
    subject = f"AI INBOUND · {channel}"
    summary = summary_text or inbound_message.body
    intent_value = intent.value if intent is not None else "unknown"
    content = (
        f"{subject}\n"
        f"Lead: {display_name}\n"
        f"Received at: {inbound_message.received_at.isoformat()}\n"
        f"Intent: {intent_value}\n"
        f"Action: {inbound_action.value}\n"
        f"Handoff required: {'yes' if handoff_required else 'no'}\n"
        f"Opt out detected: {'yes' if opt_out_detected else 'no'}\n"
        f"Classification rejected: {'yes' if classification_rejected else 'no'}\n"
        f"CRM updates detected: {'yes' if crm_updates_detected else 'no'}\n\n"
        f"Latest inbound:\n{inbound_message.body}\n\n"
        f"Conversation summary:\n{summary}"
    )
    return subject, content


def _lead_display_name(lead: CanonicalLead | None) -> str:
    if lead is None:
        return "lead"
    full_name = " ".join(part for part in (lead.first_name, lead.last_name) if part).strip()
    return full_name or lead.email or lead.phone or lead.crm_lead_id
