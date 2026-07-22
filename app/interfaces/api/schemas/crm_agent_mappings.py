from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.interfaces.api.schemas.auth import UserResponse


class CRMAgentResponse(BaseModel):
    agent_record_id: UUID
    workspace_id: UUID
    crm_provider: str
    external_agent_id: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    is_active: bool
    last_seen_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WorkspaceAgentCRMMappingResponse(BaseModel):
    mapping_id: UUID
    workspace_id: UUID
    crm_agent_record_id: UUID
    app_user_id: UUID | None = None
    mapping_status: str
    resolution_source: str
    resolved_by_user_id: UUID | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CRMAgentMappingRowResponse(BaseModel):
    agent: CRMAgentResponse
    mapping: WorkspaceAgentCRMMappingResponse | None = None
    app_user: UserResponse | None = None


class CRMAgentMappingSummaryResponse(BaseModel):
    total_agents: int
    active_agents: int
    inactive_agents: int
    verified_count: int
    suggested_count: int
    overridden_count: int
    disputed_count: int
    unmapped_count: int
    last_agent_seen_at: datetime | None = None


class CRMAgentListResponse(BaseModel):
    status: str
    agents: list[CRMAgentResponse]
    summary: CRMAgentMappingSummaryResponse | None = None


class CRMAgentMappingListResponse(BaseModel):
    status: str
    rows: list[CRMAgentMappingRowResponse]
    summary: CRMAgentMappingSummaryResponse


class UpsertCRMAgentMappingRequest(BaseModel):
    crm_agent_record_id: UUID
    app_user_id: UUID


class PatchCRMAgentMappingRequest(BaseModel):
    app_user_id: UUID


class CRMAgentMappingMutationResponse(BaseModel):
    status: str
    mapping: WorkspaceAgentCRMMappingResponse | None = None


class CRMAgentDirectorySyncResultResponse(BaseModel):
    total_seen: int
    created_count: int
    updated_count: int
    deactivated_count: int
    suggested_mapping_count: int
    unmapped_mapping_count: int


class CRMAgentDirectorySyncResponse(BaseModel):
    status: str
    sync_result: CRMAgentDirectorySyncResultResponse | None = None
    summary: CRMAgentMappingSummaryResponse | None = None
