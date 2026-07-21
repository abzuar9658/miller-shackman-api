from datetime import datetime
from uuid import UUID

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
        return 0, 1
    notes = extract_collection(raw, "notes", fallback_id_key="id")
    processed = 0
    for note in notes:
        crm_lead_id = str(note.get("personId", ""))
        note_id = str(note.get("id", ""))
        if not crm_lead_id or not note_id:
            continue
        note_at = parse_iso(str(note.get("created", ""))) or occurred_at
        await process_crm_human_activity_event(
            event=CRMHumanActivityEvent(
                workspace_id=workspace_id,
                provider=_PROVIDER,
                provider_event_id=f"{event_id}:{note_id}",
                crm_lead_id=crm_lead_id,
                occurred_at=note_at,
                event_type="note_created",
                activity_type="note",
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
            temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
            now=occurred_at,
        )
        processed += 1
    return processed, len(notes) - processed


async def handle_em_events_unsubscribed(
    workspace_id: UUID,
    event_id: str,
    occurred_at: datetime,
    uri: str,
    bundle: FollowUpBossWebhookEventBundle,
) -> tuple[int, int]:
    raw = await bundle.crm_client.fetch_resource_by_uri(workspace_id, uri)
    if raw is None:
        return 0, 1
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
            workspace_contact_policy_repository=bundle.workspace_contact_policy_repository,
            temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
            now=occurred_at,
        )
        processed += 1
    return processed, len(events) - processed
