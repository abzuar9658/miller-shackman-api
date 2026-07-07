from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.auth import OpaqueTokenService
from app.application.ports.messaging import EmailMessage, EmailProvider
from app.application.ports.repositories import (
    AuthAuditLogRepository,
    InvitationRepository,
    UserRepository,
    WorkspaceMembershipRepository,
    WorkspaceRepository,
)
from app.application.use_cases.authentication import AuthReasonCode
from app.domain.identity import (
    AuthAuditEventType,
    AuthAuditLog,
    AuthenticatedActor,
    PermissionCapability,
    User,
    UserInvitation,
    UserStatus,
    Workspace,
    WorkspaceMembership,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
    evaluate_permission,
)


class CreateWorkspaceStatus(StrEnum):
    CREATED = "created"
    REJECTED = "rejected"


class ListWorkspaceUsersStatus(StrEnum):
    FOUND = "found"
    REJECTED = "rejected"


class ResendInvitationStatus(StrEnum):
    RESENT = "resent"
    REJECTED = "rejected"


class UpdateWorkspaceMembershipStatus(StrEnum):
    UPDATED = "updated"
    REJECTED = "rejected"


class UpdateUserStatusStatus(StrEnum):
    UPDATED = "updated"
    REJECTED = "rejected"


@dataclass(frozen=True)
class CreateWorkspaceResult:
    status: CreateWorkspaceStatus
    workspace: Workspace | None = None
    membership: WorkspaceMembership | None = None
    reasons: tuple[AuthReasonCode, ...] = ()


@dataclass(frozen=True)
class WorkspaceUser:
    user: User
    membership: WorkspaceMembership


@dataclass(frozen=True)
class ListWorkspaceUsersResult:
    status: ListWorkspaceUsersStatus
    users: tuple[WorkspaceUser, ...] = ()
    reasons: tuple[AuthReasonCode, ...] = ()


@dataclass(frozen=True)
class ResendInvitationResult:
    status: ResendInvitationStatus
    invitation: UserInvitation | None = None
    reasons: tuple[AuthReasonCode, ...] = ()


@dataclass(frozen=True)
class UpdateWorkspaceMembershipResult:
    status: UpdateWorkspaceMembershipStatus
    membership: WorkspaceMembership | None = None
    reasons: tuple[AuthReasonCode, ...] = ()


@dataclass(frozen=True)
class UpdateUserStatusResult:
    status: UpdateUserStatusStatus
    user: User | None = None
    reasons: tuple[AuthReasonCode, ...] = ()


async def create_workspace(
    *,
    actor: AuthenticatedActor,
    name: str,
    default_timezone: str,
    user_repository: UserRepository,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    audit_log_repository: AuthAuditLogRepository,
    now: datetime,
) -> CreateWorkspaceResult:
    permission = evaluate_permission(actor, PermissionCapability.CREATE_WORKSPACE)
    if not permission.allowed:
        return CreateWorkspaceResult(
            status=CreateWorkspaceStatus.REJECTED,
            reasons=(AuthReasonCode.PERMISSION_DENIED,),
        )

    workspace = Workspace(
        workspace_id=uuid4(),
        name=name.strip(),
        status=WorkspaceStatus.ACTIVE,
        default_timezone=default_timezone,
        created_at=now,
        updated_at=now,
    )
    saved_workspace = await workspace_repository.save(workspace)

    membership = WorkspaceMembership(
        membership_id=uuid4(),
        workspace_id=saved_workspace.workspace_id,
        user_id=actor.user_id,
        role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
        status=WorkspaceMembershipStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    saved_membership = await membership_repository.save(membership)

    await audit_log_repository.append(
        _auth_audit_log(
            event_type=AuthAuditEventType.WORKSPACE_CREATED,
            now=now,
            workspace_id=saved_workspace.workspace_id,
            actor_user_id=actor.user_id,
            event_details={"workspace_name": saved_workspace.name},
        ),
    )
    return CreateWorkspaceResult(
        status=CreateWorkspaceStatus.CREATED,
        workspace=saved_workspace,
        membership=saved_membership,
    )


async def list_workspace_users(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    user_repository: UserRepository,
) -> ListWorkspaceUsersResult:
    effective_actor = await _actor_for_workspace(
        actor=actor,
        workspace_id=workspace_id,
        workspace_repository=workspace_repository,
        membership_repository=membership_repository,
    )
    if effective_actor is None:
        return ListWorkspaceUsersResult(
            status=ListWorkspaceUsersStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,),
        )

    permission = evaluate_permission(effective_actor, PermissionCapability.MANAGE_WORKSPACE_USERS)
    if not permission.allowed:
        return ListWorkspaceUsersResult(
            status=ListWorkspaceUsersStatus.REJECTED,
            reasons=(AuthReasonCode.PERMISSION_DENIED,),
        )

    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return ListWorkspaceUsersResult(
            status=ListWorkspaceUsersStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_NOT_FOUND,),
        )

    memberships = await membership_repository.list_by_workspace_id(workspace_id)
    users: list[WorkspaceUser] = []
    for membership in memberships:
        user = await user_repository.get_by_id(membership.user_id)
        if user is None:
            continue
        users.append(WorkspaceUser(user=user, membership=membership))

    return ListWorkspaceUsersResult(
        status=ListWorkspaceUsersStatus.FOUND,
        users=tuple(users),
    )


async def resend_invitation(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    invitation_id: UUID,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    invitation_repository: InvitationRepository,
    audit_log_repository: AuthAuditLogRepository,
    opaque_token_service: OpaqueTokenService,
    email_provider: EmailProvider,
    now: datetime,
    invitation_ttl: timedelta = timedelta(days=7),
) -> ResendInvitationResult:
    effective_actor = await _actor_for_workspace(
        actor=actor,
        workspace_id=workspace_id,
        workspace_repository=workspace_repository,
        membership_repository=membership_repository,
    )
    if effective_actor is None:
        return ResendInvitationResult(
            status=ResendInvitationStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,),
        )

    permission = evaluate_permission(effective_actor, PermissionCapability.INVITE_WORKSPACE_USER)
    if not permission.allowed:
        return ResendInvitationResult(
            status=ResendInvitationStatus.REJECTED,
            reasons=(AuthReasonCode.PERMISSION_DENIED,),
        )

    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return ResendInvitationResult(
            status=ResendInvitationStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_NOT_FOUND,),
        )

    invitation = await invitation_repository.get_by_id(invitation_id)
    if invitation is None or invitation.workspace_id != workspace_id:
        return ResendInvitationResult(
            status=ResendInvitationStatus.REJECTED,
            reasons=(AuthReasonCode.INVITATION_NOT_FOUND,),
        )
    if invitation.accepted_at is not None:
        return ResendInvitationResult(
            status=ResendInvitationStatus.REJECTED,
            reasons=(AuthReasonCode.INVITATION_ALREADY_ACCEPTED,),
        )
    if invitation.revoked_at is not None:
        return ResendInvitationResult(
            status=ResendInvitationStatus.REJECTED,
            reasons=(AuthReasonCode.INVITATION_REVOKED,),
        )

    new_token = opaque_token_service.generate_token()
    updated_invitation = replace(
        invitation,
        token_hash=new_token.token_hash,
        expires_at=now + invitation_ttl,
    )
    saved_invitation = await invitation_repository.save(updated_invitation)

    await email_provider.send(
        EmailMessage(
            to_email=saved_invitation.email,
            subject=f"You're invited to {workspace.name}",
            body=_invitation_email_body(
                workspace_name=workspace.name,
                role=saved_invitation.role,
                invitation_token=new_token.plaintext,
            ),
            idempotency_key=f"auth-invitation-resent:{saved_invitation.invitation_id}:{saved_invitation.expires_at.isoformat()}",
        ),
    )

    await audit_log_repository.append(
        _auth_audit_log(
            event_type=AuthAuditEventType.INVITATION_RESENT,
            now=now,
            workspace_id=workspace_id,
            actor_user_id=actor.user_id,
            subject_user_id=saved_invitation.user_id,
            event_details={
                "invitation_id": str(saved_invitation.invitation_id),
                "role": saved_invitation.role.value,
            },
        ),
    )
    return ResendInvitationResult(
        status=ResendInvitationStatus.RESENT,
        invitation=saved_invitation,
    )


async def update_workspace_membership(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    user_id: UUID,
    role: WorkspaceMembershipRole | None,
    membership_status: WorkspaceMembershipStatus | None,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    audit_log_repository: AuthAuditLogRepository,
    now: datetime,
) -> UpdateWorkspaceMembershipResult:
    effective_actor = await _actor_for_workspace(
        actor=actor,
        workspace_id=workspace_id,
        workspace_repository=workspace_repository,
        membership_repository=membership_repository,
    )
    if effective_actor is None:
        return UpdateWorkspaceMembershipResult(
            status=UpdateWorkspaceMembershipStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,),
        )

    permission = evaluate_permission(effective_actor, PermissionCapability.MANAGE_WORKSPACE_USERS)
    if not permission.allowed:
        return UpdateWorkspaceMembershipResult(
            status=UpdateWorkspaceMembershipStatus.REJECTED,
            reasons=(AuthReasonCode.PERMISSION_DENIED,),
        )

    membership = await membership_repository.get_by_user_and_workspace(user_id, workspace_id)
    if membership is None:
        return UpdateWorkspaceMembershipResult(
            status=UpdateWorkspaceMembershipStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,),
        )

    if role is not None and role == WorkspaceMembershipRole.PLATFORM_SUPER_ADMIN:
        return UpdateWorkspaceMembershipResult(
            status=UpdateWorkspaceMembershipStatus.REJECTED,
            reasons=(AuthReasonCode.INVALID_ROLE,),
        )

    new_role = role if role is not None else membership.role
    new_status = membership_status if membership_status is not None else membership.status
    if new_role == membership.role and new_status == membership.status:
        return UpdateWorkspaceMembershipResult(
            status=UpdateWorkspaceMembershipStatus.UPDATED,
            membership=membership,
        )

    updated_membership = replace(
        membership,
        role=new_role,
        status=new_status,
        updated_at=now,
    )
    saved_membership = await membership_repository.save(updated_membership)

    event_type = AuthAuditEventType.ROLE_CHANGED
    if membership_status is not None:
        event_type = (
            AuthAuditEventType.MEMBERSHIP_ENABLED
            if membership_status == WorkspaceMembershipStatus.ACTIVE
            else AuthAuditEventType.MEMBERSHIP_DISABLED
        )

    await audit_log_repository.append(
        _auth_audit_log(
            event_type=event_type,
            now=now,
            workspace_id=workspace_id,
            actor_user_id=actor.user_id,
            subject_user_id=user_id,
            event_details={
                "membership_id": str(saved_membership.membership_id),
                "role": saved_membership.role.value,
                "status": saved_membership.status.value,
            },
        ),
    )
    return UpdateWorkspaceMembershipResult(
        status=UpdateWorkspaceMembershipStatus.UPDATED,
        membership=saved_membership,
    )


async def update_user_status(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    user_id: UUID,
    user_status: UserStatus,
    user_repository: UserRepository,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    audit_log_repository: AuthAuditLogRepository,
    now: datetime,
) -> UpdateUserStatusResult:
    effective_actor = await _actor_for_workspace(
        actor=actor,
        workspace_id=workspace_id,
        workspace_repository=workspace_repository,
        membership_repository=membership_repository,
    )
    if effective_actor is None:
        return UpdateUserStatusResult(
            status=UpdateUserStatusStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,),
        )

    permission = evaluate_permission(effective_actor, PermissionCapability.MANAGE_WORKSPACE_USERS)
    if not permission.allowed:
        return UpdateUserStatusResult(
            status=UpdateUserStatusStatus.REJECTED,
            reasons=(AuthReasonCode.PERMISSION_DENIED,),
        )

    user = await user_repository.get_by_id(user_id)
    if user is None:
        return UpdateUserStatusResult(
            status=UpdateUserStatusStatus.REJECTED,
            reasons=(AuthReasonCode.USER_NOT_FOUND,),
        )

    if user.status == user_status:
        return UpdateUserStatusResult(
            status=UpdateUserStatusStatus.UPDATED,
            user=user,
        )

    updated_user = replace(
        user,
        status=user_status,
        updated_at=now,
    )
    saved_user = await user_repository.save(updated_user)

    event_type = (
        AuthAuditEventType.USER_ENABLED
        if user_status == UserStatus.ACTIVE
        else AuthAuditEventType.USER_DISABLED
    )
    await audit_log_repository.append(
        _auth_audit_log(
            event_type=event_type,
            now=now,
            workspace_id=workspace_id,
            actor_user_id=actor.user_id,
            subject_user_id=user_id,
            event_details={"user_status": saved_user.status.value},
        ),
    )
    return UpdateUserStatusResult(
        status=UpdateUserStatusStatus.UPDATED,
        user=saved_user,
    )


async def _actor_for_workspace(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> AuthenticatedActor | None:
    if actor.active_workspace_id == workspace_id:
        return actor

    membership = await membership_repository.get_by_user_and_workspace(
        actor.user_id,
        workspace_id,
    )
    if membership is None:
        return None

    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return None

    return AuthenticatedActor(
        user_id=actor.user_id,
        user_status=actor.user_status,
        active_role=membership.role,
        active_workspace_id=workspace.workspace_id,
        active_workspace_status=workspace.status,
        active_membership_id=membership.membership_id,
        active_membership_status=membership.status,
    )


def _auth_audit_log(
    *,
    event_type: AuthAuditEventType,
    now: datetime,
    workspace_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    subject_user_id: UUID | None = None,
    event_details: dict[str, str] | None = None,
) -> AuthAuditLog:
    return AuthAuditLog(
        audit_log_id=uuid4(),
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        subject_user_id=subject_user_id,
        event_type=event_type,
        event_details=event_details or {},
        created_at=now,
    )


def _invitation_email_body(
    *,
    workspace_name: str,
    role: WorkspaceMembershipRole,
    invitation_token: str,
) -> str:
    return (
        f"You've been invited to join {workspace_name} as {role.value}. "
        f"Use this invitation token to complete signup: {invitation_token}"
    )
