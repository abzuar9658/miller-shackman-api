from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class HandoffResponse(BaseModel):
    handoff_id: UUID
    workspace_id: UUID
    lead_id: UUID
    campaign_id: UUID | None
    workflow_id: UUID | None
    conversation_id: UUID | None
    inbound_message_id: UUID | None
    assigned_agent_user_id: UUID | None
    assigned_agent_crm_id: str | None
    reason_code: str
    summary: str
    latest_inbound_text: str | None
    preferences: dict[str, str]
    status: str
    created_at: datetime
    notified_at: datetime | None
    acknowledged_at: datetime | None


class HandoffLeadResponse(BaseModel):
    lead_id: UUID
    display_name: str
    primary_email: str | None
    primary_phone: str | None


class HandoffSummaryResponse(BaseModel):
    handoff: HandoffResponse
    lead: HandoffLeadResponse
    assigned_agent_name: str | None
    recommended_next_action: str


class HandoffListResponse(BaseModel):
    status: str
    handoffs: list[HandoffSummaryResponse]


class HandoffDetailResponse(BaseModel):
    status: str
    handoff: HandoffResponse
    lead: HandoffLeadResponse
    assigned_agent_name: str | None
    recommended_next_action: str


class ReassignHandoffRequest(BaseModel):
    assigned_agent_user_id: UUID


class HandoffActionResponse(BaseModel):
    status: str
    handoff: HandoffResponse
