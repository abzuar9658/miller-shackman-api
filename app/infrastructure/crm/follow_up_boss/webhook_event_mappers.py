from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from app.application.ports.crm import CRMResourceFetchError, CRMResourceFetchFailureKind
from app.application.ports.crm_webhook import FollowUpBossWebhookEventBundle
from app.application.use_cases.process_contact_suppression_event import (
    ContactSuppressionEvent,
    process_contact_suppression_event,
)
from app.application.use_cases.process_crm_human_activity_event import (
    CRMHumanActivityEvent,
    process_crm_human_activity_event,
)
from app.domain.compliance.contactability import ContactSuppressionKind
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.leads import CRMProvider
from app.infrastructure.crm.follow_up_boss.webhook_event_parsers import (
    extract_collection,
    parse_iso,
)

_PROVIDER = CRMProvider.FOLLOW_UP_BOSS.value


async def handle_notes_created(
    workspace_id: UUID,
    event_id: str,
    occurred_at: datetime,
    uri: str,
    bundle: FollowUpBossWebhookEventBundle,
) -> tuple[int, int]:
    raw = await bundle.crm_client.fetch_resource_by_uri(workspace_id, uri)
    if raw is None:
        raise CRMResourceFetchError(
            CRMResourceFetchFailureKind.PERMANENT,
            "crm_resource_not_found",
        )
    notes = extract_collection(raw, "notes", fallback_id_key="id")
    processed = 0
    for note in notes:
        crm_lead_id = str(note.get("personId", ""))
        note_id = str(note.get("id", ""))
        if not crm_lead_id or not note_id:
            continue
        note_at = parse_iso(str(note.get("created", ""))) or occurred_at
        result = await process_crm_human_activity_event(
            event=CRMHumanActivityEvent(
                workspace_id=workspace_id,
                provider=_PROVIDER,
                provider_event_id=f"{event_id}:{note_id}",
                crm_lead_id=crm_lead_id,
                occurred_at=note_at,
                event_type="note_created",
                activity_type="Note",
                crm_activity_id=note_id,
                actor_agent_id=str(note.get("userId", "")) or None,
                changed_field=None,
                previous_value_redacted=None,
                new_value_redacted=None,
                payload_redacted={"fub_event_id": event_id, "note_id": note_id},
            ),
            lead_repository=bundle.lead_repository,
            external_event_repository=bundle.external_event_repository,
            lead_workflow_repository=bundle.lead_workflow_repository,
            workflow_transition_repository=bundle.workflow_transition_repository,
            paused_search_occurrence_repository=bundle.paused_search_occurrence_repository,
            temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
            now=occurred_at,
        )
        await _save_conversation_event(
            workspace_id=workspace_id,
            lead_id=result.lead_id,
            crm_activity_id=f"note:{note_id}",
            activity_type="note",
            occurred_at=note_at,
            resource=note,
            bundle=bundle,
        )
        processed += 1
    return processed, len(notes) - processed


async def handle_text_messages_created(
    workspace_id: UUID,
    event_id: str,
    occurred_at: datetime,
    uri: str,
    bundle: FollowUpBossWebhookEventBundle,
) -> tuple[int, int]:
    return await _handle_communication_created(
        workspace_id=workspace_id,
        event_id=event_id,
        occurred_at=occurred_at,
        uri=uri,
        bundle=bundle,
        collection_key="textMessages",
        activity_type="Text message",
        crm_activity_prefix="text_message",
        timestamp_fields=("created", "sent", "updated"),
    )


async def handle_calls_created(
    workspace_id: UUID,
    event_id: str,
    occurred_at: datetime,
    uri: str,
    bundle: FollowUpBossWebhookEventBundle,
) -> tuple[int, int]:
    return await _handle_communication_created(
        workspace_id=workspace_id,
        event_id=event_id,
        occurred_at=occurred_at,
        uri=uri,
        bundle=bundle,
        collection_key="calls",
        activity_type="Call",
        crm_activity_prefix="call",
        timestamp_fields=("created", "called", "updated"),
    )


async def handle_em_events_unsubscribed(
    workspace_id: UUID,
    event_id: str,
    occurred_at: datetime,
    uri: str,
    bundle: FollowUpBossWebhookEventBundle,
) -> tuple[int, int]:
    raw = await bundle.crm_client.fetch_resource_by_uri(workspace_id, uri)
    if raw is None:
        raise CRMResourceFetchError(
            CRMResourceFetchFailureKind.PERMANENT,
            "crm_resource_not_found",
        )
    events = extract_collection(raw, "emEvents")
    processed = 0
    for event in events:
        if event.get("type") != "unsubscribe":
            continue
        crm_lead_id = str(event.get("personId", ""))
        if not crm_lead_id:
            continue
        event_at = parse_iso(str(event.get("created", ""))) or occurred_at
        await process_contact_suppression_event(
            event=ContactSuppressionEvent(
                workspace_id=workspace_id,
                source_provider=_PROVIDER,
                provider_event_id=f"{event_id}:{crm_lead_id}",
                crm_provider=CRMProvider.FOLLOW_UP_BOSS,
                crm_lead_id=crm_lead_id,
                suppression_kind=ContactSuppressionKind.EMAIL_UNSUBSCRIBED,
                occurred_at=event_at,
                provider_message_id=None,
                payload_redacted={"fub_event_id": event_id},
            ),
            lead_repository=bundle.lead_repository,
            external_event_repository=bundle.external_event_repository,
            lead_workflow_repository=bundle.lead_workflow_repository,
            workflow_transition_repository=bundle.workflow_transition_repository,
            paused_search_occurrence_repository=bundle.paused_search_occurrence_repository,
            campaign_enrollment_repository=bundle.campaign_enrollment_repository,
            workspace_contact_policy_repository=bundle.workspace_contact_policy_repository,
            temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
            now=occurred_at,
        )
        processed += 1
    return processed, len(events) - processed


async def _handle_communication_created(
    *,
    workspace_id: UUID,
    event_id: str,
    occurred_at: datetime,
    uri: str,
    bundle: FollowUpBossWebhookEventBundle,
    collection_key: str,
    activity_type: str,
    crm_activity_prefix: str,
    timestamp_fields: tuple[str, ...],
) -> tuple[int, int]:
    raw = await bundle.crm_client.fetch_resource_by_uri(workspace_id, uri)
    if raw is None:
        raise CRMResourceFetchError(
            CRMResourceFetchFailureKind.PERMANENT,
            "crm_resource_not_found",
        )
    resources = extract_collection(raw, collection_key, fallback_id_key="id")
    processed = 0
    for resource in resources:
        crm_lead_id = str(resource.get("personId", ""))
        resource_id = str(resource.get("id", ""))
        if not crm_lead_id or not resource_id:
            continue
        activity_at = _parse_first_timestamp(resource, timestamp_fields) or occurred_at
        result = await process_crm_human_activity_event(
            event=CRMHumanActivityEvent(
                workspace_id=workspace_id,
                provider=_PROVIDER,
                provider_event_id=f"{event_id}:{resource_id}",
                crm_lead_id=crm_lead_id,
                occurred_at=activity_at,
                event_type="activity_created",
                activity_type=activity_type,
                crm_activity_id=f"{crm_activity_prefix}:{resource_id}",
                actor_agent_id=str(resource.get("userId", "")) or None,
                changed_field=None,
                previous_value_redacted=None,
                new_value_redacted=None,
                payload_redacted={"fub_event_id": event_id, "resource_id": resource_id},
            ),
            lead_repository=bundle.lead_repository,
            external_event_repository=bundle.external_event_repository,
            lead_workflow_repository=bundle.lead_workflow_repository,
            workflow_transition_repository=bundle.workflow_transition_repository,
            paused_search_occurrence_repository=bundle.paused_search_occurrence_repository,
            temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
            now=activity_at,
        )
        await _save_conversation_event(
            workspace_id=workspace_id,
            lead_id=result.lead_id,
            crm_activity_id=f"{crm_activity_prefix}:{resource_id}",
            activity_type=activity_type,
            occurred_at=activity_at,
            resource=resource,
            bundle=bundle,
        )
        processed += 1
    return processed, len(resources) - processed


async def _save_conversation_event(
    *,
    workspace_id: UUID,
    lead_id: UUID | None,
    crm_activity_id: str,
    activity_type: str,
    occurred_at: datetime,
    resource: dict[str, Any],
    bundle: FollowUpBossWebhookEventBundle,
) -> None:
    if lead_id is None:
        return
    await bundle.crm_conversation_event_repository.save(
        CrmConversationEvent(
            crm_conversation_event_id=uuid4(),
            workspace_id=workspace_id,
            lead_id=lead_id,
            crm_provider=_PROVIDER,
            crm_activity_id=crm_activity_id,
            activity_type=activity_type,
            occurred_at=occurred_at,
            created_at=occurred_at,
            updated_at=occurred_at,
            direction=(
                _communication_direction(resource)
                or (
                    CrmConversationEventDirection.INTERNAL
                    if activity_type.lower() == "note"
                    else None
                )
            ),
            content=_communication_content(resource),
            actor_agent_id=_optional_string(resource.get("userId")),
            actor_name=_first_string(resource.get("userName"), resource.get("fromName")),
            details={"source": "follow_up_boss_webhook"},
        )
    )


def _communication_direction(
    payload: dict[str, Any],
) -> CrmConversationEventDirection | None:
    if isinstance(payload.get("isIncoming"), bool):
        return (
            CrmConversationEventDirection.INBOUND
            if payload["isIncoming"]
            else CrmConversationEventDirection.OUTBOUND
        )
    direction = str(payload.get("direction", "")).strip().lower()
    try:
        return CrmConversationEventDirection(direction)
    except ValueError:
        return None


def _communication_content(payload: dict[str, Any]) -> str | None:
    return _first_string(
        payload.get("message"),
        payload.get("body"),
        payload.get("content"),
        payload.get("transcript"),
        payload.get("summary"),
        payload.get("note"),
        payload.get("description"),
    )


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            normalized = " ".join(value.split())
            if normalized:
                return normalized
    return None


def _optional_string(value: Any) -> str | None:
    return _first_string(value)


def _parse_first_timestamp(
    payload: dict[str, Any],
    candidate_fields: tuple[str, ...],
) -> datetime | None:
    for field_name in candidate_fields:
        value = payload.get(field_name)
        if value is None:
            continue
        parsed = parse_iso(str(value))
        if parsed is not None:
            return parsed
    return None
