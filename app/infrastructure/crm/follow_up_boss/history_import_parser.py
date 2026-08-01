"""Map the authenticated FUB people response into import events."""

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.domain.crm_history_imports import (
    CrmHistoryImportDirection,
    CrmHistoryImportEventPayload,
)

_TEXT_FIELDS = (
    ("lastReceivedTextBody", "lastReceivedTextId", "inbound"),
    ("lastSentTextBody", "lastSentTextId", "outbound"),
    ("lastTextBody", "lastTextId", None),
)
_COLLECTION_FIELDS = (
    "timeline",
    "events",
    "activities",
    "messages",
    "textMessages",
    "notes",
    "calls",
)


def parse_fub_people_response(
    payload: Mapping[str, Any], crm_lead_id: str, source_url: str | None = None
) -> tuple[CrmHistoryImportEventPayload, ...]:
    people = payload.get("people")
    person = next(
        (
            item
            for item in people or ()
            if isinstance(item, Mapping) and str(item.get("id")) == crm_lead_id
        ),
        None,
    )
    if person is None:
        return ()

    events: list[CrmHistoryImportEventPayload] = []
    for body_key, id_key, direction_value in _TEXT_FIELDS:
        body = _text(person.get(body_key))
        occurred_at = _parse_datetime(person.get("lastTextDate"))
        if body is None or occurred_at is None:
            continue
        direction = (
            CrmHistoryImportDirection(direction_value) if direction_value is not None else None
        )
        events.append(
            _event(
                activity_id=person.get(id_key),
                activity_type="text",
                direction=direction,
                content=body,
                occurred_at=occurred_at,
                actor_name=_text(person.get("lastSentTextUser"))
                if direction_value == "outbound"
                else None,
                details={
                    "source": "fub_people_response",
                    "source_field": body_key,
                    **_source_detail(source_url),
                },
            )
        )

    marketing_body = _text(person.get("lastReceivedMarketingTextBody"))
    marketing_at = _parse_datetime(person.get("lastReceivedMarketingText"))
    if marketing_body is not None and marketing_at is not None:
        events.append(
            _event(
                activity_id=person.get("lastReceivedMarketingTextId"),
                activity_type="marketing_text",
                direction=None,
                content=marketing_body,
                occurred_at=marketing_at,
                actor_name=None,
                details={
                    "source": "fub_people_response",
                    "source_field": "lastReceivedMarketingTextBody",
                    **_source_detail(source_url),
                },
            )
        )

    for collection_key in _COLLECTION_FIELDS:
        collection = payload.get(collection_key)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if isinstance(item, Mapping):
                event = _collection_event(item, source_url)
                if event is not None:
                    events.append(event)
    return _dedupe(events)


def _collection_event(
    item: Mapping[str, Any], source_url: str | None
) -> CrmHistoryImportEventPayload | None:
    content = _text(
        item.get("content") or item.get("body") or item.get("message") or item.get("text")
    )
    occurred_at = _parse_datetime(
        item.get("occurred_at") or item.get("occurredAt") or item.get("date") or item.get("created")
    )
    if content is None or occurred_at is None:
        return None
    direction_text = _text(item.get("direction"))
    direction = (
        CrmHistoryImportDirection(direction_text.lower())
        if direction_text
        and direction_text.lower() in {value.value for value in CrmHistoryImportDirection}
        else None
    )
    return _event(
        activity_id=item.get("id") or item.get("activityId"),
        activity_type=_text(item.get("type") or item.get("activity_type")) or "unknown",
        direction=direction,
        content=content,
        occurred_at=occurred_at,
        actor_name=_text(item.get("actor_name") or item.get("actorName") or item.get("user")),
        details={"source": "fub_people_response", **_source_detail(source_url)},
    )


def _event(
    *,
    activity_id: Any,
    activity_type: str,
    direction: CrmHistoryImportDirection | None,
    content: str,
    occurred_at: datetime,
    actor_name: str | None,
    details: Mapping[str, str],
) -> CrmHistoryImportEventPayload:
    external_id = _text(activity_id)
    source = "|".join(
        (
            external_id or "",
            activity_type,
            direction.value if direction else "",
            content,
            occurred_at.isoformat(),
        )
    )
    return CrmHistoryImportEventPayload(
        fingerprint=hashlib.sha256(source.encode()).hexdigest(),
        external_activity_id=external_id,
        activity_type=activity_type,
        direction=direction,
        content=content,
        occurred_at=occurred_at,
        actor_name=actor_name,
        details=details,
    )


def _dedupe(events: list[CrmHistoryImportEventPayload]) -> tuple[CrmHistoryImportEventPayload, ...]:
    seen: set[str] = set()
    result: list[CrmHistoryImportEventPayload] = []
    for event in events:
        key = event.external_activity_id or event.fingerprint
        if key not in seen:
            seen.add(key)
            result.append(event)
    return tuple(result)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def _text(value: Any) -> str | None:
    if isinstance(value, (int, str)) and not isinstance(value, bool):
        normalized = str(value).strip()
        return normalized or None
    return None


def _source_detail(source_url: str | None) -> dict[str, str]:
    return {"source_url": source_url} if source_url else {}
