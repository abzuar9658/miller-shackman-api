from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.common.ids import (
    AuthAuditLogId,
    PasswordResetTokenId,
    RefreshSessionId,
    UserId,
    UserInvitationId,
    WorkspaceId,
    WorkspaceMembershipId,
)


class UserStatus(StrEnum):
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    DISABLED = "disabled"
    LOCKED = "locked"


class WorkspaceStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class WorkspaceMembershipRole(StrEnum):
    BROKERAGE_ADMIN = "brokerage_admin"
    MANAGER = "manager"
    ASSIGNED_AGENT = "assigned_agent"
    PLATFORM_SUPER_ADMIN = "platform_super_admin"


class WorkspaceMembershipStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    DISABLED = "disabled"


class AuthAuditEventType(StrEnum):
    WORKSPACE_CREATED = "workspace_created"
    USER_INVITED = "user_invited"
    INVITATION_ACCEPTED = "invitation_accepted"
    SIGNIN_SUCCEEDED = "signin_succeeded"
    SIGNIN_FAILED = "signin_failed"
    LOGOUT_SUCCEEDED = "logout_succeeded"
    LOGOUT_ALL_SUCCEEDED = "logout_all_succeeded"
    PASSWORD_RESET_REQUESTED = "password_reset_requested"
    PASSWORD_RESET_COMPLETED = "password_reset_completed"
    ROLE_CHANGED = "role_changed"
    USER_DISABLED = "user_disabled"


class RefreshSessionRevocationReason(StrEnum):
    ROTATED = "rotated"
    LOGOUT = "logout"
    LOGOUT_ALL = "logout_all"
    PASSWORD_RESET = "password_reset"
    REUSE_DETECTED = "reuse_detected"


def _empty_string_mapping() -> Mapping[str, str]:
    return {}


@dataclass(frozen=True)
class User:
    user_id: UserId
    email: str
    email_normalized: str
    full_name: str | None
    status: UserStatus
    email_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Workspace:
    workspace_id: WorkspaceId
    name: str
    status: WorkspaceStatus
    default_timezone: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class WorkspaceMembership:
    membership_id: WorkspaceMembershipId
    workspace_id: WorkspaceId
    user_id: UserId
    role: WorkspaceMembershipRole
    status: WorkspaceMembershipStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PasswordCredential:
    user_id: UserId
    password_hash: str
    password_changed_at: datetime | None
    failed_attempt_count: int
    locked_until: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RefreshSession:
    session_id: RefreshSessionId
    user_id: UserId
    workspace_id: WorkspaceId
    refresh_token_hash: str
    family_id: UUID
    rotated_from_session_id: RefreshSessionId | None
    expires_at: datetime
    revoked_at: datetime | None
    revoked_reason: RefreshSessionRevocationReason | None
    created_at: datetime
    last_used_at: datetime | None


@dataclass(frozen=True)
class PasswordResetToken:
    reset_token_id: PasswordResetTokenId
    user_id: UserId
    token_hash: str
    expires_at: datetime
    used_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class UserInvitation:
    invitation_id: UserInvitationId
    workspace_id: WorkspaceId
    user_id: UserId
    email: str
    email_normalized: str
    role: WorkspaceMembershipRole
    token_hash: str
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_by_user_id: UserId
    created_at: datetime


@dataclass(frozen=True)
class AuthAuditLog:
    audit_log_id: AuthAuditLogId
    event_type: AuthAuditEventType
    created_at: datetime
    workspace_id: WorkspaceId | None = None
    actor_user_id: UserId | None = None
    subject_user_id: UserId | None = None
    event_details: Mapping[str, str] = field(default_factory=_empty_string_mapping)


@dataclass(frozen=True)
class AuthenticatedActor:
    user_id: UserId
    user_status: UserStatus
    active_role: WorkspaceMembershipRole | None = None
    active_workspace_id: WorkspaceId | None = None
    active_workspace_status: WorkspaceStatus | None = None
    active_membership_id: WorkspaceMembershipId | None = None
    active_membership_status: WorkspaceMembershipStatus | None = None