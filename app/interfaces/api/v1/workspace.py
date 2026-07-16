from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.use_cases.authentication import (
    AuthReasonCode,
    InviteWorkspaceUserStatus,
    invite_workspace_user,
)
from app.application.use_cases.workspace import (
    CreateWorkspaceStatus,
    ListWorkspaceUsersStatus,
    ResendInvitationStatus,
    UpdateUserStatusStatus,
    UpdateWorkspaceContactPolicyStatus,
    UpdateWorkspaceCRMSyncConfigStatus,
    UpdateWorkspaceHandoffConfigStatus,
    UpdateWorkspaceLLMConfigStatus,
    UpdateWorkspaceMembershipStatus,
    UpdateWorkspaceOperationalControlStatus,
    UpdateWorkspaceTimezoneStatus,
    WorkspaceSettingsReadStatus,
    create_workspace,
    get_workspace_settings,
    list_workspace_users,
    resend_invitation,
    update_user_status,
    update_workspace_contact_policy,
    update_workspace_crm_sync_config,
    update_workspace_default_timezone,
    update_workspace_handoff_config,
    update_workspace_llm_config,
    update_workspace_membership,
    update_workspace_operational_control,
)
from app.domain.compliance import WorkspaceContactPolicy
from app.domain.conversations import WorkspaceHandoffConfig
from app.domain.crm_sync import WorkspaceCRMSyncConfig
from app.domain.identity import AuthenticatedActor, User, Workspace, WorkspaceMembership
from app.domain.llm import WorkspaceLLMConfig
from app.domain.workspace_automation import WorkspaceOperationalControl
from app.interfaces.api.dependencies.auth import (
    AuthServiceBundle,
    get_auth_service_bundle,
    get_current_actor,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.dependencies.workspace_settings import (
    WorkspaceSettingsBundle,
    get_workspace_settings_bundle,
)
from app.interfaces.api.schemas.auth import (
    MembershipResponse,
    UserResponse,
    WorkspaceResponse,
)
from app.interfaces.api.schemas.workspace import (
    CreateWorkspaceRequest,
    CreateWorkspaceResponse,
    InviteWorkspaceUserRequest,
    InviteWorkspaceUserResponse,
    ListWorkspaceUsersResponse,
    ResendInvitationResponse,
    UpdateUserStatusRequest,
    UpdateUserStatusResponse,
    UpdateWorkspaceContactPolicyRequest,
    UpdateWorkspaceContactPolicyResponse,
    UpdateWorkspaceCRMSyncConfigRequest,
    UpdateWorkspaceCRMSyncConfigResponse,
    UpdateWorkspaceHandoffConfigRequest,
    UpdateWorkspaceHandoffConfigResponse,
    UpdateWorkspaceLLMConfigRequest,
    UpdateWorkspaceLLMConfigResponse,
    UpdateWorkspaceMembershipRequest,
    UpdateWorkspaceMembershipResponse,
    UpdateWorkspaceOperationalControlRequest,
    UpdateWorkspaceOperationalControlResponse,
    UpdateWorkspaceTimezoneRequest,
    UpdateWorkspaceTimezoneResponse,
    WorkspaceContactPolicyResponse,
    WorkspaceCRMSyncConfigResponse,
    WorkspaceHandoffConfigResponse,
    WorkspaceLLMConfigResponse,
    WorkspaceOperationalControlResponse,
    WorkspaceSettingsResponse,
    WorkspaceUserResponse,
)

router = APIRouter(tags=["workspaces"])


_401_REASONS: set[AuthReasonCode] = {
    AuthReasonCode.INVALID_CREDENTIALS,
    AuthReasonCode.USER_NOT_ACTIVE,
    AuthReasonCode.USER_DISABLED,
    AuthReasonCode.USER_LOCKED,
    AuthReasonCode.USER_NOT_FOUND,
    AuthReasonCode.REFRESH_TOKEN_INVALID,
    AuthReasonCode.REFRESH_SESSION_EXPIRED,
    AuthReasonCode.REFRESH_SESSION_REVOKED,
    AuthReasonCode.REFRESH_TOKEN_REUSE_DETECTED,
}


def _status_for_reasons(reasons: tuple[AuthReasonCode, ...]) -> int:
    if any(reason in _401_REASONS for reason in reasons):
        return status.HTTP_401_UNAUTHORIZED
    if AuthReasonCode.PERMISSION_DENIED in reasons:
        return status.HTTP_403_FORBIDDEN
    return status.HTTP_400_BAD_REQUEST


def _raise_for_reasons(reasons: tuple[AuthReasonCode, ...]) -> None:
    raise HTTPException(
        status_code=_status_for_reasons(reasons),
        detail=[reason.value for reason in reasons],
    )


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        user_id=user.user_id,
        email=user.email,
        full_name=user.full_name,
        status=user.status.value,
    )


def _workspace_response(workspace: Workspace) -> WorkspaceResponse:
    return WorkspaceResponse(
        workspace_id=workspace.workspace_id,
        name=workspace.name,
        status=workspace.status.value,
        default_timezone=workspace.default_timezone,
    )


def _membership_response(membership: WorkspaceMembership) -> MembershipResponse:
    return MembershipResponse(
        membership_id=membership.membership_id,
        workspace_id=membership.workspace_id,
        user_id=membership.user_id,
        role=membership.role.value,
        status=membership.status.value,
    )


def _contact_policy_response(policy: WorkspaceContactPolicy) -> WorkspaceContactPolicyResponse:
    return WorkspaceContactPolicyResponse(
        workspace_id=policy.workspace_id,
        sms_compliance_state=policy.sms_compliance_state.value,
        quiet_hours_enabled=policy.quiet_hours_enabled,
        quiet_hours_start=policy.quiet_hours_start,
        quiet_hours_end=policy.quiet_hours_end,
        inbound_email_address=policy.inbound_email_address,
    )


def _handoff_config_response(config: WorkspaceHandoffConfig) -> WorkspaceHandoffConfigResponse:
    return WorkspaceHandoffConfigResponse(
        workspace_id=config.workspace_id,
        fallback_recipient_email=config.fallback_recipient_email,
        crm_handoff_tag=config.crm_handoff_tag,
        crm_custom_fields=dict(config.crm_custom_fields),
    )


def _crm_sync_config_response(config: WorkspaceCRMSyncConfig) -> WorkspaceCRMSyncConfigResponse:
    return WorkspaceCRMSyncConfigResponse(
        workspace_id=config.workspace_id,
        crm_sync_enabled=config.crm_sync_enabled,
        crm_sync_interval_seconds=config.crm_sync_interval_seconds,
    )


def _llm_config_response(
    config: WorkspaceLLMConfig,
    *,
    allowed_openrouter_models: tuple[str, ...],
) -> WorkspaceLLMConfigResponse:
    return WorkspaceLLMConfigResponse(
        workspace_id=config.workspace_id,
        openrouter_model=config.openrouter_model,
        allowed_openrouter_models=list(allowed_openrouter_models),
    )


def _operational_control_response(
    control: WorkspaceOperationalControl,
) -> WorkspaceOperationalControlResponse:
    return WorkspaceOperationalControlResponse(
        workspace_id=control.workspace_id,
        automation_status=control.automation_status.value,
        pause_reason=control.pause_reason,
    )


@router.post(
    "",
    response_model=CreateWorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_route(
    request: CreateWorkspaceRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_current_actor)],
    bundle: Annotated[AuthServiceBundle, Depends(get_auth_service_bundle)],
) -> CreateWorkspaceResponse:
    result = await create_workspace(
        actor=actor,
        name=request.name,
        default_timezone=request.default_timezone,
        user_repository=bundle.user_repository,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        audit_log_repository=bundle.audit_log_repository,
        now=datetime.now(UTC),
    )
    if bundle.session is not None:
        await bundle.session.commit()
    if result.status == CreateWorkspaceStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return CreateWorkspaceResponse(
        status=result.status.value,
        workspace=_workspace_response(result.workspace) if result.workspace else None,
        membership=_membership_response(result.membership) if result.membership else None,
    )


@router.get(
    "/{workspace_id}/settings",
    response_model=WorkspaceSettingsResponse,
)
async def get_workspace_settings_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[WorkspaceSettingsBundle, Depends(get_workspace_settings_bundle)],
) -> WorkspaceSettingsResponse:
    result = await get_workspace_settings(
        actor=actor,
        workspace_id=workspace_id,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        contact_policy_repository=bundle.workspace_contact_policy_repository,
        crm_sync_config_repository=bundle.workspace_crm_sync_config_repository,
        workspace_llm_config_repository=bundle.workspace_llm_config_repository,
        handoff_config_repository=bundle.workspace_handoff_config_repository,
        workspace_operational_control_repository=bundle.workspace_operational_control_repository,
        default_crm_sync_interval_seconds=bundle.default_crm_sync_interval_seconds,
        default_openrouter_model=bundle.default_openrouter_model,
    )
    if result.status == WorkspaceSettingsReadStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return WorkspaceSettingsResponse(
        status=result.status.value,
        workspace=_workspace_response(result.view.workspace) if result.view else None,
        contact_policy=(
            _contact_policy_response(result.view.contact_policy) if result.view else None
        ),
        crm_sync_config=(
            _crm_sync_config_response(result.view.crm_sync_config) if result.view else None
        ),
        llm_config=(
            _llm_config_response(
                result.view.llm_config,
                allowed_openrouter_models=bundle.allowed_openrouter_models,
            )
            if result.view
            else None
        ),
        handoff_config=(
            _handoff_config_response(result.view.handoff_config) if result.view else None
        ),
        operational_control=(
            _operational_control_response(result.view.operational_control)
            if result.view
            else None
        ),
    )


@router.patch(
    "/{workspace_id}/settings/contact-policy",
    response_model=UpdateWorkspaceContactPolicyResponse,
)
async def update_workspace_contact_policy_route(
    workspace_id: UUID,
    request: UpdateWorkspaceContactPolicyRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[WorkspaceSettingsBundle, Depends(get_workspace_settings_bundle)],
) -> UpdateWorkspaceContactPolicyResponse:
    result = await update_workspace_contact_policy(
        actor=actor,
        workspace_id=workspace_id,
        sms_compliance_state=request.sms_compliance_state,
        quiet_hours_enabled=request.quiet_hours_enabled,
        quiet_hours_start=request.quiet_hours_start,
        quiet_hours_end=request.quiet_hours_end,
        inbound_email_address=request.inbound_email_address,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        contact_policy_repository=bundle.workspace_contact_policy_repository,
        audit_log_repository=bundle.audit_log_repository,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    if result.status == UpdateWorkspaceContactPolicyStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return UpdateWorkspaceContactPolicyResponse(
        status=result.status.value,
        contact_policy=(
            _contact_policy_response(result.contact_policy)
            if result.contact_policy is not None
            else None
        ),
    )


@router.patch(
    "/{workspace_id}/settings/crm-sync",
    response_model=UpdateWorkspaceCRMSyncConfigResponse,
)
async def update_workspace_crm_sync_config_route(
    workspace_id: UUID,
    request: UpdateWorkspaceCRMSyncConfigRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[WorkspaceSettingsBundle, Depends(get_workspace_settings_bundle)],
) -> UpdateWorkspaceCRMSyncConfigResponse:
    result = await update_workspace_crm_sync_config(
        actor=actor,
        workspace_id=workspace_id,
        crm_sync_enabled=request.crm_sync_enabled,
        crm_sync_interval_seconds=request.crm_sync_interval_seconds,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        crm_sync_config_repository=bundle.workspace_crm_sync_config_repository,
        audit_log_repository=bundle.audit_log_repository,
        now=datetime.now(UTC),
        default_crm_sync_interval_seconds=bundle.default_crm_sync_interval_seconds,
    )
    await bundle.session.commit()
    if result.status == UpdateWorkspaceCRMSyncConfigStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return UpdateWorkspaceCRMSyncConfigResponse(
        status=result.status.value,
        crm_sync_config=(
            _crm_sync_config_response(result.crm_sync_config)
            if result.crm_sync_config is not None
            else None
        ),
    )


@router.patch(
    "/{workspace_id}/settings/llm",
    response_model=UpdateWorkspaceLLMConfigResponse,
)
async def update_workspace_llm_config_route(
    workspace_id: UUID,
    request: UpdateWorkspaceLLMConfigRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[WorkspaceSettingsBundle, Depends(get_workspace_settings_bundle)],
) -> UpdateWorkspaceLLMConfigResponse:
    result = await update_workspace_llm_config(
        actor=actor,
        workspace_id=workspace_id,
        openrouter_model=request.openrouter_model,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        workspace_llm_config_repository=bundle.workspace_llm_config_repository,
        audit_log_repository=bundle.audit_log_repository,
        now=datetime.now(UTC),
        default_openrouter_model=bundle.default_openrouter_model,
        allowed_openrouter_models=bundle.allowed_openrouter_models,
    )
    await bundle.session.commit()
    if result.status == UpdateWorkspaceLLMConfigStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return UpdateWorkspaceLLMConfigResponse(
        status=result.status.value,
        llm_config=(
            _llm_config_response(
                result.llm_config,
                allowed_openrouter_models=bundle.allowed_openrouter_models,
            )
            if result.llm_config is not None
            else None
        ),
    )


@router.patch(
    "/{workspace_id}/settings/automation",
    response_model=UpdateWorkspaceOperationalControlResponse,
)
async def update_workspace_operational_control_route(
    workspace_id: UUID,
    request: UpdateWorkspaceOperationalControlRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[WorkspaceSettingsBundle, Depends(get_workspace_settings_bundle)],
) -> UpdateWorkspaceOperationalControlResponse:
    result = await update_workspace_operational_control(
        actor=actor,
        workspace_id=workspace_id,
        automation_status=request.automation_status,
        pause_reason=request.pause_reason,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        workspace_operational_control_repository=bundle.workspace_operational_control_repository,
        audit_log_repository=bundle.audit_log_repository,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    if result.status == UpdateWorkspaceOperationalControlStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return UpdateWorkspaceOperationalControlResponse(
        status=result.status.value,
        operational_control=(
            _operational_control_response(result.operational_control)
            if result.operational_control is not None
            else None
        ),
    )


@router.patch(
    "/{workspace_id}/settings/handoff-config",
    response_model=UpdateWorkspaceHandoffConfigResponse,
)
async def update_workspace_handoff_config_route(
    workspace_id: UUID,
    request: UpdateWorkspaceHandoffConfigRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[WorkspaceSettingsBundle, Depends(get_workspace_settings_bundle)],
) -> UpdateWorkspaceHandoffConfigResponse:
    result = await update_workspace_handoff_config(
        actor=actor,
        workspace_id=workspace_id,
        fallback_recipient_email=(
            str(request.fallback_recipient_email)
            if request.fallback_recipient_email is not None
            else None
        ),
        crm_handoff_tag=request.crm_handoff_tag,
        crm_custom_fields=request.crm_custom_fields,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        handoff_config_repository=bundle.workspace_handoff_config_repository,
        audit_log_repository=bundle.audit_log_repository,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    if result.status == UpdateWorkspaceHandoffConfigStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return UpdateWorkspaceHandoffConfigResponse(
        status=result.status.value,
        handoff_config=(
            _handoff_config_response(result.handoff_config)
            if result.handoff_config is not None
            else None
        ),
    )


@router.patch(
    "/{workspace_id}/settings/timezone",
    response_model=UpdateWorkspaceTimezoneResponse,
)
async def update_workspace_timezone_route(
    workspace_id: UUID,
    request: UpdateWorkspaceTimezoneRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[WorkspaceSettingsBundle, Depends(get_workspace_settings_bundle)],
) -> UpdateWorkspaceTimezoneResponse:
    result = await update_workspace_default_timezone(
        actor=actor,
        workspace_id=workspace_id,
        default_timezone=request.default_timezone,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        audit_log_repository=bundle.audit_log_repository,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    if result.status == UpdateWorkspaceTimezoneStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return UpdateWorkspaceTimezoneResponse(
        status=result.status.value,
        workspace=_workspace_response(result.workspace) if result.workspace else None,
    )


@router.get(
    "/{workspace_id}/users",
    response_model=ListWorkspaceUsersResponse,
)
async def list_workspace_users_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[AuthServiceBundle, Depends(get_auth_service_bundle)],
) -> ListWorkspaceUsersResponse:
    result = await list_workspace_users(
        actor=actor,
        workspace_id=workspace_id,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        user_repository=bundle.user_repository,
        invitation_repository=bundle.invitation_repository,
    )
    if result.status == ListWorkspaceUsersStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return ListWorkspaceUsersResponse(
        status=result.status.value,
        users=[
            WorkspaceUserResponse(
                user=_user_response(workspace_user.user),
                membership=_membership_response(workspace_user.membership),
                invitation_id=workspace_user.invitation_id,
            )
            for workspace_user in result.users
        ],
    )


@router.post(
    "/{workspace_id}/users/invitations",
    response_model=InviteWorkspaceUserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_workspace_user_route(
    workspace_id: UUID,
    request: InviteWorkspaceUserRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[AuthServiceBundle, Depends(get_auth_service_bundle)],
) -> InviteWorkspaceUserResponse:
    result = await invite_workspace_user(
        actor=actor,
        workspace_id=workspace_id,
        email=request.email,
        role=request.role,
        full_name=request.full_name,
        user_repository=bundle.user_repository,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        invitation_repository=bundle.invitation_repository,
        audit_log_repository=bundle.audit_log_repository,
        opaque_token_service=bundle.opaque_token_service,
        email_provider=bundle.email_provider,
        frontend_app_base_url=bundle.settings.frontend_app_base_url,
        now=datetime.now(UTC),
    )
    if bundle.session is not None:
        await bundle.session.commit()
    if result.status == InviteWorkspaceUserStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return InviteWorkspaceUserResponse(
        status=result.status.value,
        user=_user_response(result.user) if result.user else None,
        membership=_membership_response(result.membership) if result.membership else None,
    )


@router.post(
    "/{workspace_id}/users/invitations/{invitation_id}/resend",
    response_model=ResendInvitationResponse,
)
async def resend_invitation_route(
    workspace_id: UUID,
    invitation_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[AuthServiceBundle, Depends(get_auth_service_bundle)],
) -> ResendInvitationResponse:
    result = await resend_invitation(
        actor=actor,
        workspace_id=workspace_id,
        invitation_id=invitation_id,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        invitation_repository=bundle.invitation_repository,
        audit_log_repository=bundle.audit_log_repository,
        opaque_token_service=bundle.opaque_token_service,
        email_provider=bundle.email_provider,
        frontend_app_base_url=bundle.settings.frontend_app_base_url,
        now=datetime.now(UTC),
    )
    if bundle.session is not None:
        await bundle.session.commit()
    if result.status == ResendInvitationStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return ResendInvitationResponse(
        status=result.status.value,
        invitation_id=result.invitation.invitation_id if result.invitation else None,
    )


@router.patch(
    "/{workspace_id}/users/{user_id}/membership",
    response_model=UpdateWorkspaceMembershipResponse,
)
async def update_workspace_membership_route(
    workspace_id: UUID,
    user_id: UUID,
    request: UpdateWorkspaceMembershipRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[AuthServiceBundle, Depends(get_auth_service_bundle)],
) -> UpdateWorkspaceMembershipResponse:
    result = await update_workspace_membership(
        actor=actor,
        workspace_id=workspace_id,
        user_id=user_id,
        role=request.role,
        membership_status=request.membership_status,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        user_repository=bundle.user_repository,
        invitation_repository=bundle.invitation_repository,
        audit_log_repository=bundle.audit_log_repository,
        now=datetime.now(UTC),
    )
    if bundle.session is not None:
        await bundle.session.commit()
    if result.status == UpdateWorkspaceMembershipStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return UpdateWorkspaceMembershipResponse(
        status=result.status.value,
        membership=_membership_response(result.membership) if result.membership else None,
    )


@router.patch(
    "/{workspace_id}/users/{user_id}/status",
    response_model=UpdateUserStatusResponse,
)
async def update_user_status_route(
    workspace_id: UUID,
    user_id: UUID,
    request: UpdateUserStatusRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[AuthServiceBundle, Depends(get_auth_service_bundle)],
) -> UpdateUserStatusResponse:
    result = await update_user_status(
        actor=actor,
        workspace_id=workspace_id,
        user_id=user_id,
        user_status=request.user_status,
        user_repository=bundle.user_repository,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        audit_log_repository=bundle.audit_log_repository,
        now=datetime.now(UTC),
    )
    if bundle.session is not None:
        await bundle.session.commit()
    if result.status == UpdateUserStatusStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return UpdateUserStatusResponse(
        status=result.status.value,
        user=_user_response(result.user) if result.user else None,
    )
