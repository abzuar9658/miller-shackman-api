from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.auth import OpaqueTokenService
from app.application.ports.messaging import EmailMessage, EmailProvider
from app.application.ports.repositories import (
    AuthAuditLogRepository,
    InvitationRepository,
    UserRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceCRMSyncConfigRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceMembershipRepository,
    WorkspaceOperationalControlRepository,
    WorkspaceRepository,
)
from app.application.services.authentication import render_invitation_email_body
from app.application.use_cases.authentication import AuthReasonCode
from app.domain.compliance import (
    SmsComplianceState,
    WorkspaceContactPolicy,
    default_workspace_contact_policy,
)
from app.domain.conversations import WorkspaceHandoffConfig, default_workspace_handoff_config
from app.domain.crm_sync import WorkspaceCRMSyncConfig, default_workspace_crm_sync_config
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
from app.domain.llm import WorkspaceLLMConfig, default_workspace_llm_config
from app.domain.workspace_automation import (
    WorkspaceAutomationStatus,
    WorkspaceOperationalControl,
    default_workspace_operational_control,
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


class WorkspaceSettingsReadStatus(StrEnum):
    FOUND = "found"
    REJECTED = "rejected"


class UpdateWorkspaceContactPolicyStatus(StrEnum):
    UPDATED = "updated"
    REJECTED = "rejected"


class UpdateWorkspaceHandoffConfigStatus(StrEnum):
    UPDATED = "updated"
    REJECTED = "rejected"


class UpdateWorkspaceCRMSyncConfigStatus(StrEnum):
    UPDATED = "updated"
    REJECTED = "rejected"


class UpdateWorkspaceLLMConfigStatus(StrEnum):
    UPDATED = "updated"
    REJECTED = "rejected"


class UpdateWorkspaceOperationalControlStatus(StrEnum):
    UPDATED = "updated"
    REJECTED = "rejected"


class UpdateWorkspaceTimezoneStatus(StrEnum):
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
    invitation_id: UUID | None = None


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


@dataclass(frozen=True)
class WorkspaceSettingsView:
    workspace: Workspace
    contact_policy: WorkspaceContactPolicy
    handoff_config: WorkspaceHandoffConfig
    crm_sync_config: WorkspaceCRMSyncConfig
    llm_config: WorkspaceLLMConfig
    operational_control: WorkspaceOperationalControl


@dataclass(frozen=True)
class WorkspaceSettingsReadResult:
    status: WorkspaceSettingsReadStatus
    view: WorkspaceSettingsView | None = None
    reasons: tuple[AuthReasonCode, ...] = ()


@dataclass(frozen=True)
class UpdateWorkspaceContactPolicyResult:
    status: UpdateWorkspaceContactPolicyStatus
    contact_policy: WorkspaceContactPolicy | None = None
    reasons: tuple[AuthReasonCode, ...] = ()


@dataclass(frozen=True)
class UpdateWorkspaceHandoffConfigResult:
    status: UpdateWorkspaceHandoffConfigStatus
    handoff_config: WorkspaceHandoffConfig | None = None
    reasons: tuple[AuthReasonCode, ...] = ()


@dataclass(frozen=True)
class UpdateWorkspaceCRMSyncConfigResult:
    status: UpdateWorkspaceCRMSyncConfigStatus
    crm_sync_config: WorkspaceCRMSyncConfig | None = None
    reasons: tuple[AuthReasonCode, ...] = ()


@dataclass(frozen=True)
class UpdateWorkspaceLLMConfigResult:
    status: UpdateWorkspaceLLMConfigStatus
    llm_config: WorkspaceLLMConfig | None = None
    reasons: tuple[AuthReasonCode, ...] = ()


@dataclass(frozen=True)
class UpdateWorkspaceOperationalControlResult:
    status: UpdateWorkspaceOperationalControlStatus
    operational_control: WorkspaceOperationalControl | None = None
    reasons: tuple[AuthReasonCode, ...] = ()


@dataclass(frozen=True)
class UpdateWorkspaceTimezoneResult:
    status: UpdateWorkspaceTimezoneStatus
    workspace: Workspace | None = None
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
    invitation_repository: InvitationRepository,
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

    permission = evaluate_permission(effective_actor, PermissionCapability.INVITE_WORKSPACE_USER)
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
        invitation_id: UUID | None = None
        if membership.status == WorkspaceMembershipStatus.INVITED:
            invitation = await invitation_repository.get_by_workspace_and_email_normalized(
                workspace_id,
                user.email_normalized,
            )
            if (
                invitation is not None
                and invitation.accepted_at is None
                and invitation.revoked_at is None
            ):
                invitation_id = invitation.invitation_id
        users.append(
            WorkspaceUser(
                user=user,
                membership=membership,
                invitation_id=invitation_id,
            ),
        )

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
    frontend_app_base_url: str,
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

    membership = await membership_repository.get_by_user_and_workspace(
        invitation.user_id,
        workspace_id,
    )
    if membership is None:
        return ResendInvitationResult(
            status=ResendInvitationStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,),
        )
    if membership.status == WorkspaceMembershipStatus.ACTIVE:
        return ResendInvitationResult(
            status=ResendInvitationStatus.REJECTED,
            reasons=(AuthReasonCode.MEMBERSHIP_ALREADY_ACTIVE,),
        )
    if membership.status != WorkspaceMembershipStatus.INVITED:
        return ResendInvitationResult(
            status=ResendInvitationStatus.REJECTED,
            reasons=(AuthReasonCode.MEMBERSHIP_NOT_ACTIVE,),
        )

    new_token = opaque_token_service.generate_token()
    updated_invitation = replace(
        invitation,
        role=membership.role,
        token_hash=new_token.token_hash,
        expires_at=now + invitation_ttl,
    )
    saved_invitation = await invitation_repository.save(updated_invitation)

    await email_provider.send(
        EmailMessage(
            to_email=saved_invitation.email,
            subject=f"You're invited to {workspace.name}",
            body=render_invitation_email_body(
                workspace_name=workspace.name,
                role=saved_invitation.role,
                invitation_token=new_token.plaintext,
                frontend_app_base_url=frontend_app_base_url,
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
    user_repository: UserRepository,
    invitation_repository: InvitationRepository,
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

    permission = evaluate_permission(effective_actor, PermissionCapability.INVITE_WORKSPACE_USER)
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
    user = await user_repository.get_by_id(user_id)
    if user is None:
        return UpdateWorkspaceMembershipResult(
            status=UpdateWorkspaceMembershipStatus.REJECTED,
            reasons=(AuthReasonCode.USER_NOT_FOUND,),
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

    pending_invitation = await invitation_repository.get_by_workspace_and_email_normalized(
        workspace_id,
        user.email_normalized,
    )
    if pending_invitation is not None:
        invitation_is_pending = (
            pending_invitation.accepted_at is None and pending_invitation.revoked_at is None
        )
        if invitation_is_pending and membership.status == WorkspaceMembershipStatus.INVITED:
            updated_invitation = pending_invitation
            if pending_invitation.role != saved_membership.role:
                updated_invitation = replace(updated_invitation, role=saved_membership.role)
            if saved_membership.status != WorkspaceMembershipStatus.INVITED:
                updated_invitation = replace(updated_invitation, revoked_at=now)
            if updated_invitation != pending_invitation:
                await invitation_repository.save(updated_invitation)

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

    permission = evaluate_permission(effective_actor, PermissionCapability.INVITE_WORKSPACE_USER)
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


async def get_workspace_settings(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    contact_policy_repository: WorkspaceContactPolicyRepository,
    handoff_config_repository: WorkspaceHandoffConfigRepository,
    crm_sync_config_repository: WorkspaceCRMSyncConfigRepository,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository,
    default_crm_sync_interval_seconds: int = 300,
    default_openrouter_model: str = "openai/gpt-4o-mini",
) -> WorkspaceSettingsReadResult:
    effective_actor = await _actor_for_workspace(
        actor=actor,
        workspace_id=workspace_id,
        workspace_repository=workspace_repository,
        membership_repository=membership_repository,
    )
    if effective_actor is None:
        return WorkspaceSettingsReadResult(
            status=WorkspaceSettingsReadStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,),
        )

    permission = evaluate_permission(
        effective_actor,
        PermissionCapability.VIEW_WORKSPACE_REPORTING,
    )
    if not permission.allowed:
        return WorkspaceSettingsReadResult(
            status=WorkspaceSettingsReadStatus.REJECTED,
            reasons=(AuthReasonCode.PERMISSION_DENIED,),
        )

    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return WorkspaceSettingsReadResult(
            status=WorkspaceSettingsReadStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_NOT_FOUND,),
        )

    contact_policy = await contact_policy_repository.get_by_workspace_id(workspace_id)
    handoff_config = await handoff_config_repository.get_by_workspace_id(workspace_id)
    crm_sync_config = await crm_sync_config_repository.get_by_workspace_id(workspace_id)
    llm_config = await workspace_llm_config_repository.get_by_workspace_id(workspace_id)
    operational_control = await workspace_operational_control_repository.get_by_workspace_id(
        workspace_id
    )
    return WorkspaceSettingsReadResult(
        status=WorkspaceSettingsReadStatus.FOUND,
        view=WorkspaceSettingsView(
            workspace=workspace,
            contact_policy=contact_policy or default_workspace_contact_policy(workspace_id),
            handoff_config=handoff_config or default_workspace_handoff_config(workspace_id),
            crm_sync_config=(
                crm_sync_config
                or default_workspace_crm_sync_config(
                    workspace_id,
                    default_interval_seconds=default_crm_sync_interval_seconds,
                )
            ),
            llm_config=(
                llm_config
                or default_workspace_llm_config(
                    workspace_id,
                    default_openrouter_model=default_openrouter_model,
                )
            ),
            operational_control=(
                operational_control or default_workspace_operational_control(workspace_id)
            ),
        ),
    )


async def update_workspace_contact_policy(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    sms_compliance_state: SmsComplianceState,
    quiet_hours_enabled: bool,
    quiet_hours_start: time,
    quiet_hours_end: time,
    inbound_email_address: str | None = None,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    contact_policy_repository: WorkspaceContactPolicyRepository,
    audit_log_repository: AuthAuditLogRepository,
    now: datetime,
) -> UpdateWorkspaceContactPolicyResult:
    effective_actor = await _actor_for_workspace(
        actor=actor,
        workspace_id=workspace_id,
        workspace_repository=workspace_repository,
        membership_repository=membership_repository,
    )
    if effective_actor is None:
        return UpdateWorkspaceContactPolicyResult(
            status=UpdateWorkspaceContactPolicyStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,),
        )

    permission = evaluate_permission(
        effective_actor,
        PermissionCapability.CHANGE_CONSENT_SUPPRESSION_POLICY,
    )
    if not permission.allowed:
        return UpdateWorkspaceContactPolicyResult(
            status=UpdateWorkspaceContactPolicyStatus.REJECTED,
            reasons=(AuthReasonCode.PERMISSION_DENIED,),
        )

    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return UpdateWorkspaceContactPolicyResult(
            status=UpdateWorkspaceContactPolicyStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_NOT_FOUND,),
        )

    current_policy = await contact_policy_repository.get_by_workspace_id(
        workspace_id
    ) or default_workspace_contact_policy(workspace_id)
    normalized_inbound_email = (
        current_policy.inbound_email_address
        if inbound_email_address is None
        else _normalize_optional_text(inbound_email_address)
    )
    if (
        current_policy.sms_compliance_state == sms_compliance_state
        and current_policy.quiet_hours_enabled == quiet_hours_enabled
        and current_policy.quiet_hours_start == quiet_hours_start
        and current_policy.quiet_hours_end == quiet_hours_end
        and current_policy.inbound_email_address == normalized_inbound_email
    ):
        return UpdateWorkspaceContactPolicyResult(
            status=UpdateWorkspaceContactPolicyStatus.UPDATED,
            contact_policy=current_policy,
        )

    updated_policy = replace(
        current_policy,
        sms_compliance_state=sms_compliance_state,
        quiet_hours_enabled=quiet_hours_enabled,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
        inbound_email_address=normalized_inbound_email,
    )
    saved_policy = await contact_policy_repository.save(updated_policy)
    await audit_log_repository.append(
        _auth_audit_log(
            event_type=AuthAuditEventType.WORKSPACE_CONTACT_POLICY_UPDATED,
            now=now,
            workspace_id=workspace_id,
            actor_user_id=actor.user_id,
            event_details={
                "sms_compliance_state": saved_policy.sms_compliance_state.value,
                "quiet_hours_enabled": (
                    "true" if saved_policy.quiet_hours_enabled else "false"
                ),
                "quiet_hours_start": (
                    saved_policy.quiet_hours_start.isoformat()
                    if saved_policy.quiet_hours_start is not None
                    else ""
                ),
                "quiet_hours_end": (
                    saved_policy.quiet_hours_end.isoformat()
                    if saved_policy.quiet_hours_end is not None
                    else ""
                ),
                "inbound_email_address": saved_policy.inbound_email_address or "",
            },
        ),
    )
    return UpdateWorkspaceContactPolicyResult(
        status=UpdateWorkspaceContactPolicyStatus.UPDATED,
        contact_policy=saved_policy,
    )


async def update_workspace_handoff_config(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    fallback_recipient_email: str | None,
    crm_handoff_tag: str | None,
    crm_custom_fields: dict[str, str],
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    handoff_config_repository: WorkspaceHandoffConfigRepository,
    audit_log_repository: AuthAuditLogRepository,
    now: datetime,
) -> UpdateWorkspaceHandoffConfigResult:
    effective_actor = await _actor_for_workspace(
        actor=actor,
        workspace_id=workspace_id,
        workspace_repository=workspace_repository,
        membership_repository=membership_repository,
    )
    if effective_actor is None:
        return UpdateWorkspaceHandoffConfigResult(
            status=UpdateWorkspaceHandoffConfigStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,),
        )

    permission = evaluate_permission(
        effective_actor,
        PermissionCapability.CHANGE_CONSENT_SUPPRESSION_POLICY,
    )
    if not permission.allowed:
        return UpdateWorkspaceHandoffConfigResult(
            status=UpdateWorkspaceHandoffConfigStatus.REJECTED,
            reasons=(AuthReasonCode.PERMISSION_DENIED,),
        )

    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return UpdateWorkspaceHandoffConfigResult(
            status=UpdateWorkspaceHandoffConfigStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_NOT_FOUND,),
        )

    normalized_email = _normalize_optional_text(fallback_recipient_email)
    normalized_tag = _normalize_optional_text(crm_handoff_tag)
    normalized_custom_fields = _normalize_custom_fields(crm_custom_fields)
    current_config = await handoff_config_repository.get_by_workspace_id(
        workspace_id
    ) or default_workspace_handoff_config(workspace_id)
    if (
        current_config.fallback_recipient_email == normalized_email
        and current_config.crm_handoff_tag == normalized_tag
        and dict(current_config.crm_custom_fields) == normalized_custom_fields
    ):
        return UpdateWorkspaceHandoffConfigResult(
            status=UpdateWorkspaceHandoffConfigStatus.UPDATED,
            handoff_config=current_config,
        )

    updated_config = WorkspaceHandoffConfig(
        workspace_id=workspace_id,
        fallback_recipient_email=normalized_email,
        crm_handoff_tag=normalized_tag,
        crm_custom_fields=normalized_custom_fields,
    )
    saved_config = await handoff_config_repository.save(updated_config)
    await audit_log_repository.append(
        _auth_audit_log(
            event_type=AuthAuditEventType.WORKSPACE_HANDOFF_CONFIG_UPDATED,
            now=now,
            workspace_id=workspace_id,
            actor_user_id=actor.user_id,
            event_details={
                "fallback_recipient_email": saved_config.fallback_recipient_email or "",
                "crm_handoff_tag": saved_config.crm_handoff_tag or "",
                "crm_custom_fields": str(dict(saved_config.crm_custom_fields)),
            },
        ),
    )
    return UpdateWorkspaceHandoffConfigResult(
        status=UpdateWorkspaceHandoffConfigStatus.UPDATED,
        handoff_config=saved_config,
    )


async def update_workspace_crm_sync_config(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    crm_sync_enabled: bool,
    crm_sync_interval_seconds: int,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    crm_sync_config_repository: WorkspaceCRMSyncConfigRepository,
    audit_log_repository: AuthAuditLogRepository,
    now: datetime,
    default_crm_sync_interval_seconds: int = 300,
) -> UpdateWorkspaceCRMSyncConfigResult:
    effective_actor = await _actor_for_workspace(
        actor=actor,
        workspace_id=workspace_id,
        workspace_repository=workspace_repository,
        membership_repository=membership_repository,
    )
    if effective_actor is None:
        return UpdateWorkspaceCRMSyncConfigResult(
            status=UpdateWorkspaceCRMSyncConfigStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,),
        )

    permission = evaluate_permission(
        effective_actor,
        PermissionCapability.CHANGE_CONSENT_SUPPRESSION_POLICY,
    )
    if not permission.allowed:
        return UpdateWorkspaceCRMSyncConfigResult(
            status=UpdateWorkspaceCRMSyncConfigStatus.REJECTED,
            reasons=(AuthReasonCode.PERMISSION_DENIED,),
        )

    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return UpdateWorkspaceCRMSyncConfigResult(
            status=UpdateWorkspaceCRMSyncConfigStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_NOT_FOUND,),
        )

    current_config = await crm_sync_config_repository.get_by_workspace_id(
        workspace_id,
    ) or default_workspace_crm_sync_config(
        workspace_id,
        default_interval_seconds=default_crm_sync_interval_seconds,
    )
    if (
        current_config.crm_sync_enabled == crm_sync_enabled
        and current_config.crm_sync_interval_seconds == crm_sync_interval_seconds
    ):
        return UpdateWorkspaceCRMSyncConfigResult(
            status=UpdateWorkspaceCRMSyncConfigStatus.UPDATED,
            crm_sync_config=current_config,
        )

    saved_config = await crm_sync_config_repository.save(
        WorkspaceCRMSyncConfig(
            workspace_id=workspace_id,
            crm_sync_enabled=crm_sync_enabled,
            crm_sync_interval_seconds=crm_sync_interval_seconds,
        )
    )
    await audit_log_repository.append(
        _auth_audit_log(
            event_type=AuthAuditEventType.WORKSPACE_CRM_SYNC_CONFIG_UPDATED,
            now=now,
            workspace_id=workspace_id,
            actor_user_id=actor.user_id,
            event_details={
                "crm_sync_enabled": str(saved_config.crm_sync_enabled).lower(),
                "crm_sync_interval_seconds": str(saved_config.crm_sync_interval_seconds),
            },
        ),
    )
    return UpdateWorkspaceCRMSyncConfigResult(
        status=UpdateWorkspaceCRMSyncConfigStatus.UPDATED,
        crm_sync_config=saved_config,
    )


async def update_workspace_llm_config(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    openrouter_model: str,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository,
    audit_log_repository: AuthAuditLogRepository,
    now: datetime,
    default_openrouter_model: str = "openai/gpt-4o-mini",
    allowed_openrouter_models: tuple[str, ...] = ("openai/gpt-4o-mini",),
) -> UpdateWorkspaceLLMConfigResult:
    effective_actor = await _actor_for_workspace(
        actor=actor,
        workspace_id=workspace_id,
        workspace_repository=workspace_repository,
        membership_repository=membership_repository,
    )
    if effective_actor is None:
        return UpdateWorkspaceLLMConfigResult(
            status=UpdateWorkspaceLLMConfigStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,),
        )

    permission = evaluate_permission(
        effective_actor,
        PermissionCapability.CHANGE_CONSENT_SUPPRESSION_POLICY,
    )
    if not permission.allowed:
        return UpdateWorkspaceLLMConfigResult(
            status=UpdateWorkspaceLLMConfigStatus.REJECTED,
            reasons=(AuthReasonCode.PERMISSION_DENIED,),
        )

    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return UpdateWorkspaceLLMConfigResult(
            status=UpdateWorkspaceLLMConfigStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_NOT_FOUND,),
        )

    normalized_model = openrouter_model.strip()
    if normalized_model not in allowed_openrouter_models:
        return UpdateWorkspaceLLMConfigResult(
            status=UpdateWorkspaceLLMConfigStatus.REJECTED,
            reasons=(AuthReasonCode.VALIDATION_ERROR,),
        )

    current_config = await workspace_llm_config_repository.get_by_workspace_id(
        workspace_id,
    ) or default_workspace_llm_config(
        workspace_id,
        default_openrouter_model=default_openrouter_model,
    )
    if current_config.openrouter_model == normalized_model:
        return UpdateWorkspaceLLMConfigResult(
            status=UpdateWorkspaceLLMConfigStatus.UPDATED,
            llm_config=current_config,
        )

    saved_config = await workspace_llm_config_repository.save(
        WorkspaceLLMConfig(
            workspace_id=workspace_id,
            openrouter_model=normalized_model,
        )
    )
    await audit_log_repository.append(
        _auth_audit_log(
            event_type=AuthAuditEventType.WORKSPACE_LLM_CONFIG_UPDATED,
            now=now,
            workspace_id=workspace_id,
            actor_user_id=actor.user_id,
            event_details={"openrouter_model": saved_config.openrouter_model},
        ),
    )
    return UpdateWorkspaceLLMConfigResult(
        status=UpdateWorkspaceLLMConfigStatus.UPDATED,
        llm_config=saved_config,
    )


async def update_workspace_operational_control(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    automation_status: WorkspaceAutomationStatus,
    pause_reason: str | None,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository,
    audit_log_repository: AuthAuditLogRepository,
    now: datetime,
) -> UpdateWorkspaceOperationalControlResult:
    effective_actor = await _actor_for_workspace(
        actor=actor,
        workspace_id=workspace_id,
        workspace_repository=workspace_repository,
        membership_repository=membership_repository,
    )
    if effective_actor is None:
        return UpdateWorkspaceOperationalControlResult(
            status=UpdateWorkspaceOperationalControlStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,),
        )

    permission = evaluate_permission(
        effective_actor,
        PermissionCapability.CHANGE_CONSENT_SUPPRESSION_POLICY,
    )
    if not permission.allowed:
        return UpdateWorkspaceOperationalControlResult(
            status=UpdateWorkspaceOperationalControlStatus.REJECTED,
            reasons=(AuthReasonCode.PERMISSION_DENIED,),
        )

    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return UpdateWorkspaceOperationalControlResult(
            status=UpdateWorkspaceOperationalControlStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_NOT_FOUND,),
        )

    normalized_reason = (pause_reason or "").strip() or None
    if automation_status == WorkspaceAutomationStatus.ACTIVE:
        normalized_reason = None

    current_control = await workspace_operational_control_repository.get_by_workspace_id(
        workspace_id,
    ) or default_workspace_operational_control(workspace_id)
    if (
        current_control.automation_status == automation_status
        and current_control.pause_reason == normalized_reason
    ):
        return UpdateWorkspaceOperationalControlResult(
            status=UpdateWorkspaceOperationalControlStatus.UPDATED,
            operational_control=current_control,
        )

    saved_control = await workspace_operational_control_repository.save(
        WorkspaceOperationalControl(
            workspace_id=workspace_id,
            automation_status=automation_status,
            pause_reason=normalized_reason,
        )
    )
    event_details = {"automation_status": saved_control.automation_status.value}
    if saved_control.pause_reason is not None:
        event_details["pause_reason"] = saved_control.pause_reason

    await audit_log_repository.append(
        _auth_audit_log(
            event_type=AuthAuditEventType.WORKSPACE_OPERATIONAL_CONTROL_UPDATED,
            now=now,
            workspace_id=workspace_id,
            actor_user_id=actor.user_id,
            event_details=event_details,
        ),
    )
    return UpdateWorkspaceOperationalControlResult(
        status=UpdateWorkspaceOperationalControlStatus.UPDATED,
        operational_control=saved_control,
    )


async def update_workspace_default_timezone(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    default_timezone: str,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    audit_log_repository: AuthAuditLogRepository,
    now: datetime,
) -> UpdateWorkspaceTimezoneResult:
    effective_actor = await _actor_for_workspace(
        actor=actor,
        workspace_id=workspace_id,
        workspace_repository=workspace_repository,
        membership_repository=membership_repository,
    )
    if effective_actor is None:
        return UpdateWorkspaceTimezoneResult(
            status=UpdateWorkspaceTimezoneStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,),
        )

    permission = evaluate_permission(
        effective_actor,
        PermissionCapability.CHANGE_CONSENT_SUPPRESSION_POLICY,
    )
    if not permission.allowed:
        return UpdateWorkspaceTimezoneResult(
            status=UpdateWorkspaceTimezoneStatus.REJECTED,
            reasons=(AuthReasonCode.PERMISSION_DENIED,),
        )

    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return UpdateWorkspaceTimezoneResult(
            status=UpdateWorkspaceTimezoneStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_NOT_FOUND,),
        )

    normalized_timezone = default_timezone.strip()
    if workspace.default_timezone == normalized_timezone:
        return UpdateWorkspaceTimezoneResult(
            status=UpdateWorkspaceTimezoneStatus.UPDATED,
            workspace=workspace,
        )

    saved_workspace = await workspace_repository.save(
        replace(workspace, default_timezone=normalized_timezone, updated_at=now),
    )
    await audit_log_repository.append(
        _auth_audit_log(
            event_type=AuthAuditEventType.WORKSPACE_TIMEZONE_UPDATED,
            now=now,
            workspace_id=workspace_id,
            actor_user_id=actor.user_id,
            event_details={"default_timezone": saved_workspace.default_timezone},
        ),
    )
    return UpdateWorkspaceTimezoneResult(
        status=UpdateWorkspaceTimezoneStatus.UPDATED,
        workspace=saved_workspace,
    )


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_custom_fields(values: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in values.items():
        normalized_key = key.strip()
        normalized_value = value.strip()
        if normalized_key and normalized_value:
            normalized[normalized_key] = normalized_value
    return normalized


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
