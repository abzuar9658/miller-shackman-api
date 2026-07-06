from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
import structlog

from app.application.ports.crm import CanonicalLead, CRMActivity, CRMAgent

logger = structlog.get_logger(__name__)


class FollowUpBossCRMClient:
    supports_custom_fields: bool = True
    supports_tags: bool = True
    supports_notes: bool = True
    supports_webhooks: bool = False

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

    async def get_recent_activity(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        limit: int = 50,
    ) -> list[CRMActivity]:
        response = await self._client.get(
            f"/people/{crm_lead_id}/activities",
            params={"limit": limit},
        )
        response.raise_for_status()
        data = response.json()
        return [self._map_activity(a) for a in data.get("activities", [])]

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

    async def add_note(self, workspace_id: UUID, crm_lead_id: str, content: str) -> None:
        await self._client.post(f"/people/{crm_lead_id}/notes", json={"note": content})

    async def add_tag(self, workspace_id: UUID, crm_lead_id: str, tag: str) -> None:
        await self._client.put(f"/people/{crm_lead_id}/tags", json={"tags": [tag]})

    async def remove_tag(self, workspace_id: UUID, crm_lead_id: str, tag: str) -> None:
        await self._client.request(
            "DELETE",
            f"/people/{crm_lead_id}/tags",
            json={"tags": [tag]},
        )

    async def update_custom_fields(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        fields: dict[str, str],
    ) -> None:
        await self._client.put(f"/people/{crm_lead_id}", json={"customFields": fields})

    async def subscribe_to_events(self, workspace_id: UUID, webhook_url: str) -> None:
        raise NotImplementedError

    def _map_person(self, workspace_id: UUID, payload: dict[str, Any]) -> CanonicalLead:
        return CanonicalLead(
            workspace_id=workspace_id,
            crm_lead_id=str(payload.get("id", "")),
            first_name=payload.get("firstName"),
            last_name=payload.get("lastName"),
            email=payload.get("email"),
            phone=payload.get("phone"),
            assigned_agent_id=str(payload.get("assignedTo"))
            if payload.get("assignedTo") is not None
            else None,
            tags=payload.get("tags", []) or [],
            custom_fields=payload.get("customFields", {}) or {},
            created_at=self._parse_datetime(payload.get("created")) or datetime.utcnow(),
            updated_at=self._parse_datetime(payload.get("updated")),
        )

    def _map_activity(self, payload: dict[str, Any]) -> CRMActivity:
        return CRMActivity(
            crm_activity_id=str(payload.get("id", "")),
            activity_type=payload.get("type", "unknown"),
            timestamp=self._parse_datetime(payload.get("created")) or datetime.utcnow(),
            content=payload.get("note") or payload.get("description"),
            agent_id=payload.get("userId"),
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
