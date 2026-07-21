import asyncio
import html
import math
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, cast
from uuid import UUID

import httpx
import structlog

from app.application.ports.crm import CanonicalLead, CRMActivity, CRMAgent
from app.application.ports.crm_sync import CanonicalLeadSnapshotPage
from app.domain.crm_sync import CRMSyncLeadSort
from app.infrastructure.crm.follow_up_boss.lead_mapper import (
    map_follow_up_boss_person_to_canonical_lead,
)

logger = structlog.get_logger(__name__)
TAG_RE = re.compile(r"<[^>]+>")


class FollowUpBossCRMClient:
    supports_custom_fields: bool = True
    supports_tags: bool = True
    supports_notes: bool = True
    supports_webhooks: bool = True
    _activity_retry_max_attempts: int = 3
    _activity_retry_base_delay_seconds: float = 1.0
    _activity_retry_max_delay_seconds: float = 8.0

    def __init__(self, api_key: str, base_url: str = "https://api.followupboss.com/v1") -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = httpx.BasicAuth(api_key, "")
        self._client = httpx.AsyncClient(auth=self._auth, base_url=self._base_url)

    async def validate_connection(self, workspace_id: UUID) -> bool:
        response = await self._client.get("/me")
        return response.status_code == 200

    async def get_lead(self, workspace_id: UUID, crm_lead_id: str) -> CanonicalLead | None:
        response = await self._client.get(f"/people/{crm_lead_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return self._map_person(workspace_id, response.json())

    async def search_leads(
        self,
        workspace_id: UUID,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[CanonicalLead]:
        params: dict[str, Any] = {"limit": limit}
        if tag:
            params["tag"] = tag
        response = await self._client.get("/people", params=params)
        response.raise_for_status()
        data = response.json()
        return [self._map_person(workspace_id, p) for p in data.get("people", [])]

    async def list_lead_snapshots(
        self,
        *,
        workspace_id: UUID,
        page_size: int = 100,
        cursor: str | None = None,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
        sort_by: CRMSyncLeadSort | None = None,
        mapped_custom_field_keys: tuple[str, ...] = (),
    ) -> CanonicalLeadSnapshotPage:
        params: dict[str, Any] = {"limit": max(1, min(page_size, 100))}
        if cursor:
            params["next"] = cursor
        if updated_after is not None:
            params["updatedAfter"] = self._format_datetime(updated_after)
        if updated_before is not None:
            params["updatedBefore"] = self._format_datetime(updated_before)
        if sort_by is not None:
            params["sort"] = f"-{sort_by.value}"

        response = await self._client.get("/people", params=params)
        response.raise_for_status()
        data = response.json()
        page_now = datetime.now(UTC)
        people = data.get("people", [])
        leads = tuple(
            map_follow_up_boss_person_to_canonical_lead(
                workspace_id=workspace_id,
                payload=person,
                now=page_now,
                mapped_custom_field_keys=mapped_custom_field_keys,
            )
            for person in people
            if isinstance(person, dict)
        )
        metadata = data.get("_metadata") if isinstance(data.get("_metadata"), dict) else {}
        next_cursor = metadata.get("next") or data.get("next")
        return CanonicalLeadSnapshotPage(
            leads=leads,
            next_cursor=str(next_cursor) if next_cursor else None,
        )

    async def get_recent_activity(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        limit: int = 50,
    ) -> list[CRMActivity]:
        _ = workspace_id
        collections: list[list[CRMActivity]] = []
        requests = (
            self._activity_collection_request(
                label="events",
                path="/events",
                params={"personId": crm_lead_id, "limit": limit},
                collection_key="events",
                mapper=lambda payload: self._map_event_activity(payload),
            ),
            self._activity_collection_request(
                label="notes",
                path="/notes",
                params={"personId": crm_lead_id, "limit": limit},
                collection_key="notes",
                mapper=lambda payload: self._map_note_activity(payload),
            ),
            self._activity_collection_request(
                label="text_messages",
                path="/textMessages",
                params={"personId": crm_lead_id, "limit": limit},
                collection_key="textMessages",
                mapper=lambda payload: self._map_text_message_activity(payload),
            ),
            self._activity_collection_request(
                label="calls",
                path="/calls",
                params={"personId": crm_lead_id, "limit": limit},
                collection_key="calls",
                mapper=lambda payload: self._map_call_activity(payload),
            ),
        )
        for request in requests:
            collections.append(await self._fetch_activity_collection(**request))

        merged = sorted(
            [activity for collection in collections for activity in collection],
            key=lambda activity: activity.timestamp,
            reverse=True,
        )
        deduped: list[CRMActivity] = []
        seen_ids: set[str] = set()
        for activity in merged:
            if activity.crm_activity_id in seen_ids:
                continue
            seen_ids.add(activity.crm_activity_id)
            deduped.append(activity)
            if len(deduped) >= limit:
                break
        return deduped

    def _activity_collection_request(
        self,
        *,
        label: str,
        path: str,
        params: dict[str, Any],
        collection_key: str,
        mapper: Any,
    ) -> dict[str, Any]:
        return {
            "label": label,
            "path": path,
            "params": params,
            "collection_key": collection_key,
            "mapper": mapper,
        }

    async def get_assigned_agent(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
    ) -> CRMAgent | None:
        lead = await self.get_lead(workspace_id, crm_lead_id)
        if lead is None or not lead.assigned_agent_id:
            return None
        response = await self._client.get(f"/users/{lead.assigned_agent_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return self._map_agent(response.json())

    async def add_note(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        content: str,
        subject: str | None = None,
    ) -> None:
        payload: dict[str, object] = {"personId": int(crm_lead_id), "body": content}
        if subject is not None:
            payload["subject"] = subject
        response = await self._client.post("/notes", json=payload)
        response.raise_for_status()

    async def add_tag(self, workspace_id: UUID, crm_lead_id: str, tag: str) -> None:
        response = await self._client.put(f"/people/{crm_lead_id}/tags", json={"tags": [tag]})
        response.raise_for_status()

    async def remove_tag(self, workspace_id: UUID, crm_lead_id: str, tag: str) -> None:
        response = await self._client.request(
            "DELETE",
            f"/people/{crm_lead_id}/tags",
            json={"tags": [tag]},
        )
        response.raise_for_status()

    async def update_custom_fields(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        fields: dict[str, str],
    ) -> None:
        response = await self._client.put(f"/people/{crm_lead_id}", json={"customFields": fields})
        response.raise_for_status()

    async def subscribe_to_events(self, workspace_id: UUID, webhook_url: str) -> None:
        raise NotImplementedError

    async def fetch_resource_by_uri(
        self,
        workspace_id: UUID,
        uri: str,
    ) -> dict[str, Any] | None:
        response = await self._client.get(uri)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return cast("dict[str, Any]", response.json())

    def _map_person(self, workspace_id: UUID, payload: dict[str, Any]) -> CanonicalLead:
        return CanonicalLead(
            workspace_id=workspace_id,
            crm_lead_id=str(payload.get("id", "")),
            first_name=payload.get("firstName"),
            last_name=payload.get("lastName"),
            email=payload.get("email"),
            phone=payload.get("phone"),
            assigned_agent_id=self._assigned_agent_id(payload),
            tags=payload.get("tags", []) or [],
            custom_fields=payload.get("customFields", {}) or {},
            created_at=self._parse_datetime(payload.get("created")) or datetime.utcnow(),
            updated_at=self._parse_datetime(payload.get("updated")),
        )

    def _assigned_agent_id(self, payload: dict[str, Any]) -> str | None:
        assigned_user_id = payload.get("assignedUserId")
        if assigned_user_id is not None:
            normalized = str(assigned_user_id).strip()
            return normalized or None

        assigned_to = payload.get("assignedTo")
        if isinstance(assigned_to, int):
            return str(assigned_to)
        if isinstance(assigned_to, str):
            normalized = assigned_to.strip()
            return normalized if normalized.isdigit() else None
        return None

    async def _fetch_activity_collection(
        self,
        *,
        label: str,
        path: str,
        params: dict[str, Any],
        collection_key: str,
        mapper: Any,
    ) -> list[CRMActivity]:
        attempt = 1
        while True:
            try:
                response = await self._client.get(path, params=params)
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and attempt < self._activity_retry_max_attempts:
                    delay_seconds = self._retry_after_seconds(
                        exc.response.headers.get("Retry-After")
                    )
                    if delay_seconds is None:
                        delay_seconds = self._backoff_delay_seconds(attempt)
                    logger.warning(
                        "Follow Up Boss CRM activity collection rate limited; retrying",
                        collection=label,
                        path=path,
                        attempt=attempt,
                        retry_in_seconds=delay_seconds,
                    )
                    await asyncio.sleep(delay_seconds)
                    attempt += 1
                    continue
                logger.warning(
                    "Failed to fetch Follow Up Boss CRM activity collection",
                    collection=label,
                    path=path,
                    error=str(exc),
                    attempt=attempt,
                )
                return []
            except Exception as exc:
                logger.warning(
                    "Failed to fetch Follow Up Boss CRM activity collection",
                    collection=label,
                    path=path,
                    error=str(exc),
                    attempt=attempt,
                )
                return []

        data = response.json()
        items = data.get(collection_key, [])
        if not isinstance(items, list):
            return []
        return [mapper(item) for item in items if isinstance(item, dict)]

    def _retry_after_seconds(self, value: str | None) -> float | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return max(float(stripped), 0.0)
        except ValueError:
            pass
        try:
            retry_at = parsedate_to_datetime(stripped)
        except (TypeError, ValueError, IndexError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max((retry_at - datetime.now(UTC)).total_seconds(), 0.0)

    def _backoff_delay_seconds(self, attempt: int) -> float:
        delay = self._activity_retry_base_delay_seconds * math.pow(2, max(attempt - 1, 0))
        return min(delay, self._activity_retry_max_delay_seconds)

    def _map_event_activity(self, payload: dict[str, Any]) -> CRMActivity:
        return CRMActivity(
            crm_activity_id=str(payload.get("id", "")),
            activity_type=payload.get("type", "unknown"),
            timestamp=self._parse_datetime(payload.get("created")) or datetime.utcnow(),
            content=self._normalize_content(
                payload.get("message") or payload.get("note") or payload.get("description"),
            ),
            agent_id=(
                str(payload.get("userId")) if payload.get("userId") is not None else None
            ),
            actor_name=self._first_non_empty(payload.get("userName"), payload.get("user")),
        )

    def _map_note_activity(self, payload: dict[str, Any]) -> CRMActivity:
        return CRMActivity(
            crm_activity_id=f"note:{payload.get('id', '')}",
            activity_type="Note",
            timestamp=self._parse_datetime(payload.get("created") or payload.get("updated"))
            or datetime.utcnow(),
            content=self._normalize_content(
                payload.get("body") or payload.get("note") or payload.get("description"),
                is_html=bool(payload.get("isHtml")),
            ),
            agent_id=str(payload.get("userId")) if payload.get("userId") is not None else None,
            actor_name=self._first_non_empty(
                payload.get("userName"),
                payload.get("createdByName"),
            ),
            direction="internal",
        )

    def _map_text_message_activity(self, payload: dict[str, Any]) -> CRMActivity:
        is_incoming = self._is_incoming(payload)
        return CRMActivity(
            crm_activity_id=f"text_message:{payload.get('id', '')}",
            activity_type="Text message",
            timestamp=self._parse_datetime(
                payload.get("created") or payload.get("sent") or payload.get("updated"),
            )
            or datetime.utcnow(),
            content=self._normalize_content(payload.get("message") or payload.get("body")),
            agent_id=str(payload.get("userId")) if payload.get("userId") is not None else None,
            actor_name=self._first_non_empty(payload.get("userName"), payload.get("fromName")),
            direction="inbound" if is_incoming else "outbound",
        )

    def _map_call_activity(self, payload: dict[str, Any]) -> CRMActivity:
        is_incoming = self._is_incoming(payload)
        return CRMActivity(
            crm_activity_id=f"call:{payload.get('id', '')}",
            activity_type="Call",
            timestamp=self._parse_datetime(
                payload.get("created") or payload.get("called") or payload.get("updated"),
            )
            or datetime.utcnow(),
            content=self._normalize_content(payload.get("note") or payload.get("description")),
            agent_id=str(payload.get("userId")) if payload.get("userId") is not None else None,
            actor_name=self._first_non_empty(payload.get("userName"), payload.get("fromName")),
            direction="inbound" if is_incoming else "outbound",
        )

    def _map_agent(self, payload: dict[str, Any]) -> CRMAgent:
        return CRMAgent(
            crm_agent_id=str(payload.get("id", "")),
            name=payload.get("name", ""),
            email=payload.get("email"),
        )

    def _parse_datetime(self, value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            logger.warning("Unable to parse CRM datetime", value=value)
            return None

    def _format_datetime(self, value: datetime) -> str:
        return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _normalize_content(self, value: Any, *, is_html: bool = False) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = html.unescape(value)
        if is_html:
            normalized = TAG_RE.sub(" ", normalized)
        normalized = " ".join(normalized.split())
        return normalized or None

    def _first_non_empty(self, *values: Any) -> str | None:
        for value in values:
            if not isinstance(value, str):
                continue
            normalized = value.strip()
            if normalized:
                return normalized
        return None

    def _is_incoming(self, payload: dict[str, Any]) -> bool:
        if isinstance(payload.get("isIncoming"), bool):
            return bool(payload["isIncoming"])
        direction = self._first_non_empty(payload.get("direction"))
        return direction == "inbound"
