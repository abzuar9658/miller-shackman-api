import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from app.application.ports.lead_activity import LeadActivityItem, LeadActivityKind
from app.application.services.lead_decision_tree import build_lead_decision_tree
from app.application.use_cases.lead_read import (
    LeadReadReasonCode,
    LeadReadStatus,
    get_lead_detail_view,
    list_lead_views,
)
from app.domain.campaigns.execution import CampaignVersionStatus
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
from app.domain.compliance.contactability import ContactChannel
from app.domain.conversations import (
    Handoff,
    HandoffReasonCode,
    InboundMessage,
    InboundMessageClassificationStatus,
)
from app.domain.crm_agent_mapping import CRMAgent
from app.domain.identity import (
    AuthenticatedActor,
    User,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
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
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeLeadRoutingReviewRepository,
)
from tests.application.use_cases._lead_read_fakes import (
    FakeCRMAgentRepository,
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

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000004")
MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000005")
INBOUND_ID = UUID("00000000-0000-0000-0000-000000000006")
HANDOFF_ID = UUID("00000000-0000-0000-0000-000000000007")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000008")


def test_list_lead_views_returns_owner_and_workflow() -> None:
    result = asyncio.run(
        list_lead_views(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_repository=FakeLeadRepository((_lead(),)),
            workflow_repository=FakeLeadWorkflowRepository((_workflow(),)),
            activity_repository=FakeLeadActivityRepository(_activity_items()),
            rejected_draft_review_repository=FakeRejectedDraftReviewRepository(
                (_rejected_draft_review(),)
            ),
            inbound_message_repository=FakeInboundMessageRepository((_inbound_message(),)),
            handoff_repository=FakeHandoffRepository((_handoff(),)),
            user_repository=FakeUserRepository({USER_ID: _user()}),
            crm_agent_repository=FakeCRMAgentRepository((_crm_agent(),)),
        )
    )

    assert result.status == LeadReadStatus.OK
    assert result.views[0].assigned_agent_name == "Jordan Agent"
    assert result.views[0].ownership.crm_assigned_agent is not None
    assert result.views[0].ownership.crm_assigned_agent.name == "Jordan CRM Agent"
    assert result.views[0].ownership.mapped_app_user is not None
    assert result.views[0].ownership.mapped_app_user.full_name == "Jordan Agent"
    assert result.views[0].latest_workflow is not None
    assert result.views[0].activity_summary is not None
    assert result.views[0].activity_summary.activity_count == 3


def test_get_lead_detail_view_returns_messages_and_transitions() -> None:
    result = asyncio.run(
        get_lead_detail_view(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            lead_repository=FakeLeadRepository((_lead(),)),
            paused_search_history_repository=FakeLeadPausedSearchHistoryRepository(
                (_paused_search_history_entry(),)
            ),
            classification_artifact_repository=FakeLeadClassificationArtifactRepository(
                (_classification_artifact(),)
            ),
            workflow_repository=FakeLeadWorkflowRepository((_workflow(),)),
            workflow_override_audit_repository=FakeLeadWorkflowOverrideAuditLogRepository(
                (_workflow_override_audit(),)
            ),
            workflow_transition_repository=FakeWorkflowTransitionRepository((_transition(),)),
            paused_search_track_repository=FakePausedSearchTrackAdminRepository(
                tracks=(
                    _paused_search_track(),
                    _inventory_paused_search_track(),
                    _personal_timing_paused_search_track(),
                ),
                versions=(
                    _paused_search_track_version(),
                    _inventory_paused_search_track_version(),
                    _personal_timing_paused_search_track_version(),
                ),
                steps=(
                    _paused_search_maintenance_step(),
                    _paused_search_track_step(),
                    _inventory_paused_search_step(),
                    _personal_timing_paused_search_step(),
                ),
            ),
            activity_repository=FakeLeadActivityRepository(_activity_items()),
            rejected_draft_review_repository=FakeRejectedDraftReviewRepository(
                (_rejected_draft_review(),)
            ),
            routing_review_repository=_routing_review_repository(
                (
                    _routing_review(),
                    _superseded_routing_review(),
                )
            ),
            inbound_message_repository=FakeInboundMessageRepository((_inbound_message(),)),
            outbound_message_repository=FakeOutboundMessageRepository((_outbound_message(),)),
            handoff_repository=FakeHandoffRepository((_handoff(),)),
            user_repository=FakeUserRepository({USER_ID: _user()}),
            crm_agent_repository=FakeCRMAgentRepository((_crm_agent(),)),
        )
    )

    assert result.status == LeadReadStatus.OK
    assert result.view is not None
    assert len(result.view.routing_reviews) == 2
    assert result.view.routing_reviews[0].status == LeadRoutingReviewStatus.RESOLVED
    assert result.view.routing_reviews[0].resolution == LeadRoutingReviewResolution.PAUSED_SEARCH
    assert result.view.routing_reviews[1].status == LeadRoutingReviewStatus.SUPERSEDED
    assert len(result.view.workflow_transitions) == 1
    assert len(result.view.rejected_draft_reviews) == 1
    assert len(result.view.inbound_messages) == 1
    assert len(result.view.outbound_messages) == 1
    assert len(result.view.handoffs) == 1
    assert len(result.view.paused_search_history) == 1
    assert len(result.view.workflow_override_audits) == 1
    assert result.view.workflow_override_audits[0].actor_name == "Jordan Agent"
    assert result.view.paused_search_history[0].actor_name == "Jordan Agent"
    assert result.view.qualification_plan is not None
    assert result.view.qualification_plan.classification_artifact is not None
    assert result.view.qualification_plan.classification_artifact.outcome == (
        LeadStateClassificationOutcome.PAUSED_SEARCH
    )
    assert result.view.qualification_plan.paused_search_plan is not None
    assert result.view.qualification_plan.paused_search_plan.track.display_name == "Rates Watch"
    assert result.view.qualification_plan.paused_search_plan.current_step is not None
    assert result.view.qualification_plan.paused_search_plan.current_step.message_goal == (
        "Check whether rates improved enough to restart the search."
    )
    assert result.view.decision_tree.title == "Decision flowchart"
    assert any(
        node.node_id == "paused_search" and node.status.value == "current"
        for node in result.view.decision_tree.nodes
    )
    assert any(
        node.node_id == "paused_search_state" and node.label == "Waiting For Response"
        for node in result.view.decision_tree.nodes
    )
    assert any(
        node.node_id == "paused_search_track_decision"
        and node.label == "Choose paused-search track"
        for node in result.view.decision_tree.nodes
    )
    assert any(
        node.label == "Waiting for Inventory" and node.status.value == "available"
        for node in result.view.decision_tree.nodes
    )
    assert any(
        node.label == "Personal Timing" and node.status.value == "available"
        for node in result.view.decision_tree.nodes
    )
    assert any(
        node.label == "Rates Watch" and node.status.value == "taken"
        for node in result.view.decision_tree.nodes
    )
    assert any(
        node.node_id == "paused_search_path_decision" and node.label == "Choose phase within track"
        for node in result.view.decision_tree.nodes
    )
    paused_search_edge = next(
        edge
        for edge in result.view.decision_tree.edges
        if edge.edge_id == "route_decision->paused_search"
    )
    assert "paused-search" in (paused_search_edge.description or "").lower()
    assert any(
        "Classifier summary: Lead wants to pause until financing conditions improve." == line
        for line in paused_search_edge.detail_lines
    )
    assert any(
        line.startswith("LLM output: {") and '"outcome": "paused_search"' in line
        for line in paused_search_edge.detail_lines
    )
    assert any(
        "Possible paused-search phases on this track: Maintenance, Reactivation." == line
        for line in paused_search_edge.detail_lines
    )
    paused_search_path_edge = next(
        edge
        for edge in result.view.decision_tree.edges
        if edge.edge_id == "paused_search->paused_search_track_decision"
    )
    assert (
        "identifies which configured track is pinned"
        in (paused_search_path_edge.description or "").lower()
    )
    assert any(
        "Configured active tracks shown: 3." == line
        for line in paused_search_path_edge.detail_lines
    )
    current_state_edge = next(
        edge
        for edge in result.view.decision_tree.edges
        if edge.edge_id == "paused_search_reactivation_path->paused_search_state"
    )
    assert "waiting for the lead to respond" in (current_state_edge.description or "").lower()
    assert any("Next planned action:" in line for line in current_state_edge.detail_lines)
    assert result.view.lead.ownership.crm_assigned_agent is not None
    assert result.view.lead.ownership.crm_assigned_agent.name == "Jordan CRM Agent"
    assert result.view.lead.ownership.mapped_app_user is not None
    assert result.view.lead.ownership.mapped_app_user.email == "agent@example.com"


def test_decision_tree_highlights_blocked_classifier_route() -> None:
    artifact = replace(
        _classification_artifact(),
        outcome=LeadStateClassificationOutcome.BLOCKED,
        pause_reason_code=None,
        summary="Lead opted out of further communication.",
        parsed_llm_response={"outcome": "blocked", "confidence": 0.9},
        raw_llm_response_text='{"outcome":"blocked","confidence":0.9}',
    )

    decision_tree = build_lead_decision_tree(
        lead=replace(_lead(), paused_search_active=True),
        classification_artifact=artifact,
        paused_search_track=None,
        paused_search_track_version=None,
        paused_search_steps=(),
        paused_search_current_step=None,
        paused_search_track_options=(),
        latest_workflow=None,
        latest_handoff=None,
    )

    blocked_node = next(node for node in decision_tree.nodes if node.node_id == "blocked")
    blocked_edge = next(
        edge
        for edge in decision_tree.edges
        if edge.edge_id == "route_decision->blocked"
    )

    assert blocked_node.status.value == "current"
    assert blocked_edge.status.value == "current"


def test_assigned_agent_list_lead_views_returns_only_owned_leads() -> None:
    result = asyncio.run(
        list_lead_views(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
            workspace_id=WORKSPACE_ID,
            lead_repository=FakeLeadRepository((_lead(), _other_lead())),
            workflow_repository=FakeLeadWorkflowRepository((_workflow(),)),
            activity_repository=FakeLeadActivityRepository(_activity_items()),
            rejected_draft_review_repository=FakeRejectedDraftReviewRepository(()),
            inbound_message_repository=FakeInboundMessageRepository((_inbound_message(),)),
            handoff_repository=FakeHandoffRepository((_handoff(),)),
            user_repository=FakeUserRepository({USER_ID: _user()}),
            crm_agent_repository=FakeCRMAgentRepository((_crm_agent(),)),
        )
    )

    assert result.status == LeadReadStatus.OK
    assert len(result.views) == 1
    assert result.views[0].lead.lead_id == LEAD_ID


def test_assigned_agent_list_lead_views_uses_effective_owner_visibility() -> None:
    reassigned_lead = replace(
        _other_lead(),
        assigned_agent_user_id=UUID("00000000-0000-0000-0000-000000000098"),
        effective_owner_user_id=USER_ID,
    )

    result = asyncio.run(
        list_lead_views(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
            workspace_id=WORKSPACE_ID,
            lead_repository=FakeLeadRepository((reassigned_lead,)),
            workflow_repository=FakeLeadWorkflowRepository(()),
            activity_repository=FakeLeadActivityRepository(()),
            rejected_draft_review_repository=FakeRejectedDraftReviewRepository(()),
            inbound_message_repository=FakeInboundMessageRepository(()),
            handoff_repository=FakeHandoffRepository(()),
            user_repository=FakeUserRepository({USER_ID: _user()}),
            crm_agent_repository=FakeCRMAgentRepository(()),
        )
    )

    assert result.status == LeadReadStatus.OK
    assert len(result.views) == 1
    assert result.views[0].lead.lead_id == reassigned_lead.lead_id
    assert result.views[0].assigned_agent_name == "Jordan Agent"


def test_assigned_agent_get_lead_detail_view_rejects_unowned_lead() -> None:
    result = asyncio.run(
        get_lead_detail_view(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
            workspace_id=WORKSPACE_ID,
            lead_id=UUID("00000000-0000-0000-0000-000000000099"),
            lead_repository=FakeLeadRepository((_other_lead(),)),
            paused_search_history_repository=FakeLeadPausedSearchHistoryRepository(()),
            classification_artifact_repository=FakeLeadClassificationArtifactRepository(()),
            workflow_repository=FakeLeadWorkflowRepository(()),
            workflow_override_audit_repository=FakeLeadWorkflowOverrideAuditLogRepository(()),
            workflow_transition_repository=FakeWorkflowTransitionRepository(()),
            paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
            activity_repository=FakeLeadActivityRepository(()),
            rejected_draft_review_repository=FakeRejectedDraftReviewRepository(()),
            routing_review_repository=_routing_review_repository(),
            inbound_message_repository=FakeInboundMessageRepository(()),
            outbound_message_repository=FakeOutboundMessageRepository(()),
            handoff_repository=FakeHandoffRepository(()),
            user_repository=FakeUserRepository({USER_ID: _user()}),
            crm_agent_repository=FakeCRMAgentRepository(()),
        )
    )

    assert result.status == LeadReadStatus.REJECTED
    assert result.reasons == (LeadReadReasonCode.PERMISSION_DENIED,)


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        assigned_agent_crm_id="agent-1",
        assigned_agent_user_id=USER_ID,
        effective_owner_user_id=USER_ID,
        primary_email="lead@example.com",
        primary_phone="+15555550123",
        mapped_custom_fields={"display_name": "Jordan Seller"},
        paused_search_active=True,
        pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
        pause_reason_note="Asked to revisit once rates settle.",
        reengagement_not_before=NOW,
        reengagement_window_label="check back in 90 days",
        paused_search_source=PausedSearchSource.OPERATOR,
        paused_search_recorded_at=NOW,
        paused_search_recorded_by_user_id=USER_ID,
        paused_search_last_confirmed_at=NOW,
    )


def _other_lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=UUID("00000000-0000-0000-0000-000000000099"),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-2",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        assigned_agent_user_id=UUID("00000000-0000-0000-0000-000000000098"),
        effective_owner_user_id=UUID("00000000-0000-0000-0000-000000000098"),
        primary_email="other@example.com",
        primary_phone="+15555550124",
        mapped_custom_fields={"display_name": "Casey Unowned"},
    )


def _crm_agent() -> CRMAgent:
    return CRMAgent(
        agent_record_id=UUID("00000000-0000-0000-0000-000000000012"),
        workspace_id=WORKSPACE_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        external_agent_id="agent-1",
        name="Jordan CRM Agent",
        email="crm.agent@example.com",
        email_normalized="crm.agent@example.com",
        phone="+15555550155",
        is_active=True,
        last_seen_at=NOW,
        raw_payload={"id": "agent-1"},
        created_at=NOW,
        updated_at=NOW,
    )


def _workflow() -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="wf-1",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=UUID("00000000-0000-0000-0000-000000000009"),
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=WorkflowState.WAITING_FOR_RESPONSE,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
        next_action_at=NOW,
        paused_search_track_version_id=UUID("00000000-0000-0000-0000-000000000015"),
        paused_search_track_step_id=UUID("00000000-0000-0000-0000-000000000016"),
    )


def _classification_artifact() -> LeadClassificationArtifact:
    return LeadClassificationArtifact(
        artifact_id=UUID("00000000-0000-0000-0000-000000000017"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        source="ai_conversation_classification",
        outcome=LeadStateClassificationOutcome.PAUSED_SEARCH,
        pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
        reengagement_not_before=NOW,
        reengagement_window_label="check back in 90 days",
        confidence=0.93,
        evidence=("Lead said they want to wait for rates to settle.",),
        summary="Lead wants to pause until financing conditions improve.",
        model="openai/gpt-4o-mini",
        prompt_version="lead_state_classification:v1",
        latency_ms=812,
        usage_tokens=624,
        applied_status=LeadClassificationAppliedStatus.APPLIED,
        applied_at=NOW,
        created_at=NOW,
        prompt_text="Prompt text for paused-search classification.",
        input_context={
            "conversation_summary": "Lead wants to wait for better financing conditions.",
            "recent_messages": [
                {
                    "content": "Please follow up when mortgage rates improve.",
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
            "confidence": 0.93,
            "summary": "Lead wants to pause until financing conditions improve.",
        },
    )


def _paused_search_track() -> PausedSearchTrack:
    return PausedSearchTrack(
        track_id=UUID("00000000-0000-0000-0000-000000000018"),
        workspace_id=WORKSPACE_ID,
        track_key="rates-watch",
        display_name="Rates Watch",
        status=PausedSearchTrackStatus.ACTIVE,
        active_version_id=UUID("00000000-0000-0000-0000-000000000015"),
        created_by_user_id=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _paused_search_track_version() -> PausedSearchTrackVersion:
    return PausedSearchTrackVersion(
        track_version_id=UUID("00000000-0000-0000-0000-000000000015"),
        workspace_id=WORKSPACE_ID,
        track_id=UUID("00000000-0000-0000-0000-000000000018"),
        version_number=3,
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


def _inventory_paused_search_track() -> PausedSearchTrack:
    return replace(
        _paused_search_track(),
        track_id=UUID("00000000-0000-0000-0000-000000000020"),
        track_key="waiting-for-inventory",
        display_name="Waiting for Inventory",
        active_version_id=UUID("00000000-0000-0000-0000-000000000021"),
    )


def _inventory_paused_search_track_version() -> PausedSearchTrackVersion:
    return replace(
        _paused_search_track_version(),
        track_version_id=UUID("00000000-0000-0000-0000-000000000021"),
        track_id=UUID("00000000-0000-0000-0000-000000000020"),
        track_family=PausedSearchTrackFamily.MAINTENANCE,
        default_for_reason_codes=(PausedSearchReasonCode.WAITING_FOR_INVENTORY,),
    )


def _inventory_paused_search_step() -> PausedSearchTrackStep:
    return replace(
        _paused_search_maintenance_step(),
        step_id=UUID("00000000-0000-0000-0000-000000000022"),
        track_version_id=UUID("00000000-0000-0000-0000-000000000021"),
        message_goal="Check whether inventory has improved enough to resume the search.",
        template_key="paused_search_inventory_maintenance",
    )


def _personal_timing_paused_search_track() -> PausedSearchTrack:
    return replace(
        _paused_search_track(),
        track_id=UUID("00000000-0000-0000-0000-000000000023"),
        track_key="personal-timing",
        display_name="Personal Timing",
        active_version_id=UUID("00000000-0000-0000-0000-000000000024"),
    )


def _personal_timing_paused_search_track_version() -> PausedSearchTrackVersion:
    return replace(
        _paused_search_track_version(),
        track_version_id=UUID("00000000-0000-0000-0000-000000000024"),
        track_id=UUID("00000000-0000-0000-0000-000000000023"),
        track_family=PausedSearchTrackFamily.MAINTENANCE,
        default_for_reason_codes=(PausedSearchReasonCode.PERSONAL_LIFE_TIMING,),
    )


def _personal_timing_paused_search_step() -> PausedSearchTrackStep:
    return replace(
        _paused_search_maintenance_step(),
        step_id=UUID("00000000-0000-0000-0000-000000000025"),
        track_version_id=UUID("00000000-0000-0000-0000-000000000024"),
        message_goal="Send a low-pressure timing check-in.",
        template_key="paused_search_personal_timing_maintenance",
    )


def _paused_search_track_step() -> PausedSearchTrackStep:
    return PausedSearchTrackStep(
        step_id=UUID("00000000-0000-0000-0000-000000000016"),
        workspace_id=WORKSPACE_ID,
        track_version_id=UUID("00000000-0000-0000-0000-000000000015"),
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


def _paused_search_maintenance_step() -> PausedSearchTrackStep:
    return PausedSearchTrackStep(
        step_id=UUID("00000000-0000-0000-0000-000000000019"),
        workspace_id=WORKSPACE_ID,
        track_version_id=UUID("00000000-0000-0000-0000-000000000015"),
        step_order=1,
        phase=PausedSearchTrackStepPhase.MAINTENANCE,
        channel=ContactChannel.EMAIL,
        delay_hours=24 * 30,
        message_goal="Check in while the lead is still waiting for rates to improve.",
        template_key="paused_search_rates_watch_maintenance",
        max_attempts=1,
        review_required=False,
        created_at=NOW,
    )


def _transition() -> WorkflowTransition:
    return WorkflowTransition(
        transition_id=UUID("00000000-0000-0000-0000-000000000010"),
        workspace_id=WORKSPACE_ID,
        workflow_id=WORKFLOW_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        from_state=WorkflowState.ACTIVE_NURTURE,
        to_state=WorkflowState.WAITING_FOR_RESPONSE,
        reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_SENT,
        created_at=NOW,
    )


def _workflow_override_audit() -> LeadWorkflowOverrideAuditLog:
    return LeadWorkflowOverrideAuditLog(
        audit_log_id=UUID("00000000-0000-0000-0000-000000000014"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        actor_user_id=USER_ID,
        action=LeadWorkflowOverrideAction.TIMING_CHANGED,
        reason="Agent asked to move reactivation by 30 days.",
        details={"new_reengagement_window_label": "check back in 120 days"},
        created_at=NOW,
    )


def _paused_search_history_entry() -> LeadPausedSearchHistoryEntry:
    return LeadPausedSearchHistoryEntry(
        history_id=UUID("00000000-0000-0000-0000-000000000013"),
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
    )


def _inbound_message() -> InboundMessage:
    return InboundMessage(
        inbound_message_id=INBOUND_ID,
        workspace_id=WORKSPACE_ID,
        conversation_id=UUID("00000000-0000-0000-0000-000000000011"),
        lead_id=LEAD_ID,
        channel=ContactChannel.SMS,
        provider="twilio",
        provider_message_id="pm-1",
        body="Still interested",
        received_at=NOW,
        classification_status=InboundMessageClassificationStatus.CLASSIFIED,
        created_at=NOW,
    )


def _outbound_message() -> OutboundMessage:
    return OutboundMessage(
        message_id=MESSAGE_ID,
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
    )


def _handoff() -> Handoff:
    return Handoff(
        handoff_id=HANDOFF_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        reason_code=HandoffReasonCode.HUMAN_REQUESTED,
        summary="Lead asked for a callback.",
        created_at=NOW,
    )


def _user() -> User:
    return User(
        user_id=USER_ID,
        email="agent@example.com",
        email_normalized="agent@example.com",
        full_name="Jordan Agent",
        status=UserStatus.ACTIVE,
        email_verified_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _activity_items() -> tuple[LeadActivityItem, ...]:
    return (
        LeadActivityItem(
            activity_id=INBOUND_ID,
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
            activity_id=MESSAGE_ID,
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
            activity_id=HANDOFF_ID,
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
        review_id=UUID("00000000-0000-0000-0000-000000000012"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        workflow_transition_id=UUID("00000000-0000-0000-0000-000000000013"),
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=UUID("00000000-0000-0000-0000-000000000014"),
        cadence_step_id=UUID("00000000-0000-0000-0000-000000000015"),
        channel=ContactChannel.SMS,
        status=RejectedDraftReviewStatus.PENDING_REVIEW,
        reason_codes=("draft_rejected",),
        draft_reason_codes=("low_confidence",),
        review_blockers=(),
        draft_safety_flags=(),
        draft_personalization_notes=("Used safe canonical context.",),
        draft_body="Checking in about your plans.",
        explanation="Planning blocked: draft rejected.",
        draft_confidence=0.42,
        draft_model="openai/gpt-4o-mini",
        draft_prompt_version="outbound_message_draft:v1",
        can_approve_send=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _routing_review() -> LeadRoutingReview:
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
        resolution=None,
        reviewed_by_user_id=USER_ID,
        reviewed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _routing_review_repository(
    reviews: tuple[LeadRoutingReview, ...] = (),
) -> FakeLeadRoutingReviewRepository:
    repository = FakeLeadRoutingReviewRepository()
    repository.saved.extend(reviews)
    return repository


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
