from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.interfaces.api.dependencies.campaign import (
    CampaignReadBundle,
    CampaignServiceBundle,
    get_campaign_read_bundle,
    get_campaign_service_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.main import create_app
from tests.application.use_cases._campaign_admin_fakes import (
    FakeCampaignAdminAuditLogRepository,
    FakeCampaignAdminRepository,
    FakeEventBus,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000005")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000006")


@dataclass
class CampaignAdminTestClient:
    client: TestClient
    campaign_repository: FakeCampaignAdminRepository
    audit_repository: FakeCampaignAdminAuditLogRepository
    event_bus: FakeEventBus
    session: object


@pytest.fixture
def campaign_admin_client() -> CampaignAdminTestClient:
    return _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)


def test_create_draft_campaign_route_returns_201(
    campaign_admin_client: CampaignAdminTestClient,
) -> None:
    response = campaign_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/campaigns",
        json=_payload(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "created"
    assert body["campaign"]["name"] == "Dormant Buyers"
    assert body["version"]["status"] == "draft"
    assert body["version"]["allow_assigned_agent_manual_enrollment"] is True
    assert body["version"]["prompt_text"] == "Draft dormant outreach with a calm tone."
    assert body["version"]["sms_template"] == "Hi {{lead_first_name}}, {{message_body}}"
    assert body["version"]["email_subject_template"] == "{{message_subject}}"
    assert body["version"]["enabled_extraction_fields"] == ["location", "max_price"]
    assert "message_body" in body["version"]["supported_template_placeholders"]
    assert len(body["cadence_steps"]) == 1
    assert body["cadence_steps"][0]["template_profile"]["tone"] == "warm"
    assert campaign_admin_client.audit_repository.logs[-1].action.value == "campaign_draft_created"
    assert campaign_admin_client.event_bus.events[-1].event_type.value == "campaign.draft_created"


def test_campaign_read_routes_return_list_and_detail(
    campaign_admin_client: CampaignAdminTestClient,
) -> None:
    create_response = campaign_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/campaigns",
        json=_payload(),
    )
    campaign_id = create_response.json()["campaign"]["campaign_id"]

    list_response = campaign_admin_client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/campaigns")
    detail_response = campaign_admin_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/campaigns/{campaign_id}"
    )

    assert list_response.status_code == 200
    assert list_response.json()["campaigns"][0]["campaign"]["name"] == "Dormant Buyers"
    assert list_response.json()["campaigns"][0]["cadence_step_count"] == 1
    assert detail_response.status_code == 200
    assert detail_response.json()["version"]["daily_start_cap"] == 50
    assert detail_response.json()["cadence_steps"][0]["template_key"] == "dormant-email-1"


def test_assigned_agent_cannot_view_campaign_list() -> None:
    client = _client_for_role(WorkspaceMembershipRole.ASSIGNED_AGENT)

    response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/campaigns")

    assert response.status_code == 403
    assert response.json()["detail"] == ["permission_denied"]


def test_platform_super_admin_can_create_and_view_campaigns() -> None:
    client = _client_for_role(WorkspaceMembershipRole.PLATFORM_SUPER_ADMIN)

    create_response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/campaigns",
        json=_payload(),
    )
    list_response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/campaigns")

    assert create_response.status_code == 201
    assert list_response.status_code == 200


def test_assigned_agent_cannot_create_campaign() -> None:
    client = _client_for_role(WorkspaceMembershipRole.ASSIGNED_AGENT)

    response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/campaigns",
        json=_payload(),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == ["permission_denied"]


def test_invalid_quiet_hours_returns_422(
    campaign_admin_client: CampaignAdminTestClient,
) -> None:
    payload = _payload()
    payload["quiet_hours_end"] = "09:00:00"

    response = campaign_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/campaigns",
        json=payload,
    )

    assert response.status_code == 422


def test_publish_and_pause_campaign_routes_return_200(
    campaign_admin_client: CampaignAdminTestClient,
) -> None:
    create_response = campaign_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/campaigns",
        json=_payload(),
    )
    campaign_id = create_response.json()["campaign"]["campaign_id"]
    version_id = create_response.json()["version"]["campaign_version_id"]

    publish_response = campaign_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/campaigns/{campaign_id}/versions/{version_id}/publish",
    )

    assert publish_response.status_code == 200
    publish_body = publish_response.json()
    assert publish_body["status"] == "published"
    assert publish_body["campaign"]["status"] == CampaignStatus.ACTIVE.value

    pause_response = campaign_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/campaigns/{campaign_id}/pause",
        json={"reason": "Pilot pause"},
    )

    assert pause_response.status_code == 200
    pause_body = pause_response.json()
    assert pause_body["status"] == "paused"
    assert pause_body["campaign"]["status"] == CampaignStatus.PAUSED.value

    resume_response = campaign_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/campaigns/{campaign_id}/resume",
        json={"reason": "Resume after review"},
    )

    assert resume_response.status_code == 200
    resume_body = resume_response.json()
    assert resume_body["status"] == "resumed"
    assert resume_body["campaign"]["status"] == CampaignStatus.ACTIVE.value


def test_upsert_nurture_settings_creates_default_workspace_policy(
    campaign_admin_client: CampaignAdminTestClient,
) -> None:
    response = campaign_admin_client.client.put(
        f"/api/v1/workspaces/{WORKSPACE_ID}/nurture-settings/draft",
        json=_nurture_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    assert body["nurture_settings"]["name"] == "Workspace Nurture Settings"
    assert body["settings"]["daily_start_cap"] == 50
    assert cast(_FakeSession, campaign_admin_client.session).commits == 1


def test_get_nurture_settings_prefers_latest_draft_over_active_version(
    campaign_admin_client: CampaignAdminTestClient,
) -> None:
    create_response = campaign_admin_client.client.put(
        f"/api/v1/workspaces/{WORKSPACE_ID}/nurture-settings/draft",
        json=_nurture_payload(),
    )
    nurture_settings_id = create_response.json()["nurture_settings"]["nurture_settings_id"]

    publish_response = campaign_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/nurture-settings/publish"
    )

    assert publish_response.status_code == 200

    updated_payload = _nurture_payload()
    updated_payload["daily_start_cap"] = 75
    updated_payload["prompt_version"] = "v2"
    update_response = campaign_admin_client.client.put(
        f"/api/v1/workspaces/{WORKSPACE_ID}/nurture-settings/draft",
        json=updated_payload,
    )

    assert update_response.status_code == 200
    assert update_response.json()["status"] == "updated"
    assert update_response.json()["nurture_settings"]["nurture_settings_id"] == nurture_settings_id

    detail_response = campaign_admin_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/nurture-settings"
    )

    assert detail_response.status_code == 200
    detail_body = detail_response.json()
    assert detail_body["settings"]["status"] == "draft"
    assert detail_body["settings"]["daily_start_cap"] == 75
    assert detail_body["settings"]["prompt_version"] == "v2"


def test_publish_pause_and_resume_nurture_settings_routes_return_200(
    campaign_admin_client: CampaignAdminTestClient,
) -> None:
    create_response = campaign_admin_client.client.put(
        f"/api/v1/workspaces/{WORKSPACE_ID}/nurture-settings/draft",
        json=_nurture_payload(),
    )

    assert create_response.status_code == 200

    publish_response = campaign_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/nurture-settings/publish"
    )

    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "published"
    assert publish_response.json()["nurture_settings"]["status"] == CampaignStatus.ACTIVE.value

    pause_response = campaign_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/nurture-settings/pause",
        json={"reason": "Pilot pause"},
    )

    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == "paused"
    assert pause_response.json()["nurture_settings"]["status"] == CampaignStatus.PAUSED.value

    resume_response = campaign_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/nurture-settings/resume",
        json={"reason": "Resume after review"},
    )

    assert resume_response.status_code == 200
    assert resume_response.json()["status"] == "resumed"
    assert resume_response.json()["nurture_settings"]["status"] == CampaignStatus.ACTIVE.value


def test_nurture_settings_routes_reject_multiple_workspace_policies(
    campaign_admin_client: CampaignAdminTestClient,
) -> None:
    first = _payload()
    second = _payload()
    second["name"] = "Seller Reactivation"

    first_response = campaign_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/campaigns",
        json=first,
    )
    second_response = campaign_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/campaigns",
        json=second,
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201

    detail_response = campaign_admin_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/nurture-settings"
    )
    update_response = campaign_admin_client.client.put(
        f"/api/v1/workspaces/{WORKSPACE_ID}/nurture-settings/draft",
        json=_nurture_payload(),
    )

    assert detail_response.status_code == 409
    assert detail_response.json()["detail"] == ["multiple_nurture_policies_configured"]
    assert update_response.status_code == 409
    assert update_response.json()["detail"] == ["multiple_nurture_policies_configured"]


def _client_for_role(role: WorkspaceMembershipRole) -> CampaignAdminTestClient:
    app = create_app()
    campaign_repository = FakeCampaignAdminRepository()
    audit_repository = FakeCampaignAdminAuditLogRepository()
    event_bus = FakeEventBus()
    session = _FakeSession()
    unused = cast(Any, _Unused())
    bundle = CampaignServiceBundle(
        session=session,
        campaign_admin_repository=campaign_repository,
        campaign_admin_audit_log_repository=audit_repository,
        campaign_execution_repository=unused,
        campaign_enrollment_repository=unused,
        workspace_operational_control_repository=unused,
        workspace_contact_policy_repository=unused,
        dormant_candidate_selector=unused,
        preflight_digest_repository=unused,
        lead_repository=unused,
        paused_search_history_repository=unused,
        artifact_repository=unused,
        crm_conversation_event_repository=unused,
        workspace_llm_config_repository=unused,
        lead_workflow_repository=unused,
        paused_search_track_repository=unused,
        temporal_signal_outbox_repository=unused,
        workflow_transition_repository=unused,
        temporal_workflow_starter=unused,
        crm_client=unused,
        crm_agent_repository=unused,
        workspace_agent_crm_mapping_repository=unused,
        llm_client=unused,
        default_openrouter_model="openai/gpt-4o-mini",
        notification_provider=unused,
        event_bus=event_bus,
    )

    read_bundle = CampaignReadBundle(campaign_admin_repository=campaign_repository)

    app.dependency_overrides[get_workspace_actor] = lambda: _actor(role)
    app.dependency_overrides[get_campaign_service_bundle] = lambda: bundle
    app.dependency_overrides[get_campaign_read_bundle] = lambda: read_bundle
    return CampaignAdminTestClient(
        client=TestClient(app),
        campaign_repository=campaign_repository,
        audit_repository=audit_repository,
        event_bus=event_bus,
        session=session,
    )


def _payload() -> dict[str, Any]:
    return {
        "name": "Dormant Buyers",
        "enabled_channels": ["email"],
        "daily_start_cap": 50,
        "dormant_threshold_days": 60,
        "quiet_hours_start": "10:00:00",
        "quiet_hours_end": "17:00:00",
        "timezone": "America/Chicago",
        "preflight_digest_enabled": True,
        "crm_enrollment_tag": "ai_nurture",
        "allow_assigned_agent_manual_enrollment": True,
        "prompt_version": "v1",
        "approved_model": "openai/gpt-4o-mini",
        "prompt_text": "  Draft dormant outreach with a calm tone.  ",
        "sms_prompt_text": "Use a concise dormant SMS tone.",
        "sms_template": "Hi {{lead_first_name}}, {{message_body}}",
        "email_prompt_text": "Use a concise dormant email tone.",
        "email_template": "Hello {{lead_first_name}},\n\n{{message_body}}",
        "email_subject_template": "{{message_subject}}",
        "enabled_extraction_fields": ["location", "max_price", "location"],
        "cadence_steps": [
            {
                "channel": "email",
                "delay_hours": 24,
                "message_goal": "Check whether the lead is still considering a move.",
                "template_key": "dormant-email-1",
                "max_attempts": 1,
                "template_profile": {
                    "tone": "warm",
                    "style": "friendly_follow_up",
                    "length": "short",
                    "call_to_action": "invite_reply",
                    "greeting": "lead_first_name",
                    "sign_off": "best_brokerage",
                    "listing_context": "when_available",
                    "personalization_fields": ["lead_first_name", "location"],
                    "custom_instructions": None,
                },
            }
        ],
    }


def _nurture_payload() -> dict[str, Any]:
    payload = _payload()
    payload.pop("name")
    return payload


def _actor(role: WorkspaceMembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=MEMBERSHIP_ID,
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _Unused:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"Unexpected dependency call: {name}")
