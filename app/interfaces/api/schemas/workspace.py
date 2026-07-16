from datetime import time
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.domain.compliance import SmsComplianceState
from app.domain.identity import UserStatus, WorkspaceMembershipRole, WorkspaceMembershipStatus
from app.domain.workspace_automation import WorkspaceAutomationStatus
from app.interfaces.api.schemas.auth import (
    MembershipResponse,
    UserResponse,
    WorkspaceResponse,
)


class CreateWorkspaceRequest(BaseModel):
    name: str
    default_timezone: str


class CreateWorkspaceResponse(BaseModel):
    status: str
    workspace: WorkspaceResponse | None = None
    membership: MembershipResponse | None = None


class WorkspaceUserResponse(BaseModel):
    user: UserResponse
    membership: MembershipResponse
    invitation_id: UUID | None = None


class ListWorkspaceUsersResponse(BaseModel):
    status: str
    users: list[WorkspaceUserResponse]


class InviteWorkspaceUserRequest(BaseModel):
    email: EmailStr
    role: WorkspaceMembershipRole
    full_name: str


class InviteWorkspaceUserResponse(BaseModel):
    status: str
    user: UserResponse | None = None
    membership: MembershipResponse | None = None


class ResendInvitationResponse(BaseModel):
    status: str
    invitation_id: UUID | None = None


class UpdateWorkspaceMembershipRequest(BaseModel):
    role: WorkspaceMembershipRole | None = None
    membership_status: WorkspaceMembershipStatus | None = None


class UpdateWorkspaceMembershipResponse(BaseModel):
    status: str
    membership: MembershipResponse | None = None


class UpdateUserStatusRequest(BaseModel):
    user_status: UserStatus


class UpdateUserStatusResponse(BaseModel):
    status: str
    user: UserResponse | None = None


class WorkspaceContactPolicyResponse(BaseModel):
    workspace_id: UUID
    sms_compliance_state: str
    quiet_hours_enabled: bool = True
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    inbound_email_address: str | None = None


class WorkspaceHandoffConfigResponse(BaseModel):
    workspace_id: UUID
    fallback_recipient_email: str | None = None
    crm_handoff_tag: str | None = None
    crm_custom_fields: dict[str, str]


class WorkspaceCRMSyncConfigResponse(BaseModel):
    workspace_id: UUID
    crm_sync_enabled: bool
    crm_sync_interval_seconds: int


class WorkspaceLLMConfigResponse(BaseModel):
    workspace_id: UUID
    openrouter_model: str
    allowed_openrouter_models: list[str]


class WorkspaceOperationalControlResponse(BaseModel):
    workspace_id: UUID
    automation_status: str
    pause_reason: str | None = None


class WorkspaceSettingsResponse(BaseModel):
    status: str
    workspace: WorkspaceResponse | None = None
    contact_policy: WorkspaceContactPolicyResponse | None = None
    crm_sync_config: WorkspaceCRMSyncConfigResponse | None = None
    llm_config: WorkspaceLLMConfigResponse | None = None
    handoff_config: WorkspaceHandoffConfigResponse | None = None
    operational_control: WorkspaceOperationalControlResponse | None = None


class UpdateWorkspaceContactPolicyRequest(BaseModel):
    sms_compliance_state: SmsComplianceState
    quiet_hours_enabled: bool = True
    quiet_hours_start: time
    quiet_hours_end: time
    inbound_email_address: EmailStr | None = None

    @field_validator("quiet_hours_end")
    @classmethod
    def quiet_hours_end_must_be_after_start(cls, value: time, info: object) -> time:
        data = getattr(info, "data", {})
        start = data.get("quiet_hours_start")
        if isinstance(start, time) and value <= start:
            raise ValueError("quiet_hours_end must be after quiet_hours_start")
        return value


class UpdateWorkspaceContactPolicyResponse(BaseModel):
    status: str
    contact_policy: WorkspaceContactPolicyResponse | None = None


class UpdateWorkspaceHandoffConfigRequest(BaseModel):
    fallback_recipient_email: EmailStr | None = None
    crm_handoff_tag: str | None = Field(default=None, max_length=255)
    crm_custom_fields: dict[str, str] = Field(default_factory=dict)


class UpdateWorkspaceHandoffConfigResponse(BaseModel):
    status: str
    handoff_config: WorkspaceHandoffConfigResponse | None = None


class UpdateWorkspaceCRMSyncConfigRequest(BaseModel):
    crm_sync_enabled: bool
    crm_sync_interval_seconds: int = Field(ge=60, le=86400)

    @field_validator("crm_sync_interval_seconds")
    @classmethod
    def interval_must_be_whole_minutes(cls, value: int) -> int:
        if value % 60 != 0:
            raise ValueError("crm_sync_interval_seconds must be a whole number of minutes")
        return value


class UpdateWorkspaceCRMSyncConfigResponse(BaseModel):
    status: str
    crm_sync_config: WorkspaceCRMSyncConfigResponse | None = None


class UpdateWorkspaceLLMConfigRequest(BaseModel):
    openrouter_model: str = Field(min_length=1, max_length=255)


class UpdateWorkspaceLLMConfigResponse(BaseModel):
    status: str
    llm_config: WorkspaceLLMConfigResponse | None = None


class UpdateWorkspaceOperationalControlRequest(BaseModel):
    automation_status: WorkspaceAutomationStatus
    pause_reason: str | None = Field(default=None, max_length=1000)


class UpdateWorkspaceOperationalControlResponse(BaseModel):
    status: str
    operational_control: WorkspaceOperationalControlResponse | None = None


class UpdateWorkspaceTimezoneRequest(BaseModel):
    default_timezone: str = Field(min_length=1, max_length=100)

    @field_validator("default_timezone")
    @classmethod
    def default_timezone_must_be_valid(cls, value: str) -> str:
        normalized = value.strip()
        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("default_timezone must be a valid IANA timezone") from exc
        return normalized


class UpdateWorkspaceTimezoneResponse(BaseModel):
    status: str
    workspace: WorkspaceResponse | None = None
