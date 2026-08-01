from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.domain.common.ids import (
    CRMAgentRecordId,
    UserId,
    WorkspaceAgentCRMMappingId,
    WorkspaceId,
)
from app.domain.leads import CRMProvider


class CRMAgentMappingStatus(StrEnum):
    SUGGESTED = "suggested"
    VERIFIED = "verified"
    OVERRIDDEN = "overridden"
    DISPUTED = "disputed"
    UNMAPPED = "unmapped"


class CRMAgentMappingResolutionSource(StrEnum):
    AUTO_EMAIL_MATCH = "auto_email_match"
    ADMIN_MANUAL = "admin_manual"
    SYSTEM_UNLINKED = "system_unlinked"


@dataclass(frozen=True)
class CRMAgent:
    agent_record_id: CRMAgentRecordId
    workspace_id: WorkspaceId
    crm_provider: CRMProvider
    external_agent_id: str
    created_at: datetime
    updated_at: datetime
    name: str | None = None
    email: str | None = None
    email_normalized: str | None = None
    phone: str | None = None
    is_active: bool = True
    last_seen_at: datetime | None = None
    raw_payload: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkspaceAgentCRMMapping:
    mapping_id: WorkspaceAgentCRMMappingId
    workspace_id: WorkspaceId
    crm_agent_record_id: CRMAgentRecordId
    mapping_status: CRMAgentMappingStatus
    resolution_source: CRMAgentMappingResolutionSource
    created_at: datetime
    updated_at: datetime
    app_user_id: UserId | None = None
    resolved_by_user_id: UserId | None = None
    resolved_at: datetime | None = None


@dataclass(frozen=True)
class WorkspaceAgentMappingConfig:
    workspace_id: WorkspaceId
    created_at: datetime
    updated_at: datetime
    unmapped_assignment_fallback_user_id: UserId | None = None
