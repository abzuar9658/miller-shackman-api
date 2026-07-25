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
    UserRepository,
    WorkspaceHandoffConfigRepository,
)
from app.application.services.crm_attention_tag_sync import (
    remove_conflicting_crm_tag_if_present,
)
from app.application.services.crm_snapshot import build_crm_snapshot_custom_fields
from app.application.services.lead_assignment import lead_assigned_agent_user_id
from app.domain.common.ids import WorkspaceId
from app.domain.conversations import (
    Handoff,
    HandoffCompletionRecord,
    HandoffStatus,
    default_workspace_handoff_config,
)
from app.domain.identity import User
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
    user_repository: UserRepository | None = None,
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
        notification_idempotency_key=handoff_notification_idempotency_key(handoff.handoff_id),
    )
    record = await handoff_completion_repository.save(
        replace(record, last_attempted_at=now, failure_reason=None),
    )

    completion_status = HandoffCompletionStatus.COMPLETED
    completion_failure_reason: str | None = None
    assigned_user = await _assigned_app_user(lead=lead, user_repository=user_repository)
    crm_lead_url = await _crm_lead_url(
        crm_client=crm_client,
        workspace_id=workspace_id,
        crm_lead_id=lead.crm_lead_id,
    )
    assigned_agent = None
    recipient_destination = assigned_user.email if assigned_user is not None else None
    recipient_id = str(assigned_user.user_id) if assigned_user is not None else None
    assigned_user_name = assigned_user.full_name if assigned_user is not None else None
    if recipient_destination is None or recipient_id is None:
        try:
            assigned_agent = await crm_client.get_assigned_agent(workspace_id, lead.crm_lead_id)
        except Exception as exc:
            assigned_agent = None
            completion_status = HandoffCompletionStatus.RETRYABLE_FAILURE
            completion_failure_reason = _side_effect_failure_reason("assigned_agent_lookup", exc)
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
        assigned_user_name = assigned_agent.name if assigned_agent is not None else None
    if recipient_destination is None or recipient_id is None:
        completion_status = (
            completion_status
            if completion_status == HandoffCompletionStatus.RETRYABLE_FAILURE
            else HandoffCompletionStatus.MISSING_NOTIFICATION_DESTINATION
        )
        completion_failure_reason = (
            completion_failure_reason
            or HandoffCompletionStatus.MISSING_NOTIFICATION_DESTINATION.value
        )
        record = await handoff_completion_repository.save(
            replace(
                record,
                notification_recipient_destination=recipient_destination,
                notification_recipient_id=recipient_id,
                failure_reason=completion_failure_reason,
                last_attempted_at=now,
            ),
        )

    if (
        record.notification_sent_at is None
        and recipient_destination is not None
        and recipient_id is not None
    ):
        try:
            send_result = await notification_provider.send_handoff_notification(
                _handoff_notification(
                    handoff=handoff,
                    lead=lead,
                    recipient_id=recipient_id,
                    recipient_destination=recipient_destination,
                    assigned_user_name=assigned_user_name,
                    crm_lead_url=crm_lead_url,
                    idempotency_key=record.notification_idempotency_key,
                ),
            )
        except Exception as exc:
            completion_status = HandoffCompletionStatus.RETRYABLE_FAILURE
            completion_failure_reason = _side_effect_failure_reason("notification_exception", exc)
            record = await handoff_completion_repository.save(
                replace(
                    record,
                    notification_recipient_id=recipient_id,
                    notification_recipient_destination=recipient_destination,
                    failure_reason=completion_failure_reason,
                    last_attempted_at=now,
                ),
            )
        else:
            if send_result.uncertain or not send_result.accepted:
                completion_status = HandoffCompletionStatus.RETRYABLE_FAILURE
                completion_failure_reason = (
                    "notification_uncertain" if send_result.uncertain else "notification_failed"
                )
                record = await handoff_completion_repository.save(
                    replace(
                        record,
                        notification_recipient_id=recipient_id,
                        notification_recipient_destination=recipient_destination,
                        notification_provider_reference=send_result.provider_reference,
                        failure_reason=completion_failure_reason,
                        last_attempted_at=now,
                    ),
                )
            else:
                record = await handoff_completion_repository.save(
                    replace(
                        record,
                        notification_recipient_id=recipient_id,
                        notification_recipient_destination=recipient_destination,
                        notification_provider_reference=send_result.provider_reference,
                        notification_sent_at=now,
                        failure_reason=completion_failure_reason,
                        last_attempted_at=now,
                    ),
                )
                handoff = await handoff_repository.save(
                    replace(handoff, status=HandoffStatus.NOTIFIED, notified_at=now),
                )

    try:
        crm_lead = await crm_client.get_lead(workspace_id, lead.crm_lead_id)
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
                    record,
                    crm_note_written_at=now,
                    last_attempted_at=now,
                    failure_reason=completion_failure_reason,
                ),
            )
        if handoff_config.crm_handoff_tag:
            await remove_conflicting_crm_tag_if_present(
                crm_client=crm_client,
                workspace_id=workspace_id,
                crm_lead_id=lead.crm_lead_id,
                existing_tags=(crm_lead.tags if crm_lead is not None else None),
                active_tag=handoff_config.crm_handoff_tag,
                conflicting_tag=handoff_config.crm_review_tag,
            )
        if handoff_config.crm_handoff_tag and record.crm_tag_applied_at is None:
            await crm_client.add_tag(workspace_id, lead.crm_lead_id, handoff_config.crm_handoff_tag)
            record = await handoff_completion_repository.save(
                replace(
                    record,
                    crm_tag_applied_at=now,
                    last_attempted_at=now,
                    failure_reason=completion_failure_reason,
                ),
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
                    failure_reason=completion_failure_reason,
                ),
            )
    except Exception as exc:
        failure_reason = _side_effect_failure_reason("crm_handoff_write", exc)
        saved = await handoff_completion_repository.save(
            replace(record, failure_reason=failure_reason, last_attempted_at=now),
        )
        return HandoffCompletionResult(
            status=HandoffCompletionStatus.RETRYABLE_FAILURE,
            handoff_id=handoff_id,
            failure_reason=saved.failure_reason,
        )

    if completion_status != HandoffCompletionStatus.COMPLETED:
        saved = await handoff_completion_repository.save(
            replace(record, failure_reason=completion_failure_reason, last_attempted_at=now),
        )
        return HandoffCompletionResult(
            status=completion_status,
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


def handoff_notification_idempotency_key(handoff_id: UUID) -> str:
    return f"handoff:{handoff_id}:agent-notification:v1"


def _side_effect_failure_reason(step: str, exc: Exception) -> str:
    return f"{step}:{exc.__class__.__name__}"


def _handoff_notification(
    *,
    handoff: Handoff,
    lead: CanonicalLeadRecord,
    recipient_id: str,
    recipient_destination: str,
    assigned_user_name: str | None,
    crm_lead_url: str | None,
    idempotency_key: str,
) -> HandoffNotification:
    return HandoffNotification(
        workspace_id=handoff.workspace_id,
        handoff_id=handoff.handoff_id,
        lead_id=handoff.lead_id,
        recipient_id=recipient_id,
        recipient_destination=recipient_destination,
        assigned_user_name=assigned_user_name,
        lead_display_name=_lead_display_name(lead),
        lead_primary_email=lead.primary_email,
        lead_primary_phone=lead.primary_phone,
        crm_lead_id=lead.crm_lead_id,
        crm_lead_url=crm_lead_url,
        handoff_reason=handoff.reason_code,
        latest_inbound_text=handoff.latest_inbound_text or "",
        summary=handoff.summary,
        preferences=dict(handoff.preferences),
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


async def _assigned_app_user(
    *,
    lead: CanonicalLeadRecord,
    user_repository: UserRepository | None,
) -> User | None:
    if user_repository is None:
        return None
    user_id = lead_assigned_agent_user_id(lead)
    if user_id is None:
        return None
    try:
        user = await user_repository.get_by_id(user_id)
    except Exception:
        return None
    if user is None or not user.email:
        return None
    return user


async def _crm_lead_url(
    *,
    crm_client: CRMClient,
    workspace_id: WorkspaceId,
    crm_lead_id: str,
) -> str | None:
    try:
        return await crm_client.get_lead_url(workspace_id, crm_lead_id)
    except Exception:
        return None
