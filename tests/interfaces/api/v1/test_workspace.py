from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
)
from app.interfaces.api.dependencies.auth import (
    AuthServiceBundle,
    get_auth_service_bundle,
    get_current_actor,
)
from app.interfaces.api.dependencies.workspace_settings import (
    WorkspaceSettingsBundle,
    get_workspace_settings_bundle,
)
from app.main import create_app
from tests.application.use_cases.test_authentication import (
    ADMIN_ID,
    INVITATION_ID,
    MEMBERSHIP_ID,
    USER_ID,
    WORKSPACE_ID,
    _actor,
    _Dependencies,
    _invitation,
    _membership,
    _user,
    _workspace,
)


class WorkspaceTestClient:
    def __init__(self, client: TestClient, deps: _Dependencies) -> None:
        self.client = client
        self.deps = deps


class _NoopSession:
    async def commit(self) -> None:
        return None


@pytest.fixture
def workspace_client() -> WorkspaceTestClient:
    app = create_app()
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.users[ADMIN_ID] = _user(user_id=ADMIN_ID, status=UserStatus.ACTIVE)
    deps.memberships[MEMBERSHIP_ID] = _membership(
        membership_id=MEMBERSHIP_ID,
        user_id=ADMIN_ID,
        role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
    )
    bundle = AuthServiceBundle(
        user_repository=deps.user_repository,
        workspace_repository=deps.workspace_repository,
        membership_repository=deps.membership_repository,
        credential_repository=deps.credential_repository,
        refresh_session_repository=deps.refresh_session_repository,
        reset_token_repository=deps.reset_token_repository,
        invitation_repository=deps.invitation_repository,
        audit_log_repository=deps.audit_log_repository,
        password_hasher=deps.password_hasher,
        access_token_service=deps.access_token_service,
        opaque_token_service=deps.opaque_token_service,
        email_provider=deps.email_provider,
        settings=get_settings(),
    )

    def override_get_auth_service_bundle() -> AuthServiceBundle:
        return bundle

    def override_get_current_actor() -> AuthenticatedActor:
        return _actor(
            user_id=ADMIN_ID,
            role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
        )

    app.dependency_overrides[get_auth_service_bundle] = override_get_auth_service_bundle
    app.dependency_overrides[get_current_actor] = override_get_current_actor

    def override_get_workspace_settings_bundle() -> WorkspaceSettingsBundle:
        return WorkspaceSettingsBundle(
            session=_NoopSession(),
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            audit_log_repository=deps.audit_log_repository,
            workspace_contact_policy_repository=deps.workspace_contact_policy_repository,
            workspace_crm_sync_config_repository=deps.workspace_crm_sync_config_repository,
            workspace_llm_config_repository=deps.workspace_llm_config_repository,
            workspace_handoff_config_repository=deps.workspace_handoff_config_repository,
            workspace_outbound_drafting_config_repository=(
                deps.workspace_outbound_drafting_config_repository
            ),
            workspace_operational_control_repository=deps.workspace_operational_control_repository,
            lead_workflow_repository=deps.lead_workflow_repository,
            workflow_transition_repository=deps.workflow_transition_repository,
            temporal_signal_outbox_repository=deps.temporal_signal_outbox_repository,
            default_crm_sync_interval_seconds=300,
            default_openrouter_model="openai/gpt-4o-mini",
            allowed_openrouter_models=("openai/gpt-4o-mini", "openai/gpt-4.1-mini"),
        )

    app.dependency_overrides[get_workspace_settings_bundle] = override_get_workspace_settings_bundle

    return WorkspaceTestClient(TestClient(app), deps)


def test_create_workspace_returns_201(workspace_client: WorkspaceTestClient) -> None:
    response = workspace_client.client.post(
        "/api/v1/workspaces",
        json={"name": "New Brokerage", "default_timezone": "America/Chicago"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "created"
    assert body["workspace"]["name"] == "New Brokerage"
    assert body["membership"]["role"] == "brokerage_admin"


def test_list_workspace_users_returns_200(workspace_client: WorkspaceTestClient) -> None:
    invited_membership_id = UUID("00000000-0000-0000-0000-00000000000f")
    workspace_client.deps.users[USER_ID] = _user(status=UserStatus.PENDING_VERIFICATION)
    workspace_client.deps.memberships[invited_membership_id] = _membership(
        membership_id=invited_membership_id,
        user_id=USER_ID,
        role=WorkspaceMembershipRole.MANAGER,
        status=WorkspaceMembershipStatus.INVITED,
    )
    workspace_client.deps.invitations[INVITATION_ID] = _invitation(token_hash="hash::invite-token")

    response = workspace_client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/users")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "found"
    assert len(body["users"]) == 2
    invited_user = next(
        user
        for user in body["users"]
        if user["membership"]["membership_id"] == str(invited_membership_id)
    )
    assert invited_user["invitation_id"] == str(INVITATION_ID)


def test_invite_user_returns_201(workspace_client: WorkspaceTestClient) -> None:
    response = workspace_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/users/invitations",
        json={"email": "agent@example.com", "role": "assigned_agent", "full_name": "Agent Smith"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "invited"
    assert body["user"]["email"] == "agent@example.com"
    assert body["membership"]["role"] == "assigned_agent"


def test_resend_invitation_returns_200(workspace_client: WorkspaceTestClient) -> None:
    workspace_client.deps.users[USER_ID] = _user(status=UserStatus.PENDING_VERIFICATION)
    workspace_client.deps.memberships[UUID("00000000-0000-0000-0000-000000000010")] = _membership(
        user_id=USER_ID,
        role=WorkspaceMembershipRole.ASSIGNED_AGENT,
        status=WorkspaceMembershipStatus.INVITED,
    )
    workspace_client.deps.invitations[INVITATION_ID] = _invitation(token_hash="hash::old-token")

    response = workspace_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/users/invitations/{INVITATION_ID}/resend",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resent"
    assert body["invitation_id"] == str(INVITATION_ID)


def test_update_workspace_membership_returns_200(workspace_client: WorkspaceTestClient) -> None:
    user_membership_id = UUID("00000000-0000-0000-0000-000000000010")
    workspace_client.deps.users[USER_ID] = _user()
    workspace_client.deps.memberships[user_membership_id] = _membership(
        membership_id=user_membership_id,
        role=WorkspaceMembershipRole.ASSIGNED_AGENT,
    )

    response = workspace_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/users/{USER_ID}/membership",
        json={"role": "manager"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "updated"
    assert body["membership"]["role"] == "manager"


def test_update_user_status_returns_200(workspace_client: WorkspaceTestClient) -> None:
    user_membership_id = UUID("00000000-0000-0000-0000-000000000011")
    workspace_client.deps.users[USER_ID] = _user()
    workspace_client.deps.memberships[user_membership_id] = _membership(
        membership_id=user_membership_id,
        role=WorkspaceMembershipRole.ASSIGNED_AGENT,
    )

    response = workspace_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/users/{USER_ID}/status",
        json={"user_status": "disabled"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "updated"
    assert body["user"]["status"] == "disabled"


def test_get_workspace_settings_returns_crm_sync_defaults(
    workspace_client: WorkspaceTestClient,
) -> None:
    response = workspace_client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "found"
    assert body["contact_policy"] == {
        "workspace_id": str(WORKSPACE_ID),
        "sms_compliance_state": "not_approved",
        "quiet_hours_enabled": True,
        "quiet_hours_start": "10:00:00",
        "quiet_hours_end": "17:00:00",
        "inbound_email_address": None,
    }
    assert body["crm_sync_config"] == {
        "workspace_id": str(WORKSPACE_ID),
        "crm_sync_enabled": True,
        "crm_sync_interval_seconds": 300,
        "max_leads_per_sync_cycle": None,
    }
    assert body["llm_config"] == {
        "workspace_id": str(WORKSPACE_ID),
        "openrouter_model": "openai/gpt-4o-mini",
        "allowed_openrouter_models": ["openai/gpt-4o-mini", "openai/gpt-4.1-mini"],
    }
    assert body["operational_control"] == {
        "workspace_id": str(WORKSPACE_ID),
        "automation_status": "active",
        "pause_reason": None,
        "recurring_paused_search_enabled": False,
    }
    assert body["handoff_config"] == {
        "workspace_id": str(WORKSPACE_ID),
        "fallback_recipient_email": None,
        "crm_handoff_tag": None,
        "crm_review_tag": None,
        "crm_custom_fields": {},
        "lead_acknowledgment_sms_enabled": False,
        "lead_acknowledgment_sms_body": None,
        "lead_acknowledgment_email_enabled": False,
        "lead_acknowledgment_email_subject": None,
        "lead_acknowledgment_email_body": None,
        "lead_acknowledgment_prompt_text": None,
        "crm_snapshot_summary_field": None,
        "crm_snapshot_status_field": None,
        "crm_snapshot_latest_inbound_field": None,
        "crm_snapshot_latest_outbound_field": None,
        "crm_snapshot_last_activity_at_field": None,
    }


def test_update_workspace_handoff_config_returns_200(
    workspace_client: WorkspaceTestClient,
) -> None:
    response = workspace_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/settings/handoff-config",
        json={
            "fallback_recipient_email": "review@example.com",
            "crm_handoff_tag": "human_handoff_required",
            "crm_review_tag": "needs_agent_review",
            "crm_custom_fields": {"handoff_status": "required"},
            "crm_snapshot_summary_field": "ai_summary",
            "crm_snapshot_status_field": "ai_status",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "updated"
    assert body["handoff_config"] == {
        "workspace_id": str(WORKSPACE_ID),
        "fallback_recipient_email": "review@example.com",
        "crm_handoff_tag": "human_handoff_required",
        "crm_review_tag": "needs_agent_review",
        "crm_custom_fields": {"handoff_status": "required"},
        "lead_acknowledgment_sms_enabled": False,
        "lead_acknowledgment_sms_body": None,
        "lead_acknowledgment_email_enabled": False,
        "lead_acknowledgment_email_subject": None,
        "lead_acknowledgment_email_body": None,
        "lead_acknowledgment_prompt_text": None,
        "crm_snapshot_summary_field": "ai_summary",
        "crm_snapshot_status_field": "ai_status",
        "crm_snapshot_latest_inbound_field": None,
        "crm_snapshot_latest_outbound_field": None,
        "crm_snapshot_last_activity_at_field": None,
    }


def test_update_workspace_crm_sync_config_returns_200(
    workspace_client: WorkspaceTestClient,
) -> None:
    response = workspace_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/settings/crm-sync",
        json={
            "crm_sync_enabled": False,
            "crm_sync_interval_seconds": 900,
            "max_leads_per_sync_cycle": 250,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "updated"
    assert body["crm_sync_config"] == {
        "workspace_id": str(WORKSPACE_ID),
        "crm_sync_enabled": False,
        "crm_sync_interval_seconds": 900,
        "max_leads_per_sync_cycle": 250,
    }


def test_update_workspace_llm_config_returns_200(
    workspace_client: WorkspaceTestClient,
) -> None:
    response = workspace_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/settings/llm",
        json={"openrouter_model": "openai/gpt-4.1-mini"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "updated"
    assert body["llm_config"] == {
        "workspace_id": str(WORKSPACE_ID),
        "openrouter_model": "openai/gpt-4.1-mini",
        "allowed_openrouter_models": ["openai/gpt-4o-mini", "openai/gpt-4.1-mini"],
    }


def test_update_workspace_outbound_drafting_config_returns_200(
    workspace_client: WorkspaceTestClient,
) -> None:
    response = workspace_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/settings/outbound-drafting",
        json={
            "prompt_text": (
                "You are the brokerage's outreach assistant. Re-engage leads safely "
                "and tee up the assigned agent."
            ),
            "sms_prompt_text": "Use a short conversational SMS tone.",
            "sms_template": "Hi {{agent_name}}",
            "email_prompt_text": "Use a concise professional email tone.",
            "email_template": "Regards,\nMiller Schackman",
            "email_subject_template": "{{message_subject}} | Miller Schackman",
            "enabled_extraction_fields": ["location", "max_price"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "updated"
    assert body["outbound_drafting_config"] == {
        "workspace_id": str(WORKSPACE_ID),
        "revision": 1,
        "prompt_text": (
            "You are the brokerage's outreach assistant. Re-engage leads safely "
            "and tee up the assigned agent."
        ),
        "sms_prompt_text": "Use a short conversational SMS tone.",
        "sms_template": "Hi {{agent_name}}",
        "email_prompt_text": "Use a concise professional email tone.",
        "email_template": "Regards,\nMiller Schackman",
        "email_subject_template": "{{message_subject}} | Miller Schackman",
        "enabled_extraction_fields": ["location", "max_price"],
        "supported_extraction_fields": [
            "address",
            "location",
            "keywords",
            "search_type",
            "beds",
            "min_price",
            "max_price",
            "price_band",
        ],
        "supported_template_placeholders": [
            "agent_name",
            "brokerage_name",
            "lead_first_name",
            "message_body",
            "message_subject",
        ],
    }


def test_update_workspace_outbound_drafting_config_allows_templates_without_placeholders(
    workspace_client: WorkspaceTestClient,
) -> None:
    response = workspace_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/settings/outbound-drafting",
        json={
            "prompt_text": (
                "You are the brokerage's outreach assistant. Keep the message focused "
                "on a safe follow-up."
            ),
            "sms_prompt_text": "Use a short conversational SMS tone.",
            "sms_template": "Hi there",
            "email_prompt_text": "Use a concise professional email tone.",
            "email_template": "Regards,\nMiller Schackman",
            "email_subject_template": "Follow-up from the brokerage",
            "enabled_extraction_fields": ["location", "max_price"],
        },
    )

    assert response.status_code == 200


def test_update_workspace_operational_control_returns_200(
    workspace_client: WorkspaceTestClient,
) -> None:
    response = workspace_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/settings/automation",
        json={
            "automation_status": "paused",
            "pause_reason": "Brokerage requested a temporary pause.",
            "recurring_paused_search_enabled": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "updated"
    assert body["operational_control"] == {
        "workspace_id": str(WORKSPACE_ID),
        "automation_status": "paused",
        "pause_reason": "Brokerage requested a temporary pause.",
        "recurring_paused_search_enabled": True,
    }


def test_update_workspace_contact_policy_returns_200(
    workspace_client: WorkspaceTestClient,
) -> None:
    response = workspace_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/settings/contact-policy",
        json={
            "sms_compliance_state": "approved",
            "quiet_hours_enabled": False,
            "quiet_hours_start": "10:00:00",
            "quiet_hours_end": "17:00:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "updated"
    assert body["contact_policy"] == {
        "workspace_id": str(WORKSPACE_ID),
        "sms_compliance_state": "approved",
        "quiet_hours_enabled": False,
        "quiet_hours_start": "10:00:00",
        "quiet_hours_end": "17:00:00",
        "inbound_email_address": None,
    }
