from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.services.authentication import IssuedSessionTokens
from app.application.use_cases.authentication import (
    AuthReasonCode,
    CompleteInvitedSignupStatus,
    CurrentUserStatus,
    RefreshAuthenticationStatus,
    ResetPasswordStatus,
    SignInStatus,
    SwitchWorkspaceStatus,
    complete_invited_signup,
    get_current_user,
    logout_all_sessions,
    logout_current_session,
    refresh_authentication,
    request_password_reset,
    reset_password,
    sign_in,
    switch_active_workspace,
)
from app.domain.identity import AuthenticatedActor, User, Workspace, WorkspaceMembership
from app.interfaces.api.dependencies.auth import (
    AuthServiceBundle,
    get_auth_service_bundle,
    get_current_actor,
)
from app.interfaces.api.schemas.auth import (
    CompleteInvitedSignupRequest,
    CompleteInvitedSignupResponse,
    CurrentUserResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LogoutAllResponse,
    LogoutRequest,
    LogoutResponse,
    MembershipResponse,
    RefreshAuthenticationRequest,
    RefreshAuthenticationResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SignInRequest,
    SignInResponse,
    SwitchWorkspaceRequest,
    SwitchWorkspaceResponse,
    TokenPair,
    UserResponse,
    WorkspaceResponse,
)

router = APIRouter(tags=["auth"])


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


def _token_pair(tokens: IssuedSessionTokens) -> TokenPair:
    return TokenPair(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        access_token_expires_at=tokens.access_token_expires_at,
        refresh_token_expires_at=tokens.refresh_token_expires_at,
    )


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


def _require_active_workspace_id(actor: AuthenticatedActor) -> UUID:
    if actor.active_workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active workspace",
        )
    return actor.active_workspace_id


@router.post(
    "/signup",
    response_model=CompleteInvitedSignupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def complete_signup(
    request: CompleteInvitedSignupRequest,
    bundle: Annotated[AuthServiceBundle, Depends(get_auth_service_bundle)],
) -> CompleteInvitedSignupResponse:
    result = await complete_invited_signup(
        invitation_token=request.invitation_token,
        full_name=request.full_name,
        password=request.password,
        user_repository=bundle.user_repository,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        credential_repository=bundle.credential_repository,
        invitation_repository=bundle.invitation_repository,
        refresh_session_repository=bundle.refresh_session_repository,
        audit_log_repository=bundle.audit_log_repository,
        password_hasher=bundle.password_hasher,
        access_token_service=bundle.access_token_service,
        opaque_token_service=bundle.opaque_token_service,
        now=datetime.now(UTC),
    )
    if result.status == CompleteInvitedSignupStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return CompleteInvitedSignupResponse(
        status=result.status.value,
        user=_user_response(result.user) if result.user else None,
        workspace=_workspace_response(result.workspace) if result.workspace else None,
        tokens=_token_pair(result.tokens) if result.tokens else None,
    )


@router.post("/signin", response_model=SignInResponse)
async def signin(
    request: SignInRequest,
    bundle: Annotated[AuthServiceBundle, Depends(get_auth_service_bundle)],
) -> SignInResponse:
    result = await sign_in(
        email=request.email,
        password=request.password,
        workspace_id=request.workspace_id,
        user_repository=bundle.user_repository,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        credential_repository=bundle.credential_repository,
        refresh_session_repository=bundle.refresh_session_repository,
        audit_log_repository=bundle.audit_log_repository,
        password_hasher=bundle.password_hasher,
        access_token_service=bundle.access_token_service,
        opaque_token_service=bundle.opaque_token_service,
        now=datetime.now(UTC),
    )
    if result.status == SignInStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return SignInResponse(
        status=result.status.value,
        user=_user_response(result.user) if result.user else None,
        workspace=_workspace_response(result.workspace) if result.workspace else None,
        tokens=_token_pair(result.tokens) if result.tokens else None,
    )


@router.post("/refresh", response_model=RefreshAuthenticationResponse)
async def refresh(
    request: RefreshAuthenticationRequest,
    bundle: Annotated[AuthServiceBundle, Depends(get_auth_service_bundle)],
) -> RefreshAuthenticationResponse:
    result = await refresh_authentication(
        refresh_token=request.refresh_token,
        user_repository=bundle.user_repository,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        refresh_session_repository=bundle.refresh_session_repository,
        access_token_service=bundle.access_token_service,
        opaque_token_service=bundle.opaque_token_service,
        now=datetime.now(UTC),
    )
    if result.status == RefreshAuthenticationStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return RefreshAuthenticationResponse(
        status=result.status.value,
        user=_user_response(result.user) if result.user else None,
        workspace=_workspace_response(result.workspace) if result.workspace else None,
        tokens=_token_pair(result.tokens) if result.tokens else None,
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: LogoutRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_current_actor)],
    bundle: Annotated[AuthServiceBundle, Depends(get_auth_service_bundle)],
) -> LogoutResponse:
    result = await logout_current_session(
        actor=actor,
        refresh_token=request.refresh_token,
        refresh_session_repository=bundle.refresh_session_repository,
        audit_log_repository=bundle.audit_log_repository,
        opaque_token_service=bundle.opaque_token_service,
        now=datetime.now(UTC),
    )
    return LogoutResponse(status=result.status.value, revoked=result.revoked)


@router.post("/logout-all", response_model=LogoutAllResponse)
async def logout_all(
    actor: Annotated[AuthenticatedActor, Depends(get_current_actor)],
    bundle: Annotated[AuthServiceBundle, Depends(get_auth_service_bundle)],
) -> LogoutAllResponse:
    result = await logout_all_sessions(
        actor=actor,
        refresh_session_repository=bundle.refresh_session_repository,
        audit_log_repository=bundle.audit_log_repository,
        now=datetime.now(UTC),
    )
    return LogoutAllResponse(status=result.status.value, revoked=result.revoked)


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def forgot_password(
    request: ForgotPasswordRequest,
    bundle: Annotated[AuthServiceBundle, Depends(get_auth_service_bundle)],
) -> ForgotPasswordResponse:
    result = await request_password_reset(
        email=request.email,
        user_repository=bundle.user_repository,
        credential_repository=bundle.credential_repository,
        reset_token_repository=bundle.reset_token_repository,
        audit_log_repository=bundle.audit_log_repository,
        opaque_token_service=bundle.opaque_token_service,
        email_provider=bundle.email_provider,
        now=datetime.now(UTC),
    )
    return ForgotPasswordResponse(status=result.status.value)


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password_route(
    request: ResetPasswordRequest,
    bundle: Annotated[AuthServiceBundle, Depends(get_auth_service_bundle)],
) -> ResetPasswordResponse:
    result = await reset_password(
        reset_token=request.reset_token,
        new_password=request.new_password,
        user_repository=bundle.user_repository,
        credential_repository=bundle.credential_repository,
        reset_token_repository=bundle.reset_token_repository,
        refresh_session_repository=bundle.refresh_session_repository,
        audit_log_repository=bundle.audit_log_repository,
        password_hasher=bundle.password_hasher,
        opaque_token_service=bundle.opaque_token_service,
        now=datetime.now(UTC),
    )
    if result.status == ResetPasswordStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return ResetPasswordResponse(
        status=result.status.value,
        user=_user_response(result.user) if result.user else None,
    )


@router.get("/me", response_model=CurrentUserResponse)
async def current_user(
    actor: Annotated[AuthenticatedActor, Depends(get_current_actor)],
    bundle: Annotated[AuthServiceBundle, Depends(get_auth_service_bundle)],
) -> CurrentUserResponse:
    result = await get_current_user(
        actor=actor,
        user_repository=bundle.user_repository,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
    )
    if result.status == CurrentUserStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return CurrentUserResponse(
        status=result.status.value,
        user=_user_response(result.user) if result.user else None,
        workspace=_workspace_response(result.workspace) if result.workspace else None,
        membership=_membership_response(result.membership) if result.membership else None,
        permissions=list(result.permissions),
    )


@router.post("/switch-workspace", response_model=SwitchWorkspaceResponse)
async def switch_workspace(
    request: SwitchWorkspaceRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_current_actor)],
    bundle: Annotated[AuthServiceBundle, Depends(get_auth_service_bundle)],
) -> SwitchWorkspaceResponse:
    result = await switch_active_workspace(
        actor=actor,
        workspace_id=request.workspace_id,
        user_repository=bundle.user_repository,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        access_token_service=bundle.access_token_service,
        now=datetime.now(UTC),
    )
    if result.status == SwitchWorkspaceStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return SwitchWorkspaceResponse(
        status=result.status.value,
        workspace=_workspace_response(result.workspace) if result.workspace else None,
        access_token=result.access_token,
        access_token_expires_at=result.access_token_expires_at,
    )
