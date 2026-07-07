from uuid import UUID

from app.domain.identity.models import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.identity.permissions import (
    PermissionCapability,
    PermissionContext,
    PermissionReasonCode,
    evaluate_permission,
)


def _actor(
    *,
    user_status: UserStatus = UserStatus.ACTIVE,
    role: WorkspaceMembershipRole | None = WorkspaceMembershipRole.ASSIGNED_AGENT,
    workspace_status: WorkspaceStatus | None = WorkspaceStatus.ACTIVE,
    membership_status: WorkspaceMembershipStatus | None = WorkspaceMembershipStatus.ACTIVE,
) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        user_status=user_status,
        active_role=role,
        active_workspace_id=UUID("00000000-0000-0000-0000-000000000010"),
        active_workspace_status=workspace_status,
        active_membership_id=UUID("00000000-0000-0000-0000-000000000020"),
        active_membership_status=membership_status,
    )


def test_platform_super_admin_can_create_workspace_without_active_workspace_context() -> None:
    actor = AuthenticatedActor(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        user_status=UserStatus.ACTIVE,
        active_role=WorkspaceMembershipRole.PLATFORM_SUPER_ADMIN,
    )

    decision = evaluate_permission(actor, PermissionCapability.CREATE_WORKSPACE)

    assert decision.allowed is True
    assert decision.reasons == ()


def test_brokerage_admin_can_create_workspace() -> None:
    decision = evaluate_permission(
        _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN),
        PermissionCapability.CREATE_WORKSPACE,
    )

    assert decision.allowed is True
    assert decision.reasons == ()


def test_inactive_user_is_blocked_before_role_rules() -> None:
    decision = evaluate_permission(
        _actor(user_status=UserStatus.DISABLED),
        PermissionCapability.PAUSE_CAMPAIGN,
    )

    assert decision.allowed is False
    assert decision.reasons == (PermissionReasonCode.USER_NOT_ACTIVE,)


def test_inactive_workspace_blocks_business_action() -> None:
    decision = evaluate_permission(
        _actor(workspace_status=WorkspaceStatus.SUSPENDED),
        PermissionCapability.VIEW_OWN_ASSIGNED_LEAD,
    )

    assert decision.allowed is False
    assert decision.reasons == (PermissionReasonCode.WORKSPACE_NOT_ACTIVE,)


def test_invited_membership_blocks_business_action() -> None:
    decision = evaluate_permission(
        _actor(membership_status=WorkspaceMembershipStatus.INVITED),
        PermissionCapability.VIEW_OWN_ASSIGNED_LEAD,
    )

    assert decision.allowed is False
    assert decision.reasons == (PermissionReasonCode.MEMBERSHIP_NOT_ACTIVE,)


def test_assigned_agent_can_view_own_assigned_lead() -> None:
    decision = evaluate_permission(
        _actor(),
        PermissionCapability.VIEW_OWN_ASSIGNED_LEAD,
        PermissionContext(acts_on_assigned_lead=True),
    )

    assert decision.allowed is True
    assert decision.reasons == ()


def test_assigned_agent_cannot_view_unowned_lead() -> None:
    decision = evaluate_permission(
        _actor(),
        PermissionCapability.VIEW_OWN_ASSIGNED_LEAD,
    )

    assert decision.allowed is False
    assert decision.reasons == (PermissionReasonCode.OWNERSHIP_REQUIRED,)


def test_assigned_agent_enrollment_requires_campaign_to_allow_it() -> None:
    decision = evaluate_permission(
        _actor(),
        PermissionCapability.ENROLL_OWN_LEAD_WHEN_CAMPAIGN_ALLOWS,
        PermissionContext(
            acts_on_assigned_lead=True,
            campaign_allows_assigned_agent_enrollment=False,
        ),
    )

    assert decision.allowed is False
    assert decision.reasons == (
        PermissionReasonCode.CAMPAIGN_DISALLOWS_ASSIGNED_AGENT_ENROLLMENT,
    )


def test_assigned_agent_resume_requires_reason() -> None:
    decision = evaluate_permission(
        _actor(),
        PermissionCapability.RESUME_AI_AFTER_HANDOFF_OWN_LEAD,
        PermissionContext(
            acts_on_assigned_lead=True,
            handoff_resume_reason_provided=False,
        ),
    )

    assert decision.allowed is False
    assert decision.reasons == (PermissionReasonCode.RESUME_REASON_REQUIRED,)


def test_manager_can_enroll_any_eligible_lead() -> None:
    decision = evaluate_permission(
        _actor(role=WorkspaceMembershipRole.MANAGER),
        PermissionCapability.ENROLL_ANY_ELIGIBLE_LEAD,
    )

    assert decision.allowed is True
    assert decision.reasons == ()


def test_brokerage_admin_can_invite_workspace_user() -> None:
    decision = evaluate_permission(
        _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN),
        PermissionCapability.INVITE_WORKSPACE_USER,
    )

    assert decision.allowed is True
    assert decision.reasons == ()


def test_brokerage_admin_can_launch_campaign() -> None:
    decision = evaluate_permission(
        _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN),
        PermissionCapability.LAUNCH_OR_PUBLISH_CAMPAIGN,
    )

    assert decision.allowed is True
    assert decision.reasons == ()


def test_assigned_agent_cannot_pause_campaign() -> None:
    decision = evaluate_permission(
        _actor(),
        PermissionCapability.PAUSE_CAMPAIGN,
    )

    assert decision.allowed is False
    assert decision.reasons == (PermissionReasonCode.ROLE_NOT_ALLOWED,)


def test_platform_super_admin_is_restricted_from_business_actions() -> None:
    decision = evaluate_permission(
        _actor(role=WorkspaceMembershipRole.PLATFORM_SUPER_ADMIN),
        PermissionCapability.PAUSE_CAMPAIGN,
    )

    assert decision.allowed is False
    assert decision.reasons == (PermissionReasonCode.PLATFORM_SUPER_ADMIN_RESTRICTED,)