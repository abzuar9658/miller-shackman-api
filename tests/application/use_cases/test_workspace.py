from collections.abc import Coroutine
from datetime import time
from typing import TypeVar
from uuid import UUID

from app.application.use_cases.authentication import AuthReasonCode
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
    UpdateWorkspaceOutboundDraftingConfigStatus,
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
    update_workspace_outbound_drafting_config,
)
from app.domain.compliance import SmsComplianceState, WorkspaceContactPolicy
from app.domain.crm_sync import default_workspace_crm_sync_config
from app.domain.identity import (
    AuthAuditEventType,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.llm import default_workspace_llm_config
from app.domain.outbound_drafting import default_workspace_outbound_drafting_config
from app.domain.workspace_automation import (
    WorkspaceAutomationStatus,
    default_workspace_operational_control,
)
from tests.application.use_cases.test_authentication import (
    ADMIN_ID,
    INVITATION_ID,
    MEMBERSHIP_ID,
    NOW,
    SECOND_WORKSPACE_ID,
    USER_ID,
    WORKSPACE_ID,
    _actor,
    _Dependencies,
    _FakeWorkspaceContactPolicyRepository,
    _invitation,
    _membership,
    _user,
    _workspace,
)

T = TypeVar("T")

NEW_WORKSPACE_ID = UUID("00000000-0000-0000-0000-00000000000c")
NEW_USER_ID = UUID("00000000-0000-0000-0000-00000000000d")
NEW_MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-00000000000e")


def test_create_workspace_creates_workspace_and_admin_membership() -> None:
    deps = _Dependencies()
    actor = _actor()

    result = _run(
        create_workspace(
            actor=actor,
            name="New Brokerage",
            default_timezone="America/Chicago",
            user_repository=deps.user_repository,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == CreateWorkspaceStatus.CREATED
    assert result.workspace is not None
    assert result.workspace.name == "New Brokerage"
    assert result.workspace.status == WorkspaceStatus.ACTIVE
    assert result.membership is not None
    assert result.membership.role == WorkspaceMembershipRole.BROKERAGE_ADMIN
    assert result.membership.status == WorkspaceMembershipStatus.ACTIVE
    assert deps.audit_log_repository.logs[-1].event_type == AuthAuditEventType.WORKSPACE_CREATED


def test_create_workspace_rejects_without_permission() -> None:
    deps = _Dependencies()
    actor = _actor(role=WorkspaceMembershipRole.ASSIGNED_AGENT)

    result = _run(
        create_workspace(
            actor=actor,
            name="New Brokerage",
            default_timezone="America/Chicago",
            user_repository=deps.user_repository,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == CreateWorkspaceStatus.REJECTED
    assert result.reasons == (AuthReasonCode.PERMISSION_DENIED,)


def test_list_workspace_users_returns_users() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.users[ADMIN_ID] = _user(user_id=ADMIN_ID)
    deps.memberships[MEMBERSHIP_ID] = _membership(
        membership_id=MEMBERSHIP_ID,
        user_id=ADMIN_ID,
        role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
    )
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        list_workspace_users(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            user_repository=deps.user_repository,
            invitation_repository=deps.invitation_repository,
        ),
    )

    assert result.status == ListWorkspaceUsersStatus.FOUND
    assert len(result.users) == 1
    assert result.users[0].user.user_id == ADMIN_ID


def test_list_workspace_users_rejects_without_membership() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    actor = _actor(active_workspace_id=SECOND_WORKSPACE_ID)

    result = _run(
        list_workspace_users(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            user_repository=deps.user_repository,
            invitation_repository=deps.invitation_repository,
        ),
    )

    assert result.status == ListWorkspaceUsersStatus.REJECTED
    assert result.reasons == (AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,)


def test_resend_invitation_sends_new_email() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.users[USER_ID] = _user()
    deps.memberships[MEMBERSHIP_ID] = _membership(
        user_id=USER_ID,
        role=WorkspaceMembershipRole.MANAGER,
        status=WorkspaceMembershipStatus.INVITED,
    )
    deps.invitations[INVITATION_ID] = _invitation(
        token_hash="hash::old-token",
        role=WorkspaceMembershipRole.ASSIGNED_AGENT,
    )
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        resend_invitation(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            invitation_id=INVITATION_ID,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            invitation_repository=deps.invitation_repository,
            audit_log_repository=deps.audit_log_repository,
            opaque_token_service=deps.opaque_token_service,
            email_provider=deps.email_provider,
            frontend_app_base_url="https://app.millerschackman.test",
            now=NOW,
        ),
    )

    assert result.status == ResendInvitationStatus.RESENT
    assert result.invitation is not None
    assert result.invitation.token_hash == "hash::invite-token"
    assert result.invitation.role == WorkspaceMembershipRole.MANAGER
    assert len(deps.email_provider.messages) == 1
    assert deps.audit_log_repository.logs[-1].event_type == AuthAuditEventType.INVITATION_RESENT


def test_update_workspace_membership_changes_role() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.users[USER_ID] = _user()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.ASSIGNED_AGENT)
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_membership(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            user_id=USER_ID,
            role=WorkspaceMembershipRole.MANAGER,
            membership_status=None,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            user_repository=deps.user_repository,
            invitation_repository=deps.invitation_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateWorkspaceMembershipStatus.UPDATED
    assert result.membership is not None
    assert result.membership.role == WorkspaceMembershipRole.MANAGER
    assert deps.audit_log_repository.logs[-1].event_type == AuthAuditEventType.ROLE_CHANGED


def test_update_workspace_membership_disables_membership() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.users[USER_ID] = _user()
    deps.memberships[MEMBERSHIP_ID] = _membership()
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_membership(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            user_id=USER_ID,
            role=None,
            membership_status=WorkspaceMembershipStatus.DISABLED,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            user_repository=deps.user_repository,
            invitation_repository=deps.invitation_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateWorkspaceMembershipStatus.UPDATED
    assert result.membership is not None
    assert result.membership.status == WorkspaceMembershipStatus.DISABLED
    assert deps.audit_log_repository.logs[-1].event_type == AuthAuditEventType.MEMBERSHIP_DISABLED


def test_update_workspace_membership_syncs_pending_invitation_role() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.users[USER_ID] = _user()
    deps.memberships[MEMBERSHIP_ID] = _membership(
        role=WorkspaceMembershipRole.ASSIGNED_AGENT,
        status=WorkspaceMembershipStatus.INVITED,
    )
    deps.invitations[INVITATION_ID] = _invitation(role=WorkspaceMembershipRole.ASSIGNED_AGENT)
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_membership(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            user_id=USER_ID,
            role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
            membership_status=None,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            user_repository=deps.user_repository,
            invitation_repository=deps.invitation_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateWorkspaceMembershipStatus.UPDATED
    assert result.membership is not None
    assert result.membership.role == WorkspaceMembershipRole.BROKERAGE_ADMIN
    assert deps.invitations[INVITATION_ID].role == WorkspaceMembershipRole.BROKERAGE_ADMIN
    assert deps.invitations[INVITATION_ID].revoked_at is None


def test_update_workspace_membership_revokes_pending_invitation_when_leaving_invited() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.users[USER_ID] = _user()
    deps.memberships[MEMBERSHIP_ID] = _membership(status=WorkspaceMembershipStatus.INVITED)
    deps.invitations[INVITATION_ID] = _invitation()
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_membership(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            user_id=USER_ID,
            role=None,
            membership_status=WorkspaceMembershipStatus.DISABLED,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            user_repository=deps.user_repository,
            invitation_repository=deps.invitation_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateWorkspaceMembershipStatus.UPDATED
    assert result.membership is not None
    assert result.membership.status == WorkspaceMembershipStatus.DISABLED
    assert deps.invitations[INVITATION_ID].revoked_at == NOW


def test_update_user_status_disables_user() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.users[USER_ID] = _user()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_user_status(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            user_id=USER_ID,
            user_status=UserStatus.DISABLED,
            user_repository=deps.user_repository,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateUserStatusStatus.UPDATED
    assert result.user is not None
    assert result.user.status == UserStatus.DISABLED
    assert deps.audit_log_repository.logs[-1].event_type == AuthAuditEventType.USER_DISABLED


def test_get_workspace_settings_returns_defaults_when_missing() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        get_workspace_settings(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            contact_policy_repository=deps.workspace_contact_policy_repository,
            crm_sync_config_repository=deps.workspace_crm_sync_config_repository,
            workspace_llm_config_repository=deps.workspace_llm_config_repository,
            handoff_config_repository=deps.workspace_handoff_config_repository,
            workspace_outbound_drafting_config_repository=(
                deps.workspace_outbound_drafting_config_repository
            ),
            workspace_operational_control_repository=deps.workspace_operational_control_repository,
        ),
    )

    assert result.status == WorkspaceSettingsReadStatus.FOUND
    assert result.view is not None
    assert result.view.workspace.workspace_id == WORKSPACE_ID
    assert result.view.contact_policy.sms_compliance_state == SmsComplianceState.NOT_APPROVED
    assert result.view.crm_sync_config == default_workspace_crm_sync_config(WORKSPACE_ID)
    assert result.view.llm_config == default_workspace_llm_config(WORKSPACE_ID)
    assert result.view.outbound_drafting_config == default_workspace_outbound_drafting_config(
        WORKSPACE_ID
    )
    assert result.view.operational_control == default_workspace_operational_control(WORKSPACE_ID)
    assert result.view.handoff_config.crm_custom_fields == {}


def test_default_workspace_outbound_drafting_config_uses_polished_starter_values() -> None:
    config = default_workspace_outbound_drafting_config(WORKSPACE_ID)

    assert (
        config.prompt_text
        == "You are an administrative follow-up assistant for a real estate brokerage.\n"
        "Draft one compliant outbound message using only the approved JSON context below."
    )
    assert config.sms_template == "Hi there,\n\n{{message_body}}"
    assert config.email_template == "Hi there,\n\n{{message_body}}\n\nBest,\n{{brokerage_name}}"
    assert config.email_subject_template == "{{message_subject}} | {{brokerage_name}}"
    assert "Do not add a greeting or sign-off" in config.sms_prompt_text
    assert "Do not add a greeting, sign-off, sender name, or brokerage name" in (
        config.email_prompt_text
    )


def test_update_workspace_contact_policy_persists_values() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_contact_policy(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            sms_compliance_state=SmsComplianceState.APPROVED,
            quiet_hours_enabled=False,
            quiet_hours_start=time(9, 0),
            quiet_hours_end=time(16, 0),
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            contact_policy_repository=deps.workspace_contact_policy_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateWorkspaceContactPolicyStatus.UPDATED
    assert result.contact_policy is not None
    assert result.contact_policy.sms_compliance_state == SmsComplianceState.APPROVED
    assert result.contact_policy.quiet_hours_enabled is False
    assert result.contact_policy.quiet_hours_start == time(9, 0)
    assert deps.audit_log_repository.logs[-1].event_type == (
        AuthAuditEventType.WORKSPACE_CONTACT_POLICY_UPDATED
    )


def test_update_workspace_contact_policy_persists_inbound_email_address() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_contact_policy(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            sms_compliance_state=SmsComplianceState.APPROVED,
            quiet_hours_enabled=True,
            quiet_hours_start=time(9, 0),
            quiet_hours_end=time(16, 0),
            inbound_email_address="inbound@example.com",
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            contact_policy_repository=deps.workspace_contact_policy_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateWorkspaceContactPolicyStatus.UPDATED
    assert result.contact_policy is not None
    assert result.contact_policy.inbound_email_address == "inbound@example.com"


def test_update_workspace_contact_policy_preserves_inbound_email_when_not_provided() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)
    deps.workspace_contact_policy_repository = _FakeWorkspaceContactPolicyRepository(
        {
            WORKSPACE_ID: WorkspaceContactPolicy(
                workspace_id=WORKSPACE_ID,
                sms_compliance_state=SmsComplianceState.APPROVED,
                quiet_hours_enabled=True,
                quiet_hours_start=time(9, 0),
                quiet_hours_end=time(16, 0),
                inbound_email_address="inbound@example.com",
            ),
        }
    )
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_contact_policy(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            sms_compliance_state=SmsComplianceState.APPROVED,
            quiet_hours_enabled=True,
            quiet_hours_start=time(9, 0),
            quiet_hours_end=time(16, 0),
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            contact_policy_repository=deps.workspace_contact_policy_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateWorkspaceContactPolicyStatus.UPDATED
    assert result.contact_policy is not None
    assert result.contact_policy.inbound_email_address == "inbound@example.com"


def test_update_workspace_contact_policy_disables_quiet_hours_without_clearing_window() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_contact_policy(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            sms_compliance_state=SmsComplianceState.APPROVED,
            quiet_hours_enabled=False,
            quiet_hours_start=time(10, 0),
            quiet_hours_end=time(17, 0),
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            contact_policy_repository=deps.workspace_contact_policy_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateWorkspaceContactPolicyStatus.UPDATED
    assert result.contact_policy is not None
    assert result.contact_policy.quiet_hours_enabled is False
    assert result.contact_policy.quiet_hours_start == time(10, 0)
    assert result.contact_policy.quiet_hours_end == time(17, 0)


def test_update_workspace_handoff_config_normalizes_values() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_handoff_config(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            fallback_recipient_email=" fallback@example.com ",
            crm_handoff_tag=" human_handoff_required ",
            crm_custom_fields={" handoff_status ": " required ", "": "skip"},
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            handoff_config_repository=deps.workspace_handoff_config_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateWorkspaceHandoffConfigStatus.UPDATED
    assert result.handoff_config is not None
    assert result.handoff_config.fallback_recipient_email == "fallback@example.com"
    assert result.handoff_config.crm_handoff_tag == "human_handoff_required"
    assert dict(result.handoff_config.crm_custom_fields) == {"handoff_status": "required"}
    assert deps.audit_log_repository.logs[-1].event_type == (
        AuthAuditEventType.WORKSPACE_HANDOFF_CONFIG_UPDATED
    )


def test_update_workspace_crm_sync_config_persists_values() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_crm_sync_config(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            crm_sync_enabled=False,
            crm_sync_interval_seconds=900,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            crm_sync_config_repository=deps.workspace_crm_sync_config_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateWorkspaceCRMSyncConfigStatus.UPDATED
    assert result.crm_sync_config is not None
    assert result.crm_sync_config.crm_sync_enabled is False
    assert result.crm_sync_config.crm_sync_interval_seconds == 900
    assert deps.audit_log_repository.logs[-1].event_type == (
        AuthAuditEventType.WORKSPACE_CRM_SYNC_CONFIG_UPDATED
    )


def test_update_workspace_llm_config_persists_values() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_llm_config(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            openrouter_model="openai/gpt-4.1-mini",
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            workspace_llm_config_repository=deps.workspace_llm_config_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
            allowed_openrouter_models=("openai/gpt-4o-mini", "openai/gpt-4.1-mini"),
        ),
    )

    assert result.status == UpdateWorkspaceLLMConfigStatus.UPDATED
    assert result.llm_config is not None
    assert result.llm_config.openrouter_model == "openai/gpt-4.1-mini"
    assert deps.audit_log_repository.logs[-1].event_type == (
        AuthAuditEventType.WORKSPACE_LLM_CONFIG_UPDATED
    )


def test_update_workspace_llm_config_rejects_unapproved_model() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_llm_config(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            openrouter_model="anthropic/claude-3.5-sonnet",
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            workspace_llm_config_repository=deps.workspace_llm_config_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
            allowed_openrouter_models=("openai/gpt-4o-mini",),
        ),
    )

    assert result.status == UpdateWorkspaceLLMConfigStatus.REJECTED
    assert result.reasons == (AuthReasonCode.VALIDATION_ERROR,)


def test_update_workspace_outbound_drafting_config_persists_values() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_outbound_drafting_config(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            prompt_text=(
                "You are the brokerage's outreach assistant. Re-engage leads safely "
                "and tee up an agent follow-up."
            ),
            sms_prompt_text="Use a short conversational SMS tone.",
            sms_template="Hi {{agent_name}}",
            email_prompt_text="Use a concise professional email tone.",
            email_template="Regards,\nMiller Schackman",
            email_subject_template="{{message_subject}} | Miller Schackman",
            enabled_extraction_fields=("location", "max_price", "beds"),
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            workspace_outbound_drafting_config_repository=(
                deps.workspace_outbound_drafting_config_repository
            ),
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateWorkspaceOutboundDraftingConfigStatus.UPDATED
    assert result.outbound_drafting_config is not None
    assert (
        result.outbound_drafting_config.prompt_text
        == "You are the brokerage's outreach assistant. Re-engage leads safely "
        "and tee up an agent follow-up."
    )
    assert result.outbound_drafting_config.sms_prompt_text == "Use a short conversational SMS tone."
    assert result.outbound_drafting_config.sms_template == "Hi {{agent_name}}"
    assert (
        result.outbound_drafting_config.email_prompt_text
        == "Use a concise professional email tone."
    )
    assert (
        result.outbound_drafting_config.email_subject_template
        == "{{message_subject}} | Miller Schackman"
    )
    assert result.outbound_drafting_config.enabled_extraction_fields == (
        "location",
        "max_price",
        "beds",
    )
    assert deps.audit_log_repository.logs[-1].event_type == (
        AuthAuditEventType.WORKSPACE_OUTBOUND_DRAFTING_CONFIG_UPDATED
    )


def test_update_workspace_outbound_drafting_config_allows_templates_without_placeholders() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_outbound_drafting_config(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            prompt_text=(
                "You are the brokerage's outreach assistant. Keep the message body "
                "focused on a safe follow-up."
            ),
            sms_prompt_text="Use a short conversational SMS tone.",
            sms_template="Hi there",
            email_prompt_text="Use a concise professional email tone.",
            email_template="Regards,\nMiller Schackman",
            email_subject_template="Follow-up from the brokerage",
            enabled_extraction_fields=("location", "max_price"),
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            workspace_outbound_drafting_config_repository=(
                deps.workspace_outbound_drafting_config_repository
            ),
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateWorkspaceOutboundDraftingConfigStatus.UPDATED
    assert result.outbound_drafting_config is not None
    assert result.outbound_drafting_config.sms_prompt_text == "Use a short conversational SMS tone."
    assert result.outbound_drafting_config.email_template == "Regards,\nMiller Schackman"
    assert (
        result.outbound_drafting_config.email_prompt_text
        == "Use a concise professional email tone."
    )
    assert result.outbound_drafting_config.email_subject_template == "Follow-up from the brokerage"


def test_update_workspace_operational_control_persists_values() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_operational_control(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            automation_status=WorkspaceAutomationStatus.PAUSED,
            pause_reason="Brokerage requested a temporary pause.",
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            workspace_operational_control_repository=deps.workspace_operational_control_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateWorkspaceOperationalControlStatus.UPDATED
    assert result.operational_control is not None
    assert result.operational_control.automation_status == WorkspaceAutomationStatus.PAUSED
    assert result.operational_control.pause_reason == "Brokerage requested a temporary pause."
    assert deps.audit_log_repository.logs[-1].event_type == (
        AuthAuditEventType.WORKSPACE_OPERATIONAL_CONTROL_UPDATED
    )


def test_update_workspace_default_timezone_updates_workspace() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_default_timezone(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            default_timezone="America/New_York",
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateWorkspaceTimezoneStatus.UPDATED
    assert result.workspace is not None
    assert result.workspace.default_timezone == "America/New_York"
    assert deps.audit_log_repository.logs[-1].event_type == (
        AuthAuditEventType.WORKSPACE_TIMEZONE_UPDATED
    )


def _run[T](coroutine: Coroutine[object, object, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)
