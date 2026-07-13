from datetime import time
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.domain.compliance import SmsComplianceState
from app.domain.identity import UserStatus, WorkspaceMembershipRole, WorkspaceMembershipStatus
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
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None


class WorkspaceHandoffConfigResponse(BaseModel):
    workspace_id: UUID
    fallback_recipient_email: str | None = None
    crm_handoff_tag: str | None = None
    crm_custom_fields: dict[str, str]


class WorkspaceSettingsResponse(BaseModel):
    status: str
    workspace: WorkspaceResponse | None = None
    contact_policy: WorkspaceContactPolicyResponse | None = None
    handoff_config: WorkspaceHandoffConfigResponse | None = None


class UpdateWorkspaceContactPolicyRequest(BaseModel):
    sms_compliance_state: SmsComplianceState
    quiet_hours_start: time
    quiet_hours_end: time

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
