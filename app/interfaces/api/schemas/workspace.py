from uuid import UUID

from pydantic import BaseModel, EmailStr

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
