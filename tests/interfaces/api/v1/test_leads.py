from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import time_machine
from fastapi.testclient import TestClient

from app.application.ports.lead_activity import (
    LeadActivityItem,
    LeadActivityKind,
    LeadActivityTranscriptSegment,
)
from app.application.ports.repositories import (
    CRMAgentRepository,
    UserRepository,
    WorkspaceAgentCRMMappingRepository,
    WorkspaceAgentMappingConfigRepository,
    WorkspaceMembershipRepository,
)
from app.domain.campaigns.execution import (
    CampaignCadenceStep,
    CampaignExecutionConfig,
    CampaignVersionStatus,
)
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTrack,
    PausedSearchTrackFamily,
    PausedSearchTrackStatus,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.campaigns.rejected_draft_review import (
    RejectedDraftReview,
    RejectedDraftReviewStatus,
)
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SmsComplianceState,
    WorkspaceContactPolicy,
)
from app.domain.conversations import (
    Handoff,
    HandoffReasonCode,
    InboundMessage,
    InboundMessageClassificationStatus,
)
from app.domain.crm_agent_mapping import (
    CRMAgent,
    CRMAgentMappingResolutionSource,
    CRMAgentMappingStatus,
    WorkspaceAgentCRMMapping,
    WorkspaceAgentMappingConfig,
)
from app.domain.crm_sync import ExternalEvent
from app.domain.identity import (
    AuthenticatedActor,
    User,
    UserStatus,
    Workspace,
    WorkspaceMembership,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import (
    AssignmentResolutionStatus,
    CanonicalLeadRecord,
    CRMProvider,
    EffectiveOwnerSource,
    LeadClassificationAppliedStatus,
    LeadClassificationArtifact,
    LeadPausedSearchHistoryEntry,
    LeadPausedSearchProfile,
    LeadRoutingReview,
    LeadRoutingReviewResolution,
    LeadRoutingReviewStatus,
    LeadStateClassificationOutcome,
    PausedSearchAction,
    PausedSearchReasonCode,
    PausedSearchSource,
)
from app.domain.workflows import (
    LeadWorkflow,
    LeadWorkflowOverrideAction,
    LeadWorkflowOverrideAuditLog,
    WorkflowState,
    WorkflowTransition,
    WorkflowTransitionReasonCode,
)
from app.interfaces.api.dependencies.lead_draft_review import (
    LeadDraftReviewActionBundle,
    get_lead_draft_review_action_bundle,
)
from app.interfaces.api.dependencies.lead_paused_search import (
    LeadPausedSearchActionBundle,
    get_lead_paused_search_action_bundle,
)
from app.interfaces.api.dependencies.lead_read import LeadReadBundle, get_lead_read_bundle
from app.interfaces.api.dependencies.lead_resume import (
    LeadResumeActionBundle,
    LeadResumeReadBundle,
    get_lead_resume_action_bundle,
    get_lead_resume_read_bundle,
)
from app.interfaces.api.dependencies.lead_workflow_overrides import (
    LeadWorkflowOverrideActionBundle,
    get_lead_workflow_override_action_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.main import create_app
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCampaignExecutionRepository,
    FakeEmailProvider,
    FakeLeadRoutingReviewRepository,
    FakeSMSProvider,
    FakeWorkspaceContactPolicyRepository,
    FakeWorkspaceOperationalControlRepository,
    FakeWorkspaceRepository,
)
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeLeadRepository as FakeCadenceLeadRepository,
)
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeOutboundMessageRepository as FakeCadenceOutboundMessageRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeTemporalSignalOutboxRepository,
)
from tests.application.use_cases._lead_read_fakes import (
    FakeCrmConversationEventRepository,
    FakeHandoffRepository,
    FakeInboundMessageRepository,
    FakeLeadActivityRepository,
    FakeLeadClassificationArtifactRepository,
    FakeLeadPausedSearchHistoryRepository,
    FakeLeadRepository,
    FakeLeadWorkflowOverrideAuditLogRepository,
    FakeLeadWorkflowRepository,
    FakeOutboundMessageRepository,
    FakeRejectedDraftReviewRepository,
    FakeUserRepository,
    FakeWorkflowTransitionRepository,
)
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
)
from tests.application.use_cases.test_process_inbound_message_event import (
    FakeCRMClient,
    FakeOutboundMessageCRMCompletionRepository,
    FakeWorkspaceHandoffConfigRepository,
    _workspace_handoff_config_with_snapshot_fields,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000004")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000005")
CAMPAIGN_VERSION_ID = UUID("00000000-0000-0000-0000-000000000016")
REVIEW_ID = UUID("00000000-0000-0000-0000-000000000021")


@dataclass
class LeadsTestClient:
    client: TestClient
    outbox: FakeTemporalSignalOutboxRepository
    crm_client: FakeCRMClient


class LeadRouteCRMClient(FakeCRMClient):
    async def get_lead_snapshot(
        self,
        *,
        workspace_id: UUID,
        crm_lead_id: str,
        mapped_custom_field_keys: tuple[str, ...] = (),
    ) -> CanonicalLeadRecord | None:
        _ = mapped_custom_field_keys
        return CanonicalLeadRecord(
            workspace_id=workspace_id,
            lead_id=LEAD_ID,
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            crm_lead_id=crm_lead_id,
            facts_derived_at=NOW,
            source_payload_version="test:v1",
            assigned_agent_crm_id="agent-1",
            primary_email="lead@example.com",
            primary_phone="+15555550100",
            has_email=True,
            has_phone=True,
            has_sms_capable_phone=True,
            sms_permission_status=ContactPermissionStatus.CONFIRMED,
            email_permission_status=ContactPermissionStatus.CONFIRMED,
            do_not_contact=False,
        )


class FakeCRMAgentRepository:
    async def get_by_record_id(self, workspace_id: UUID, agent_record_id: UUID) -> CRMAgent | None:
        return next(
            (
                agent
                for agent in await self.list_for_workspace(workspace_id)
                if agent.agent_record_id == agent_record_id
            ),
            None,
        )

    async def get_by_external_id(
        self,
        workspace_id: UUID,
        crm_provider: CRMProvider,
        external_agent_id: str,
    ) -> CRMAgent | None:
        return next(
            (
                agent
                for agent in await self.list_for_workspace(workspace_id)
                if agent.crm_provider == crm_provider
                and agent.external_agent_id == external_agent_id
            ),
            None,
        )

    async def list_for_workspace(self, workspace_id: UUID) -> tuple[CRMAgent, ...]:
        return (
            CRMAgent(
                agent_record_id=UUID("00000000-0000-0000-0000-000000000031"),
                workspace_id=workspace_id,
                crm_provider=CRMProvider.FOLLOW_UP_BOSS,
                external_agent_id="agent-1",
                name="Jordan Agent",
                email="agent@example.com",
                email_normalized="agent@example.com",
                phone="+15555550100",
                is_active=True,
                last_seen_at=NOW,
                raw_payload={"id": "agent-1"},
                created_at=NOW,
                updated_at=NOW,
            ),
        )

    async def save(self, agent: CRMAgent) -> CRMAgent:
        return agent


class FakeWorkspaceAgentCRMMappingRepository:
    async def get_by_id(
        self,
        workspace_id: UUID,
        mapping_id: UUID,
    ) -> WorkspaceAgentCRMMapping | None:
        return next(
            (
                mapping
                for mapping in await self.list_for_workspace(workspace_id)
                if mapping.mapping_id == mapping_id
            ),
            None,
        )

    async def list_for_workspace(
        self,
        workspace_id: UUID,
    ) -> tuple[WorkspaceAgentCRMMapping, ...]:
        return (
            WorkspaceAgentCRMMapping(
                mapping_id=UUID("00000000-0000-0000-0000-000000000032"),
                workspace_id=workspace_id,
                crm_agent_record_id=UUID("00000000-0000-0000-0000-000000000031"),
                app_user_id=USER_ID,
                mapping_status=CRMAgentMappingStatus.VERIFIED,
                resolution_source=CRMAgentMappingResolutionSource.ADMIN_MANUAL,
                resolved_by_user_id=None,
                resolved_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            ),
        )


class FakeWorkspaceAgentMappingConfigRepository:
    async def get_by_workspace_id(
        self, workspace_id: UUID
    ) -> WorkspaceAgentMappingConfig | None:
        return WorkspaceAgentMappingConfig(
            workspace_id=workspace_id,
            unmapped_assignment_fallback_user_id=USER_ID,
            created_at=NOW,
            updated_at=NOW,
        )

    async def save(self, config: WorkspaceAgentMappingConfig) -> WorkspaceAgentMappingConfig:
        return config


class FakeWorkspaceMembershipRepository:
    async def list_by_workspace_id(self, workspace_id: UUID) -> tuple[WorkspaceMembership, ...]:
        return (
            WorkspaceMembership(
                membership_id=UUID("00000000-0000-0000-0000-000000000033"),
                workspace_id=workspace_id,
                user_id=USER_ID,
                role=WorkspaceMembershipRole.ASSIGNED_AGENT,
                status=WorkspaceMembershipStatus.ACTIVE,
                created_at=NOW,
                updated_at=NOW,
            ),
        )


def test_lead_routes_return_list_and_detail() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.BROKERAGE_ADMIN,
        routing_reviews=(
            _resolved_routing_review(),
            _superseded_routing_review(),
        ),
    )

    list_response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/leads")
    detail_response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}")

    assert list_response.status_code == 200
    list_payload = list_response.json()["leads"][0]
    assert list_payload["lead"]["display_name"] == "Jordan Seller"
    assert list_payload["ownership"]["crm_assigned_agent"] == {
        "external_agent_id": "agent-1",
        "name": "Jordan Agent",
        "email": "agent@example.com",
    }
    assert list_payload["ownership"]["mapped_app_user"]["user_id"] == str(USER_ID)
    assert list_payload["has_activity"] is True
    assert list_payload["activity_count"] == 4
    assert list_payload["inbound_message_count"] == 1
    assert list_payload["latest_activity_preview"] is not None
    assert detail_response.status_code == 200
    assert detail_response.json()["ownership"]["crm_assigned_agent"] == {
        "external_agent_id": "agent-1",
        "name": "Jordan Agent",
        "email": "agent@example.com",
    }
    assert detail_response.json()["ownership"]["mapped_app_user"]["user_id"] == str(USER_ID)
    assert detail_response.json()["ownership"]["mapped_app_user"]["email"] == "agent@example.com"
    assert (
        detail_response.json()["lead"]["paused_search"]["pause_reason_code"]
        == "waiting_for_rates"
    )
    assert detail_response.json()["qualification_plan"]["classification_artifact"]["outcome"] == (
        "paused_search"
    )
    assert detail_response.json()["qualification_plan"]["classification_artifact"][
        "pause_reason_code"
    ] == "waiting_for_rates"
    trace = detail_response.json()["qualification_plan"]["classification_artifact"]["llm_trace"]
    assert trace["prompt_text"] == "Prompt text for paused-search classification."
    assert trace["input_context"]["conversation_summary"] == "Lead asked to wait for lower rates."
    assert trace["parsed_response"]["outcome"] == "paused_search"
    assert detail_response.json()["qualification_plan"]["paused_search_plan"][
        "display_name"
    ] == "Rates Watch"
    assert detail_response.json()["qualification_plan"]["paused_search_plan"][
        "current_phase"
    ] == "reactivation"
    paused_search_edge = next(
        edge
        for edge in detail_response.json()["decision_tree"]["edges"]
        if edge["edge_id"] == "route_decision->paused_search"
    )
    assert paused_search_edge["description"] is not None
    assert any(
        "Classifier summary: Pause until rates settle, then re-engage." == line
        for line in paused_search_edge["detail_lines"]
    )
    assert any(
        "Possible paused-search phases on this track:" in line
        for line in paused_search_edge["detail_lines"]
    )
    assert detail_response.json()["paused_search_history"][0]["action"] == "set"
    assert len(detail_response.json()["workflow_transitions"]) == 1
    assert (
        detail_response.json()["workflow_override_audits"][0]["action"]
        == "paused_search_timing_changed"
    )
    assert detail_response.json()["workflow_transitions"][0]["metadata"]["draft_reasons"] == [
        "safety_flags_present"
    ]
    assert [review["status"] for review in detail_response.json()["routing_reviews"]] == [
        "resolved",
        "superseded",
    ]
    assert detail_response.json()["routing_reviews"][0]["resolution"] == "paused_search"
    assert len(detail_response.json()["rejected_draft_reviews"]) == 1
    assert len(detail_response.json()["activity_log"]) == 4
    crm_activity = next(
        item
        for item in detail_response.json()["activity_log"]
        if item["kind"] == "crm_conversation_event"
    )
    assert crm_activity["content"] == (
        "Agent Ada: We can reconnect once you are back in town.\n"
        "Jordan Buyer: Sounds good, call me in two weeks."
    )
    assert crm_activity["details"] == {
        "duration_seconds": 40,
        "call_outcome": "Connected",
        "transcript_segment_count": 2,
    }
    assert crm_activity["transcript_segments"][0]["speaker_name"] == "Agent Ada"
    assert len(detail_response.json()["inbound_messages"]) == 1
    assert detail_response.json()["inbound_messages"][0]["from_address_redacted"] is None
    assert detail_response.json()["inbound_messages"][0]["to_address_redacted"] is None


def test_review_queue_route_returns_pending_items_for_brokerage_admin() -> None:
    client = _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)

    response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/review-queue")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert len(payload["items"]) == 1
    assert payload["items"][0]["review"]["status"] == "pending"
    assert payload["items"][0]["lead"]["lead_id"] == str(LEAD_ID)
    assert payload["items"][0]["artifact"]["outcome"] == "review_hold"


def test_admin_can_approve_rejected_draft_review() -> None:
    client = _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)

    with time_machine.travel("2030-01-01T18:00:00Z"):
        response = client.client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/rejected-draft-reviews/{REVIEW_ID}/approve-send",
            json={"reason": "Admin reviewed and approved this draft for delivery."},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "sent"
    assert response.json()["signal_queued"] is True
    assert len(client.outbox.entries) == 1
    assert len(client.crm_client.notes) == 1
    assert client.crm_client.note_subjects == ["AI OUTBOUND · EMAIL"]
    assert "AI OUTBOUND · EMAIL" in client.crm_client.notes[0]
    assert client.crm_client.custom_field_updates == [
        {
            "ai_summary": "Used safe canonical context.",
            "ai_status": "waiting_for_response",
            "ai_latest_outbound": "Would you like to continue the conversation this week?",
            "ai_last_activity_at": "2030-01-01T18:00:00+00:00",
        }
    ]


def test_lead_routes_return_contactability_and_sendability() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.BROKERAGE_ADMIN,
        sms_permission_status=ContactPermissionStatus.UNKNOWN,
        email_permission_status=ContactPermissionStatus.UNKNOWN,
    )

    response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}")

    assert response.status_code == 200
    contactability = response.json()["lead"]["contactability"]
    sendability = response.json()["lead"]["sendability"]
    assert contactability["sms"] == {"channel": "sms", "contactable": True}
    assert contactability["email"] == {
        "channel": "email",
        "contactable": True,
    }
    assert contactability["contactable_channels"] == ["sms", "email"]
    assert sendability["sms"] == {"channel": "sms", "sendable": True, "reasons": []}
    assert sendability["email"] == {
        "channel": "email",
        "sendable": True,
        "reasons": [],
    }
    assert sendability["sendable_channels"] == ["sms", "email"]
    assert sendability["blocked_reasons"] == []


def test_resume_routes_return_eligibility_and_request_resume() -> None:
    client = _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)

    eligibility_response = client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/resume-eligibility"
    )
    resume_response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/resume",
        json={"reason": "Agent requested AI resume after manual follow-up."},
    )

    assert eligibility_response.status_code == 200
    assert eligibility_response.json()["can_resume"] is True
    assert resume_response.status_code == 200
    assert resume_response.json()["status"] == "requested"
    assert resume_response.json()["signal_queued"] is True
    assert len(client.outbox.entries) == 1


def test_pause_route_requests_manual_pause() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.BROKERAGE_ADMIN,
        workflow_state=WorkflowState.ACTIVE_NURTURE,
    )

    response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/pause",
        json={"reason": "Agent asked to pause automated follow-up."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "requested"
    assert response.json()["workflow_state"] == "paused"
    assert response.json()["signal_queued"] is True
    assert len(client.outbox.entries) == 1


def test_update_paused_search_route_updates_profile_and_history() -> None:
    client = _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)

    response = client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/paused-search",
        json={
            "active": True,
            "reason_code": "waiting_for_inventory",
            "reason_note": "Holding for new listings this fall.",
            "reengagement_not_before": "2030-03-01T12:00:00Z",
            "reengagement_window_label": "fall inventory",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "updated"
    assert payload["paused_search"]["pause_reason_code"] == "waiting_for_inventory"
    assert payload["history_entry"]["action"] == "updated"


def test_assigned_agent_cannot_update_unowned_paused_search_profile() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.ASSIGNED_AGENT,
        assigned_agent_user_id=UUID("00000000-0000-0000-0000-000000000099"),
    )

    response = client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/paused-search",
        json={"active": True, "reason_code": "timing_not_right"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == ["permission_denied"]


def test_clear_paused_search_request_rejects_extra_fields() -> None:
    client = _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)

    response = client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/paused-search",
        json={"active": False, "reason_code": "timing_not_right"},
    )

    assert response.status_code == 422


def test_assigned_agent_can_resume_own_lead() -> None:
    client = _client_for_role(WorkspaceMembershipRole.ASSIGNED_AGENT)

    response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/resume",
        json={"reason": "Resuming my assigned lead after handoff."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "requested"


def test_assigned_agent_cannot_resume_handoff_owned_lead() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.ASSIGNED_AGENT,
        workflow_state=WorkflowState.HUMAN_HANDOFF,
    )

    eligibility_response = client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/resume-eligibility"
    )
    resume_response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/resume",
        json={"reason": "Trying to resume a handed off lead."},
    )

    assert eligibility_response.status_code == 200
    assert eligibility_response.json()["can_resume"] is False
    assert eligibility_response.json()["reasons"] == ["handoff_requires_manager"]
    assert resume_response.status_code == 200
    assert resume_response.json()["status"] == "not_resumable"


def test_assigned_agent_can_read_own_lead_routes() -> None:
    client = _client_for_role(WorkspaceMembershipRole.ASSIGNED_AGENT)

    list_response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/leads")
    detail_response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}")

    assert list_response.status_code == 200
    assert list_response.json()["leads"][0]["lead"]["display_name"] == "Jordan Seller"
    assert detail_response.status_code == 200
    assert detail_response.json()["lead"]["display_name"] == "Jordan Seller"


def test_assigned_agent_lead_detail_rejects_unowned_lead() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.ASSIGNED_AGENT,
        assigned_agent_user_id=UUID("00000000-0000-0000-0000-000000000099"),
    )

    response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}")

    assert response.status_code == 403
    assert response.json()["detail"] == ["permission_denied"]


def _client_for_role(
    role: WorkspaceMembershipRole,
    *,
    assigned_agent_user_id: UUID = USER_ID,
    sms_permission_status: ContactPermissionStatus = ContactPermissionStatus.CONFIRMED,
    email_permission_status: ContactPermissionStatus = ContactPermissionStatus.CONFIRMED,
    workflow_state: WorkflowState = WorkflowState.PAUSED,
    workflow_pause_reason: str | None = None,
    routing_reviews: tuple[LeadRoutingReview, ...] | None = None,
) -> LeadsTestClient:
    app = create_app()
    lead = CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        assigned_agent_crm_id="agent-1",
        assigned_agent_user_id=assigned_agent_user_id,
        effective_owner_user_id=assigned_agent_user_id,
        effective_owner_source=EffectiveOwnerSource.CRM_MAPPING,
        assignment_resolution_status=AssignmentResolutionStatus.RESOLVED,
        primary_email="lead@example.com",
        primary_phone="+15555550100",
        has_email=True,
        has_phone=True,
        has_sms_capable_phone=True,
        has_accountable_owner=True,
        sms_permission_status=sms_permission_status,
        email_permission_status=email_permission_status,
        do_not_contact=False,
        paused_search_active=True,
        pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
        pause_reason_note="Asked to revisit once rates settle.",
        reengagement_not_before=NOW,
        reengagement_window_label="check back in 90 days",
        paused_search_source=PausedSearchSource.OPERATOR,
        paused_search_recorded_at=NOW,
        paused_search_recorded_by_user_id=USER_ID,
        paused_search_last_confirmed_at=NOW,
        mapped_custom_fields={
            "assigned_agent_user_id": str(assigned_agent_user_id),
            "display_name": "Jordan Seller",
        },
    )
    workflow = LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="wf-1",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=UUID("00000000-0000-0000-0000-000000000006"),
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=workflow_state,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
        next_action_at=NOW,
        pause_reason=workflow_pause_reason,
        paused_search_track_version_id=UUID("00000000-0000-0000-0000-000000000052"),
        paused_search_track_step_id=UUID("00000000-0000-0000-0000-000000000053"),
    )
    policy_repository = FakeWorkspaceContactPolicyRepository(
        WorkspaceContactPolicy(
            workspace_id=WORKSPACE_ID,
            sms_compliance_state=SmsComplianceState.APPROVED,
        )
    )
    outbox = FakeTemporalSignalOutboxRepository()
    crm_client = LeadRouteCRMClient()
    lead_repository = FakeLeadRepository((lead,))
    paused_search_history_repository = FakeLeadPausedSearchHistoryRepository(
        (
            LeadPausedSearchHistoryEntry(
                history_id=UUID("00000000-0000-0000-0000-000000000041"),
                workspace_id=WORKSPACE_ID,
                lead_id=LEAD_ID,
                action=PausedSearchAction.SET,
                previous_profile=None,
                current_profile=LeadPausedSearchProfile(
                    paused_search_active=True,
                    pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
                    pause_reason_note="Asked to revisit once rates settle.",
                    reengagement_not_before=NOW,
                    reengagement_window_label="check back in 90 days",
                    paused_search_source=PausedSearchSource.OPERATOR,
                    paused_search_recorded_at=NOW,
                    paused_search_recorded_by_user_id=USER_ID,
                    paused_search_last_confirmed_at=NOW,
                ),
                actor_user_id=USER_ID,
                created_at=NOW,
            ),
        )
    )
    bundle = LeadReadBundle(
        lead_repository=lead_repository,
        paused_search_history_repository=paused_search_history_repository,
        classification_artifact_repository=FakeLeadClassificationArtifactRepository(
            (_classification_artifact(), _review_queue_artifact())
        ),
        workflow_repository=FakeLeadWorkflowRepository((workflow,)),
        workflow_override_audit_repository=FakeLeadWorkflowOverrideAuditLogRepository(
            (_workflow_override_audit_log(),)
        ),
        workflow_transition_repository=FakeWorkflowTransitionRepository(
            (
                WorkflowTransition(
                    transition_id=UUID("00000000-0000-0000-0000-000000000007"),
                    workspace_id=WORKSPACE_ID,
                    workflow_id=WORKFLOW_ID,
                    lead_id=LEAD_ID,
                    campaign_id=CAMPAIGN_ID,
                    from_state=WorkflowState.ACTIVE_NURTURE,
                    to_state=WorkflowState.PAUSED,
                    reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED,
                    created_at=NOW,
                    metadata={
                        "block_stage": "planning",
                        "reason_codes": ["draft_rejected"],
                        "draft_reasons": ["safety_flags_present"],
                        "draft_safety_flags": ["tour_request_detected"],
                        "draft_confidence": 0.91,
                        "explanation": "Planning blocked: draft rejected.",
                    },
                ),
            )
        ),
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(
            tracks=(_paused_search_track(),),
            versions=(_paused_search_track_version(),),
            steps=(_paused_search_track_step(),),
        ),
        activity_repository=FakeLeadActivityRepository(_activity_items()),
        rejected_draft_review_repository=FakeRejectedDraftReviewRepository(
            (_rejected_draft_review(),)
        ),
        inbound_message_repository=FakeInboundMessageRepository(
            (
                InboundMessage(
                    inbound_message_id=UUID("00000000-0000-0000-0000-000000000008"),
                    workspace_id=WORKSPACE_ID,
                    conversation_id=UUID("00000000-0000-0000-0000-000000000009"),
                    lead_id=LEAD_ID,
                    channel=ContactChannel.SMS,
                    provider="twilio",
                    provider_message_id="pm-1",
                    body="Still interested",
                    received_at=NOW,
                    classification_status=InboundMessageClassificationStatus.CLASSIFIED,
                    created_at=NOW,
                ),
            )
        ),
        outbound_message_repository=FakeOutboundMessageRepository(
            (
                OutboundMessage(
                    message_id=UUID("00000000-0000-0000-0000-000000000010"),
                    workspace_id=WORKSPACE_ID,
                    lead_id=LEAD_ID,
                    campaign_id=CAMPAIGN_ID,
                    cadence_step_id="step-1",
                    channel=ContactChannel.SMS,
                    status=OutboundMessageStatus.SENT,
                    idempotency_key="msg-1",
                    body="Checking in",
                    created_at=NOW,
                    updated_at=NOW,
                    provider_send_status=ProviderSendStatus.ACCEPTED,
                ),
            )
        ),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(()),
        handoff_repository=FakeHandoffRepository(
            (
                Handoff(
                    handoff_id=UUID("00000000-0000-0000-0000-000000000011"),
                    workspace_id=WORKSPACE_ID,
                    lead_id=LEAD_ID,
                    reason_code=HandoffReasonCode.HUMAN_REQUESTED,
                    summary="Lead asked for a callback.",
                    created_at=NOW,
                ),
            )
        ),
        user_repository=FakeUserRepository(
            {
                USER_ID: User(
                    user_id=USER_ID,
                    email="agent@example.com",
                    email_normalized="agent@example.com",
                    full_name="Jordan Agent",
                    status=UserStatus.ACTIVE,
                    email_verified_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            }
        ),
        crm_agent_repository=FakeCRMAgentRepository(),
        routing_review_repository=_routing_review_repository(routing_reviews),
        workspace_contact_policy_repository=policy_repository,
    )
    resume_read_bundle = LeadResumeReadBundle(
        lead_repository=bundle.lead_repository,
        workflow_repository=bundle.workflow_repository,
        workspace_contact_policy_repository=policy_repository,
    )
    resume_action_bundle = LeadResumeActionBundle(
        session=_FakeSession(),
        lead_repository=bundle.lead_repository,
        workflow_repository=bundle.workflow_repository,
        lead_workflow_repository=FakeLeadWorkflowRepository((workflow,)),
        workspace_contact_policy_repository=policy_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(()),
        temporal_signal_outbox_repository=outbox,
        external_event_repository=_FakeExternalEventRepository(),
    )
    paused_search_action_bundle = LeadPausedSearchActionBundle(
        session=_FakeSession(),
        lead_repository=lead_repository,
        paused_search_history_repository=paused_search_history_repository,
        lead_workflow_repository=FakeLeadWorkflowRepository((workflow,)),
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        temporal_signal_outbox_repository=outbox,
    )
    workflow_override_action_bundle = LeadWorkflowOverrideActionBundle(
        session=_FakeSession(),
        lead_repository=lead_repository,
        paused_search_history_repository=paused_search_history_repository,
        lead_workflow_repository=FakeLeadWorkflowRepository((workflow,)),
        lead_workflow_override_audit_repository=FakeLeadWorkflowOverrideAuditLogRepository(()),
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        temporal_signal_outbox_repository=outbox,
        workspace_repository=FakeWorkspaceRepository(_workspace()),
    )
    draft_review_action_bundle = LeadDraftReviewActionBundle(
        session=_FakeSession(),
        lead_repository=FakeCadenceLeadRepository(lead),
        review_repository=FakeRejectedDraftReviewRepository((_rejected_draft_review(),)),
        workflow_repository=FakeLeadWorkflowRepository((workflow,)),
        workflow_transition_repository=FakeWorkflowTransitionRepository(()),
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=policy_repository,
        workspace_operational_control_repository=FakeWorkspaceOperationalControlRepository(),
        message_repository=FakeCadenceOutboundMessageRepository(),
        external_event_repository=_FakeExternalEventRepository(),
        temporal_signal_outbox_repository=outbox,
        crm_conversation_event_repository=FakeCrmConversationEventRepository(()),
        crm_client=crm_client,
        crm_agent_repository=cast(CRMAgentRepository, FakeCRMAgentRepository()),
        workspace_agent_crm_mapping_repository=cast(
            WorkspaceAgentCRMMappingRepository,
            FakeWorkspaceAgentCRMMappingRepository(),
        ),
        workspace_agent_mapping_config_repository=cast(
            WorkspaceAgentMappingConfigRepository,
            FakeWorkspaceAgentMappingConfigRepository(),
        ),
        workspace_membership_repository=cast(
            WorkspaceMembershipRepository,
            FakeWorkspaceMembershipRepository(),
        ),
        user_repository=cast(UserRepository, bundle.user_repository),
        outbound_message_crm_completion_repository=FakeOutboundMessageCRMCompletionRepository(),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            _workspace_handoff_config_with_snapshot_fields()
        ),
        sms_provider=FakeSMSProvider("msg-1"),
        email_provider=FakeEmailProvider("email-1"),
    )
    app.dependency_overrides[get_workspace_actor] = lambda: _actor(role)
    app.dependency_overrides[get_lead_read_bundle] = lambda: bundle
    app.dependency_overrides[get_lead_resume_read_bundle] = lambda: resume_read_bundle
    app.dependency_overrides[get_lead_resume_action_bundle] = lambda: resume_action_bundle
    app.dependency_overrides[get_lead_paused_search_action_bundle] = (
        lambda: paused_search_action_bundle
    )
    app.dependency_overrides[get_lead_workflow_override_action_bundle] = (
        lambda: workflow_override_action_bundle
    )
    app.dependency_overrides[get_lead_draft_review_action_bundle] = lambda: (
        draft_review_action_bundle
    )
    return LeadsTestClient(client=TestClient(app), outbox=outbox, crm_client=crm_client)


def _classification_artifact() -> LeadClassificationArtifact:
    return LeadClassificationArtifact(
        artifact_id=UUID("00000000-0000-0000-0000-000000000051"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        source="ai_conversation_classification",
        outcome=LeadStateClassificationOutcome.PAUSED_SEARCH,
        pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
        reengagement_not_before=NOW,
        reengagement_window_label="check back in 90 days",
        confidence=0.94,
        evidence=("Lead asked to wait for lower rates.",),
        summary="Pause until rates settle, then re-engage.",
        model="openai/gpt-4o-mini",
        prompt_version="lead_state_classification:v1",
        latency_ms=701,
        usage_tokens=512,
        applied_status=LeadClassificationAppliedStatus.APPLIED,
        applied_at=NOW,
        created_at=NOW,
        prompt_text="Prompt text for paused-search classification.",
        input_context={
            "conversation_summary": "Lead asked to wait for lower rates.",
            "recent_messages": [
                {
                    "content": "Let's reconnect when rates come down.",
                    "timestamp": NOW.isoformat(),
                    "direction": "inbound",
                }
            ],
        },
        raw_llm_response_text=(
            '{"outcome":"paused_search","pause_reason_code":"waiting_for_rates"}'
        ),
        parsed_llm_response={
            "outcome": "paused_search",
            "pause_reason_code": "waiting_for_rates",
            "confidence": 0.94,
            "summary": "Pause until rates settle, then re-engage.",
        },
    )


def _review_queue_artifact() -> LeadClassificationArtifact:
    return LeadClassificationArtifact(
        artifact_id=UUID("00000000-0000-0000-0000-000000000061"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        source="ai_conversation_classification",
        outcome=LeadStateClassificationOutcome.REVIEW_HOLD,
        pause_reason_code=None,
        reengagement_not_before=None,
        reengagement_window_label=None,
        confidence=0.55,
        evidence=("Low confidence",),
        summary="Needs manager review.",
        model="openai/gpt-4o-mini",
        prompt_version="lead_state_classification:v1",
        latency_ms=220,
        usage_tokens=84,
        applied_status=LeadClassificationAppliedStatus.REVIEW,
        applied_at=None,
        created_at=NOW,
        prompt_text="Prompt text for review-hold classification.",
        input_context={
            "conversation_summary": "Lead intent was unclear and needs review.",
            "recent_messages": [
                {
                    "content": "Can you explain this situation more clearly?",
                    "timestamp": NOW.isoformat(),
                    "direction": "inbound",
                }
            ],
        },
        raw_llm_response_text='{"outcome":"review_hold","confidence":0.55}',
        parsed_llm_response={
            "outcome": "review_hold",
            "confidence": 0.55,
            "summary": "Needs manager review.",
        },
    )


def _routing_review_repository(
    reviews: tuple[LeadRoutingReview, ...] | None = None,
) -> FakeLeadRoutingReviewRepository:
    repository = FakeLeadRoutingReviewRepository()
    repository.saved.extend(reviews or (_pending_routing_review(),))
    return repository


def _pending_routing_review() -> LeadRoutingReview:
    return LeadRoutingReview(
        review_id=UUID("00000000-0000-0000-0000-000000000062"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        artifact_id=UUID("00000000-0000-0000-0000-000000000061"),
        status=LeadRoutingReviewStatus.PENDING,
        reason_codes=("classification_rejected",),
        created_at=NOW,
        updated_at=NOW,
    )


def _resolved_routing_review() -> LeadRoutingReview:
    return LeadRoutingReview(
        review_id=UUID("00000000-0000-0000-0000-000000000063"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        artifact_id=UUID("00000000-0000-0000-0000-000000000061"),
        status=LeadRoutingReviewStatus.RESOLVED,
        reason_codes=("classification_rejected",),
        resolution=LeadRoutingReviewResolution.PAUSED_SEARCH,
        reviewed_by_user_id=USER_ID,
        reviewed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _superseded_routing_review() -> LeadRoutingReview:
    return LeadRoutingReview(
        review_id=UUID("00000000-0000-0000-0000-000000000064"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        artifact_id=UUID("00000000-0000-0000-0000-000000000061"),
        status=LeadRoutingReviewStatus.SUPERSEDED,
        reason_codes=("stale_review",),
        reviewed_by_user_id=USER_ID,
        reviewed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _paused_search_track() -> PausedSearchTrack:
    return PausedSearchTrack(
        track_id=UUID("00000000-0000-0000-0000-000000000054"),
        workspace_id=WORKSPACE_ID,
        track_key="rates-watch",
        display_name="Rates Watch",
        status=PausedSearchTrackStatus.ACTIVE,
        active_version_id=UUID("00000000-0000-0000-0000-000000000052"),
        created_by_user_id=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _paused_search_track_version() -> PausedSearchTrackVersion:
    return PausedSearchTrackVersion(
        track_version_id=UUID("00000000-0000-0000-0000-000000000052"),
        workspace_id=WORKSPACE_ID,
        track_id=UUID("00000000-0000-0000-0000-000000000054"),
        version_number=2,
        status=CampaignVersionStatus.PUBLISHED,
        track_family=PausedSearchTrackFamily.REACTIVATION,
        enabled=True,
        allowed_channels=(ContactChannel.SMS, ContactChannel.EMAIL),
        default_for_reason_codes=(PausedSearchReasonCode.WAITING_FOR_RATES,),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE,
        maintenance_interval_days=30,
        reactivation_window_days=14,
        max_total_touches=5,
        requires_review_before_publish=False,
        created_by_user_id=USER_ID,
        created_at=NOW,
        published_at=NOW,
    )


def _paused_search_track_step() -> PausedSearchTrackStep:
    return PausedSearchTrackStep(
        step_id=UUID("00000000-0000-0000-0000-000000000053"),
        workspace_id=WORKSPACE_ID,
        track_version_id=UUID("00000000-0000-0000-0000-000000000052"),
        step_order=1,
        phase=PausedSearchTrackStepPhase.REACTIVATION,
        channel=ContactChannel.EMAIL,
        delay_hours=0,
        message_goal="Check whether rates improved enough to restart the search.",
        template_key="paused_search_rates_watch_reactivation",
        max_attempts=1,
        review_required=False,
        created_at=NOW,
    )


def _activity_items() -> tuple[LeadActivityItem, ...]:
    return (
        LeadActivityItem(
            activity_id=UUID("00000000-0000-0000-0000-000000000012"),
            lead_id=LEAD_ID,
            kind=LeadActivityKind.CRM_CONVERSATION_EVENT,
            occurred_at=NOW,
            title="CRM call logged",
            preview="We can reconnect once you are back in town.",
            content=(
                "Agent Ada: We can reconnect once you are back in town.\n"
                "Jordan Buyer: Sounds good, call me in two weeks."
            ),
            direction="inbound",
            status="Call",
            actor_name="Agent Ada",
            details={
                "duration_seconds": 40,
                "call_outcome": "Connected",
                "transcript_segment_count": 2,
            },
            transcript_segments=(
                LeadActivityTranscriptSegment(
                    text="We can reconnect once you are back in town.",
                    speaker_name="Agent Ada",
                    speaker_role="agent",
                    started_at=NOW,
                ),
                LeadActivityTranscriptSegment(
                    text="Sounds good, call me in two weeks.",
                    speaker_name="Jordan Buyer",
                    speaker_role="lead",
                    started_at=NOW,
                ),
            ),
        ),
        LeadActivityItem(
            activity_id=UUID("00000000-0000-0000-0000-000000000008"),
            lead_id=LEAD_ID,
            kind=LeadActivityKind.INBOUND_MESSAGE,
            occurred_at=NOW,
            title="Inbound reply received",
            preview="Still interested",
            channel="sms",
            direction="inbound",
            status="classified",
            actor_name="twilio",
        ),
        LeadActivityItem(
            activity_id=UUID("00000000-0000-0000-0000-000000000010"),
            lead_id=LEAD_ID,
            kind=LeadActivityKind.OUTBOUND_MESSAGE,
            occurred_at=NOW,
            title="Outbound outreach logged",
            preview="Checking in",
            channel="sms",
            direction="outbound",
            status="sent",
        ),
        LeadActivityItem(
            activity_id=UUID("00000000-0000-0000-0000-000000000011"),
            lead_id=LEAD_ID,
            kind=LeadActivityKind.HANDOFF,
            occurred_at=NOW,
            title="Human handoff created",
            preview="Lead asked for a callback.",
            status="created",
        ),
    )


def _rejected_draft_review() -> RejectedDraftReview:
    return RejectedDraftReview(
        review_id=REVIEW_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        workflow_transition_id=UUID("00000000-0000-0000-0000-000000000007"),
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=UUID("00000000-0000-0000-0000-000000000017"),
        channel=ContactChannel.EMAIL,
        status=RejectedDraftReviewStatus.PENDING_REVIEW,
        reason_codes=("draft_rejected",),
        draft_reason_codes=("low_confidence",),
        review_blockers=(),
        draft_safety_flags=(),
        draft_personalization_notes=("Used safe canonical context.",),
        draft_body="Would you like to continue the conversation this week?",
        draft_subject="Quick check-in",
        explanation="Planning blocked: draft rejected.",
        draft_confidence=0.42,
        draft_model="openai/gpt-4o-mini",
        draft_prompt_version="outbound_message_draft:v1",
        can_approve_send=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _workspace() -> Workspace:
    return Workspace(
        workspace_id=WORKSPACE_ID,
        name="Miller Schackman",
        status=WorkspaceStatus.ACTIVE,
        default_timezone="America/Chicago",
        created_at=NOW,
        updated_at=NOW,
    )


def _workflow_override_audit_log() -> LeadWorkflowOverrideAuditLog:
    return LeadWorkflowOverrideAuditLog(
        audit_log_id=UUID("00000000-0000-0000-0000-000000000040"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        actor_user_id=USER_ID,
        action=LeadWorkflowOverrideAction.TIMING_CHANGED,
        reason="Move the follow-up to later in the year.",
        details={"new_reengagement_window_label": "fall inventory"},
        created_at=NOW,
    )


def _config() -> CampaignExecutionConfig:
    return CampaignExecutionConfig(
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        workspace_id=WORKSPACE_ID,
        campaign_name="Dormant Buyers",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(ContactChannel.EMAIL,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=datetime(2030, 1, 1, 10, 0, tzinfo=UTC).time(),
        quiet_hours_end=datetime(2030, 1, 1, 17, 0, tzinfo=UTC).time(),
        timezone="America/Chicago",
        sms_compliance_required=True,
        preflight_digest_enabled=False,
        crm_enrollment_tag=None,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(
            CampaignCadenceStep(
                cadence_step_id=UUID("00000000-0000-0000-0000-000000000017"),
                workspace_id=WORKSPACE_ID,
                campaign_version_id=CAMPAIGN_VERSION_ID,
                step_order=1,
                channel=ContactChannel.EMAIL,
                delay_hours=24,
                message_goal="Re-engage dormant lead",
                template_key="dormant-step-1",
                max_attempts=1,
                created_at=NOW,
            ),
        ),
        created_at=NOW,
        published_at=NOW,
    )


class _FakeSession:
    async def commit(self) -> None:
        return None


class _FakeExternalEventRepository:
    def __init__(self) -> None:
        self.events: dict[UUID, ExternalEvent] = {}

    async def save(self, event: ExternalEvent) -> ExternalEvent:
        self.events[event.external_event_id] = event
        return event

    async def get_by_provider_event_id(
        self,
        workspace_id: UUID,
        provider: str,
        provider_event_id: str,
    ) -> ExternalEvent | None:
        for event in self.events.values():
            if (
                event.workspace_id == workspace_id
                and event.provider == provider
                and event.provider_event_id == provider_event_id
            ):
                return event
        return None


def _actor(role: WorkspaceMembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=USER_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=UUID("00000000-0000-0000-0000-000000000012"),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )
