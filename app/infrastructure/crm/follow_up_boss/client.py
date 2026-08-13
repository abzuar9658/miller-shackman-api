import asyncio
import html
import math
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, cast
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse
from uuid import UUID

import httpx
import structlog

from app.application.ports.crm import (
    CanonicalLead,
    CRMActivity,
    CRMActivityTranscriptSegment,
    CRMAgent,
    CRMAgentDirectoryEntry,
    CRMResourceFetchError,
    CRMResourceFetchFailureKind,
)
from app.application.ports.crm_sync import CanonicalLeadSnapshotPage
from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.compliance.contactability import ContactChannel
from app.domain.crm_sync import CRMSyncLeadSort
from app.domain.leads import CanonicalLeadRecord
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

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.followupboss.com/v1",
        *,
        inbox_sync_enabled: bool = False,
        inbox_app_id: str | None = None,
        inbox_sender_name: str = "AI Assistant",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = httpx.BasicAuth(api_key, "")
        self._client = httpx.AsyncClient(
            auth=self._auth,
            base_url=self._base_url,
            timeout=timeout_seconds,
        )
        self._inbox_sync_enabled = inbox_sync_enabled
        self._inbox_app_id = inbox_app_id.strip() if inbox_app_id else None
        self._inbox_sender_name = inbox_sender_name.strip() or "AI Assistant"

    async def validate_connection(self, workspace_id: UUID) -> bool:
        response = await self._client.get("/me")
        return response.status_code == 200

    async def get_lead(self, workspace_id: UUID, crm_lead_id: str) -> CanonicalLead | None:
        response = await self._client.get(f"/people/{crm_lead_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return self._map_person(workspace_id, response.json())

    async def get_lead_snapshot(
        self,
        *,
        workspace_id: UUID,
        crm_lead_id: str,
        mapped_custom_field_keys: tuple[str, ...] = (),
    ) -> CanonicalLeadRecord | None:
        response = await self._client.get(f"/people/{crm_lead_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return self._map_canonical_lead_snapshot(
            workspace_id=workspace_id,
            payload=response.json(),
            mapped_custom_field_keys=mapped_custom_field_keys,
        )

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

    async def list_agents(self, workspace_id: UUID) -> list[CRMAgentDirectoryEntry]:
        _ = workspace_id
        next_cursor: str | None = None
        agents: list[CRMAgentDirectoryEntry] = []
        while True:
            params: dict[str, Any] = {"limit": 100}
            if next_cursor:
                params["next"] = next_cursor

            response = await self._client.get("/users", params=params)
            response.raise_for_status()
            data = response.json()
            users = data.get("users", [])
            if isinstance(users, list):
                agents.extend(
                    self._map_agent_directory_entry(user)
                    for user in users
                    if isinstance(user, dict)
                )

            metadata = data.get("_metadata") if isinstance(data.get("_metadata"), dict) else {}
            next_value = metadata.get("next") or data.get("next")
            if not next_value:
                break
            next_cursor = str(next_value)

        return agents

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
            self._map_canonical_lead_snapshot(
                workspace_id=workspace_id,
                payload=person,
                mapped_custom_field_keys=mapped_custom_field_keys,
                now=page_now,
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

    async def get_lead_url(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
    ) -> str | None:
        _ = workspace_id
        return f"https://app.followupboss.com/2/people/{quote(crm_lead_id, safe='')}"

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

    async def publish_outbound_message(
        self,
        *,
        lead: CanonicalLeadRecord,
        outbound_message: OutboundMessage,
    ) -> bool:
        if not self._inbox_sync_enabled or not self._inbox_app_id:
            return False
        if outbound_message.channel != ContactChannel.SMS:
            return False

        person_id = _parse_fub_int_id(lead.crm_lead_id)
        owner_user_id = _parse_fub_int_id(lead.assigned_agent_crm_id)
        if person_id is None or owner_user_id is None:
            return False

        payload: dict[str, object] = {
            "externalConversationId": _inbox_external_conversation_id(lead, outbound_message),
            "externalMessageId": str(outbound_message.message_id),
            "message": outbound_message.body,
            "isIncoming": False,
            "sender": {"name": self._inbox_sender_name},
            "isAutomation": True,
            "person": {"id": person_id},
            "owner": {"userId": owner_user_id},
            "sentAt": (outbound_message.sent_at or outbound_message.updated_at).isoformat(),
        }
        if outbound_message.subject:
            payload["subject"] = outbound_message.subject

        response = await self._client.post(
            f"/inboxApps/{quote(self._inbox_app_id, safe='')}/message",
            json=payload,
        )
        response.raise_for_status()
        return True

    async def add_tag(self, workspace_id: UUID, crm_lead_id: str, tag: str) -> None:
        response = await self._client.put(
            f"/people/{crm_lead_id}",
            params={"mergeTags": "true"},
            json={"tags": [tag]},
        )
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
        _ = workspace_id
        try:
            response = await self._client.get(self._with_follow_up_boss_people_fields(uri))
        except httpx.RequestError as exc:
            raise CRMResourceFetchError(
                CRMResourceFetchFailureKind.TRANSIENT,
                "crm_resource_transport_failure",
            ) from exc
        if response.status_code == 404:
            raise CRMResourceFetchError(
                CRMResourceFetchFailureKind.PERMANENT,
                "crm_resource_not_found",
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise CRMResourceFetchError(
                CRMResourceFetchFailureKind.TRANSIENT,
                f"crm_resource_http_{response.status_code}",
            )
        if response.status_code >= 400:
            raise CRMResourceFetchError(
                CRMResourceFetchFailureKind.PERMANENT,
                f"crm_resource_http_{response.status_code}",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise CRMResourceFetchError(
                CRMResourceFetchFailureKind.UNKNOWN,
                "crm_resource_invalid_json",
            ) from exc
        if not isinstance(payload, dict):
            raise CRMResourceFetchError(
                CRMResourceFetchFailureKind.UNKNOWN,
                "crm_resource_invalid_payload",
            )
        return cast("dict[str, Any]", payload)

    def _with_follow_up_boss_people_fields(self, uri: str) -> str:
        parsed = urlparse(uri)
        if "/people" not in parsed.path:
            return uri

        params = parse_qsl(parsed.query, keep_blank_values=True)
        if any(key == "fields" for key, _ in params):
            return uri

        params.append(("fields", "allFields"))
        return urlunparse(parsed._replace(query=urlencode(params, doseq=True)))

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
            agent_id=(str(payload.get("userId")) if payload.get("userId") is not None else None),
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
        transcript_segments = self._extract_transcript_segments(payload)
        return CRMActivity(
            crm_activity_id=f"call:{payload.get('id', '')}",
            activity_type="Call",
            timestamp=self._parse_datetime(
                payload.get("created") or payload.get("called") or payload.get("updated"),
            )
            or datetime.utcnow(),
            content=self._call_content(payload, transcript_segments),
            agent_id=str(payload.get("userId")) if payload.get("userId") is not None else None,
            actor_name=self._first_non_empty(payload.get("userName"), payload.get("fromName")),
            direction="inbound" if is_incoming else "outbound",
            details=self._call_activity_details(payload, transcript_segments=transcript_segments),
            transcript_segments=transcript_segments,
        )

    def _map_agent(self, payload: dict[str, Any]) -> CRMAgent:
        return CRMAgent(
            crm_agent_id=str(payload.get("id", "")),
            name=payload.get("name", ""),
            email=payload.get("email"),
        )

    def _map_agent_directory_entry(self, payload: dict[str, Any]) -> CRMAgentDirectoryEntry:
        return CRMAgentDirectoryEntry(
            crm_agent_id=str(payload.get("id", "")),
            name=self._agent_name(payload),
            email=self._first_non_empty(payload.get("email")),
            phone=self._first_non_empty(
                payload.get("phone"),
                payload.get("mobilePhone"),
                payload.get("cellPhone"),
            ),
            is_active=self._agent_is_active(payload),
            raw_payload=payload,
        )

    def _agent_name(self, payload: dict[str, Any]) -> str | None:
        name = self._first_non_empty(payload.get("name"), payload.get("fullName"))
        if name is not None:
            return name
        first_name = self._first_non_empty(payload.get("firstName"))
        last_name = self._first_non_empty(payload.get("lastName"))
        parts = tuple(part for part in (first_name, last_name) if part is not None)
        if not parts:
            return None
        return " ".join(parts)

    def _agent_is_active(self, payload: dict[str, Any]) -> bool:
        if isinstance(payload.get("isActive"), bool):
            return bool(payload["isActive"])
        status = self._first_non_empty(payload.get("status"))
        if status is None:
            return True
        return status.lower() not in {"inactive", "disabled", "deleted", "archived"}

    def _map_canonical_lead_snapshot(
        self,
        *,
        workspace_id: UUID,
        payload: dict[str, Any],
        mapped_custom_field_keys: tuple[str, ...] = (),
        now: datetime | None = None,
    ) -> CanonicalLeadRecord:
        return map_follow_up_boss_person_to_canonical_lead(
            workspace_id=workspace_id,
            payload=payload,
            now=now or datetime.now(UTC),
            mapped_custom_field_keys=mapped_custom_field_keys,
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

    def _call_content(
        self,
        payload: dict[str, Any],
        transcript_segments: list[CRMActivityTranscriptSegment],
    ) -> str | None:
        transcript_text = self._transcript_content(transcript_segments)
        if transcript_text is not None:
            return transcript_text
        return self._normalize_content(
            self._first_non_empty(
                payload.get("transcript"),
                payload.get("transcription"),
                payload.get("summary"),
                payload.get("note"),
                payload.get("description"),
            )
        )

    def _call_activity_details(
        self,
        payload: dict[str, Any],
        *,
        transcript_segments: list[CRMActivityTranscriptSegment],
    ) -> dict[str, str | int | float | bool | None]:
        details: dict[str, str | int | float | bool | None] = {}
        duration_seconds = self._first_number(
            payload.get("duration"),
            payload.get("durationSeconds"),
            payload.get("callDuration"),
            payload.get("talkTime"),
        )
        if duration_seconds is not None:
            details["duration_seconds"] = duration_seconds
        call_outcome = self._first_non_empty(
            payload.get("outcome"),
            payload.get("callOutcome"),
            payload.get("disposition"),
            payload.get("status"),
            payload.get("result"),
        )
        if call_outcome is not None:
            details["call_outcome"] = call_outcome
        if self._has_non_empty(
            payload.get("recordingUrl"),
            payload.get("recording_url"),
            payload.get("recording"),
        ):
            details["recording_available"] = True
        if len(transcript_segments) > 0:
            details["transcript_segment_count"] = len(transcript_segments)
        return details

    def _extract_transcript_segments(
        self,
        payload: dict[str, Any],
    ) -> list[CRMActivityTranscriptSegment]:
        for candidate in (
            payload.get("transcriptSegments"),
            payload.get("transcript_segments"),
            payload.get("segments"),
            payload.get("utterances"),
            payload.get("transcript"),
        ):
            segments = self._coerce_transcript_segments(candidate)
            if len(segments) > 0:
                return segments
        return []

    def _coerce_transcript_segments(self, value: Any) -> list[CRMActivityTranscriptSegment]:
        if isinstance(value, dict):
            nested = value.get("segments") or value.get("utterances") or value.get("items")
            return self._coerce_transcript_segments(nested)
        if not isinstance(value, list):
            return []
        segments: list[CRMActivityTranscriptSegment] = []
        for entry in value:
            if isinstance(entry, str):
                text = self._normalize_content(entry)
                if text is None:
                    continue
                segments.append(CRMActivityTranscriptSegment(text=text))
                continue
            if not isinstance(entry, dict):
                continue
            text = self._normalize_content(
                entry.get("text")
                or entry.get("message")
                or entry.get("body")
                or entry.get("content")
            )
            if text is None:
                continue
            segments.append(
                CRMActivityTranscriptSegment(
                    text=text,
                    speaker_name=self._first_non_empty(
                        entry.get("speakerName"),
                        entry.get("speaker"),
                        entry.get("name"),
                        entry.get("fromName"),
                        entry.get("userName"),
                    ),
                    speaker_role=self._first_non_empty(
                        entry.get("speakerRole"),
                        entry.get("role"),
                        entry.get("participantType"),
                        entry.get("direction"),
                    ),
                    started_at=self._parse_datetime(
                        entry.get("startedAt")
                        or entry.get("startTime")
                        or entry.get("timestamp")
                        or entry.get("created")
                    ),
                )
            )
        return segments

    def _transcript_content(
        self,
        transcript_segments: list[CRMActivityTranscriptSegment],
    ) -> str | None:
        if len(transcript_segments) == 0:
            return None
        lines = [
            f"{segment.speaker_name}: {segment.text}"
            if segment.speaker_name is not None
            else segment.text
            for segment in transcript_segments
        ]
        return "\n".join(lines)

    def _first_non_empty(self, *values: Any) -> str | None:
        for value in values:
            if not isinstance(value, str):
                continue
            normalized = value.strip()
            if normalized:
                return normalized
        return None

    def _first_number(self, *values: Any) -> int | float | None:
        for value in values:
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, (int, float)):
                return int(value) if isinstance(value, float) and value.is_integer() else value
            if not isinstance(value, str):
                continue
            normalized = value.strip()
            if not normalized:
                continue
            try:
                parsed = float(normalized)
            except ValueError:
                continue
            return int(parsed) if parsed.is_integer() else parsed
        return None

    def _has_non_empty(self, *values: Any) -> bool:
        return self._first_non_empty(*values) is not None

    def _is_incoming(self, payload: dict[str, Any]) -> bool:
        if isinstance(payload.get("isIncoming"), bool):
            return bool(payload["isIncoming"])
        direction = self._first_non_empty(payload.get("direction"))
        return direction == "inbound"


def _parse_fub_int_id(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _inbox_external_conversation_id(
    lead: CanonicalLeadRecord,
    outbound_message: OutboundMessage,
) -> str:
    return f"lead:{lead.crm_lead_id}:channel:{outbound_message.channel.value}"
