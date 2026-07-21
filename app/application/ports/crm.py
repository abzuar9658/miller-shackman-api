from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, Field


class CanonicalLead(BaseModel):
    workspace_id: UUID
    crm_lead_id: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    assigned_agent_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    custom_fields: dict[str, str] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CRMAgent(BaseModel):
    crm_agent_id: str
    name: str
    email: str | None = None


class CRMActivity(BaseModel):
    crm_activity_id: str
    activity_type: str
    timestamp: datetime
    content: str | None = None
    agent_id: str | None = None
    actor_name: str | None = None
    direction: str | None = None


class CRMClient(Protocol):
    supports_custom_fields: bool = True
    supports_tags: bool = True
    supports_notes: bool = True
    supports_webhooks: bool = False

    async def validate_connection(self, workspace_id: UUID) -> bool:
        raise NotImplementedError

    async def get_lead(self, workspace_id: UUID, crm_lead_id: str) -> CanonicalLead | None:
        raise NotImplementedError

    async def search_leads(
        self,
        workspace_id: UUID,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[CanonicalLead]:
        raise NotImplementedError

    async def get_recent_activity(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        limit: int = 50,
    ) -> list[CRMActivity]:
        raise NotImplementedError

    async def get_assigned_agent(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
    ) -> CRMAgent | None:
        raise NotImplementedError

    async def add_note(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        content: str,
        subject: str | None = None,
    ) -> None:
        raise NotImplementedError

    async def add_tag(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        tag: str,
    ) -> None:
        raise NotImplementedError

    async def remove_tag(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        tag: str,
    ) -> None:
        raise NotImplementedError

    async def update_custom_fields(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        fields: dict[str, str],
    ) -> None:
        raise NotImplementedError

    async def subscribe_to_events(
        self,
        workspace_id: UUID,
        webhook_url: str,
    ) -> None:
        raise NotImplementedError

    async def fetch_resource_by_uri(
        self,
        workspace_id: UUID,
        uri: str,
    ) -> dict[str, Any] | None:
        raise NotImplementedError
