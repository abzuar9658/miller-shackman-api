from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from app.domain.crm_sync import ExternalEvent, ExternalEventStatus
from app.domain.leads import CRMProvider

_PROVIDER = CRMProvider.FOLLOW_UP_BOSS.value


def parse_envelope(payload: Mapping[str, Any]) -> tuple[str, str, datetime, str] | None:
    event_id = payload.get("eventId")
    event_type = payload.get("event")
    event_created = payload.get("eventCreated")
    uri = payload.get("uri")
    if not isinstance(event_id, str) or not isinstance(event_type, str):
        return None
    if not isinstance(event_created, str) or not isinstance(uri, str):
        return None
    occurred_at = parse_iso(event_created)
    if occurred_at is None:
        return None
    return event_id, event_type, occurred_at, uri


def parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def envelope_event(
    workspace_id: UUID,
    event_id: str,
    event_type: str,
    occurred_at: datetime,
    payload: Mapping[str, Any],
    now: datetime,
    status: ExternalEventStatus,
) -> ExternalEvent:
    return ExternalEvent(
        external_event_id=uuid4(),
        workspace_id=workspace_id,
        provider=_PROVIDER,
        event_type=event_type,
        provider_event_id=event_id,
        crm_lead_id=None,
        lead_id=None,
        received_at=occurred_at,
        processed_at=now if status is not ExternalEventStatus.PENDING else None,
        status=status,
        payload_redacted=dict(payload),
        failure_reason=None,
        created_at=now,
        updated_at=now,
        attempt_count=1,
    )


def extract_collection(
    raw: Any,
    collection_key: str,
    fallback_id_key: str = "id",
) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if not isinstance(raw, dict):
        return []
    value = raw.get(collection_key)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    value_lower = raw.get(collection_key.lower())
    if isinstance(value_lower, list):
        return [item for item in value_lower if isinstance(item, dict)]
    if fallback_id_key and raw.get(fallback_id_key) is not None:
        return [raw]
    return []
