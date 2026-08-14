from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.domain.identity import WorkspaceMembershipRole


class UserResponse(BaseModel):
    user_id: UUID
    email: str
    full_name: str
    status: str


class WorkspaceResponse(BaseModel):
    workspace_id: UUID
    name: str
    status: str
    default_timezone: str


class MembershipResponse(BaseModel):
    membership_id: UUID
    workspace_id: UUID
    user_id: UUID
    role: str
    status: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    access_token_expires_at: datetime
    refresh_token_expires_at: datetime


class InviteWorkspaceUserRequest(BaseModel):
    email: EmailStr
    role: WorkspaceMembershipRole
    full_name: str


class InviteWorkspaceUserResponse(BaseModel):
    status: str
    user: UserResponse | None = None
    membership: MembershipResponse | None = None


class PreviewInvitationRequest(BaseModel):
    invitation_token: str


class InvitationPreview(BaseModel):
    email: str
    role: str
    workspace_name: str
    expires_at: datetime


class PreviewInvitationResponse(BaseModel):
    status: str
    invitation: InvitationPreview | None = None


class CompleteInvitedSignupRequest(BaseModel):
    invitation_token: str
    full_name: str
    password: str


class CompleteInvitedSignupResponse(BaseModel):
    status: str
    user: UserResponse | None = None
    workspace: WorkspaceResponse | None = None
    tokens: TokenPair | None = None


class SignInRequest(BaseModel):
    email: EmailStr
    password: str
    workspace_id: UUID | None = None


class SignInResponse(BaseModel):
    status: str
    user: UserResponse | None = None
    workspace: WorkspaceResponse | None = None
    tokens: TokenPair | None = None


class RefreshAuthenticationRequest(BaseModel):
    refresh_token: str


class RefreshAuthenticationResponse(BaseModel):
    status: str
    user: UserResponse | None = None
    workspace: WorkspaceResponse | None = None
    tokens: TokenPair | None = None


class LogoutRequest(BaseModel):
    refresh_token: str


class LogoutResponse(BaseModel):
    status: str
    revoked: bool


class LogoutAllResponse(BaseModel):
    status: str
    revoked: bool


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    status: str


class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str


class ResetPasswordResponse(BaseModel):
    status: str
    user: UserResponse | None = None


class CurrentUserResponse(BaseModel):
    status: str
    user: UserResponse | None = None
    workspace: WorkspaceResponse | None = None
    membership: MembershipResponse | None = None
    permissions: list[str] = []


class SwitchWorkspaceRequest(BaseModel):
    workspace_id: UUID


class SwitchWorkspaceResponse(BaseModel):
    status: str
    workspace: WorkspaceResponse | None = None
    access_token: str | None = None
    access_token_expires_at: datetime | None = None
