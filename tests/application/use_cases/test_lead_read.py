import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.ports.lead_activity import LeadActivityItem, LeadActivityKind
from app.application.services.lead_cadence_progress import (
    CadenceStepProgressStatus,
    LeadCadenceJourney,
    build_dormant_cadence_progress,
    build_lead_status_narrative,
    build_paused_search_cadence_progress,
)
from app.application.services.lead_decision_tree import (
    PausedSearchTrackOptionSpec,
    build_lead_decision_tree,
)
from app.application.use_cases.lead_read import (
    LeadReadReasonCode,
    LeadReadStatus,
    _paused_search_plan_view,
    get_lead_detail_view,
    list_lead_views,
)
from app.domain.campaigns.execution import CampaignCadenceStep, CampaignVersionStatus
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTrack,
    PausedSearchTrackAssignment,
    PausedSearchTrackAssignmentSource,
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
    FakePausedSearchTrackAssignmentRepository,
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
TRACK_VERSION_ID = UUID("00000000-0000-0000-0000-000000000015")


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
            paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(
                (_paused_search_track_assignment(),)
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
        "identifies which configured track is assigned"
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


def test_decision_tree_does_not_assign_first_track_when_workflow_is_unpinned() -> None:
    decision_tree = build_lead_decision_tree(
        lead=_lead(),
        classification_artifact=_classification_artifact(),
        paused_search_track=None,
        paused_search_track_version=None,
        paused_search_steps=(),
        paused_search_current_step=None,
        paused_search_track_options=(
            PausedSearchTrackOptionSpec(
                track=_paused_search_track(),
                version=_paused_search_track_version(),
                steps=(_paused_search_track_step(),),
            ),
        ),
        latest_workflow=replace(_workflow(), paused_search_track_version_id=None),
        latest_handoff=None,
    )

    unassigned_node = next(
        node for node in decision_tree.nodes if node.node_id == "paused_search_track_unassigned"
    )
    track_node = next(node for node in decision_tree.nodes if node.label == "Rates Watch")
    assert unassigned_node.status.value == "current"
    assert track_node.status.value == "available"


def test_decision_tree_renders_assigned_track_without_workflow() -> None:
    decision_tree = build_lead_decision_tree(
        lead=_lead(),
        classification_artifact=_classification_artifact(),
        paused_search_track=_paused_search_track(),
        paused_search_track_version=_paused_search_track_version(),
        paused_search_steps=(_paused_search_track_step(),),
        paused_search_current_step=None,
        paused_search_track_options=(
            PausedSearchTrackOptionSpec(
                track=_paused_search_track(),
                version=_paused_search_track_version(),
                steps=(_paused_search_track_step(),),
            ),
        ),
        latest_workflow=None,
        latest_handoff=None,
    )

    track_node = next(node for node in decision_tree.nodes if node.label == "Rates Watch")
    state_node = next(node for node in decision_tree.nodes if node.node_id == "paused_search_state")
    assert track_node.status.value == "taken"
    assert state_node.label == "Paused"
    assert any(
        "durable paused-search assignment" in (edge.description or "")
        for edge in decision_tree.edges
    )


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


def test_paused_search_plan_uses_assignment_without_workflow() -> None:
    plan = asyncio.run(
        _paused_search_plan_view(
            WORKSPACE_ID,
            LEAD_ID,
            _lead(),
            None,
            FakePausedSearchTrackAssignmentRepository((_paused_search_track_assignment(),)),
            FakePausedSearchTrackAdminRepository(
                tracks=(_paused_search_track(),),
                versions=(_paused_search_track_version(),),
                steps=(_paused_search_track_step(),),
            ),
        )
    )

    assert plan is not None
    assert plan.track.track_key == "rates-watch"
    assert plan.version.version_number == 3
    assert plan.steps[0].template_key == "paused_search_rates_watch_reactivation"


def test_paused_search_plan_hidden_when_lead_profile_inactive_and_workflow_unpinned() -> None:
    plan = asyncio.run(
        _paused_search_plan_view(
            WORKSPACE_ID,
            LEAD_ID,
            replace(
                _lead(),
                paused_search_active=False,
                paused_search_track_key=None,
                paused_search_track_version_id=None,
            ),
            None,
            FakePausedSearchTrackAssignmentRepository((_paused_search_track_assignment(),)),
            FakePausedSearchTrackAdminRepository(
                tracks=(_paused_search_track(),),
                versions=(_paused_search_track_version(),),
                steps=(_paused_search_track_step(),),
            ),
        )
    )

    assert plan is None


def _cadence_step(step_id: UUID, order: int, channel: ContactChannel) -> CampaignCadenceStep:
    return CampaignCadenceStep(
        cadence_step_id=step_id,
        workspace_id=WORKSPACE_ID,
        campaign_version_id=UUID("00000000-0000-0000-0000-000000000030"),
        step_order=order,
        channel=channel,
        delay_hours=24,
        message_goal=f"Step {order} goal",
        template_key=f"step-{order}",
        max_attempts=1,
        created_at=NOW,
    )


def _step_message(
    step_id: UUID,
    status: OutboundMessageStatus,
    *,
    failure_reason: str | None = None,
) -> OutboundMessage:
    return replace(
        _outbound_message(),
        message_id=UUID(int=hash((str(step_id), status.value)) % (2**32)),
        cadence_step_id=str(step_id),
        status=status,
        sent_at=NOW if status == OutboundMessageStatus.SENT else None,
        failure_reason=failure_reason,
    )


STEP_1 = UUID("00000000-0000-0000-0000-000000000031")
STEP_2 = UUID("00000000-0000-0000-0000-000000000032")
STEP_3 = UUID("00000000-0000-0000-0000-000000000033")


def test_dormant_cadence_progress_derives_steps_without_cursor() -> None:
    steps = (
        _cadence_step(STEP_1, 1, ContactChannel.EMAIL),
        _cadence_step(STEP_2, 2, ContactChannel.SMS),
        _cadence_step(STEP_3, 3, ContactChannel.EMAIL),
    )
    messages = (
        _step_message(STEP_1, OutboundMessageStatus.SENT),
        _step_message(STEP_2, OutboundMessageStatus.FAILED, failure_reason="undeliverable"),
    )
    workflow = replace(
        _workflow(),
        current_step_id=None,
        paused_search_track_version_id=None,
        paused_search_track_step_id=None,
    )

    progress = build_dormant_cadence_progress(
        flow_name="Dormant Buyers",
        cadence_steps=steps,
        outbound_messages=messages,
        workflow=workflow,
    )

    assert progress is not None
    assert progress.journey == LeadCadenceJourney.DORMANT
    assert progress.total_steps == 3
    assert progress.completed_steps == 1
    statuses = {step.step_id: step.status for step in progress.steps}
    assert statuses[STEP_1] == CadenceStepProgressStatus.COMPLETED
    assert statuses[STEP_2] == CadenceStepProgressStatus.FAILED
    assert statuses[STEP_3] == CadenceStepProgressStatus.UPCOMING
    assert progress.current_step_order is None
    failed_step = next(step for step in progress.steps if step.step_id == STEP_2)
    assert failed_step.last_failure_reason == "undeliverable"
    assert failed_step.attempt_count == 1


def test_dormant_cadence_progress_uses_cursor_when_present() -> None:
    steps = (
        _cadence_step(STEP_1, 1, ContactChannel.EMAIL),
        _cadence_step(STEP_2, 2, ContactChannel.SMS),
    )
    workflow = replace(
        _workflow(),
        current_step_id=STEP_2,
        paused_search_track_version_id=None,
        paused_search_track_step_id=None,
    )

    progress = build_dormant_cadence_progress(
        flow_name="Dormant Buyers",
        cadence_steps=steps,
        outbound_messages=(_step_message(STEP_1, OutboundMessageStatus.SENT),),
        workflow=workflow,
    )

    assert progress is not None
    assert progress.current_step_order == 2
    assert progress.is_sendable is True
    assert progress.workflow_state == WorkflowState.WAITING_FOR_RESPONSE
    statuses = {step.step_id: step.status for step in progress.steps}
    assert statuses[STEP_1] == CadenceStepProgressStatus.COMPLETED
    assert statuses[STEP_2] == CadenceStepProgressStatus.CURRENT


def test_dormant_cadence_progress_ignores_prior_workflow_run_messages() -> None:
    """Re-enrollment must not inherit sent/failed state from a closed run."""
    steps = (
        _cadence_step(STEP_1, 1, ContactChannel.EMAIL),
        _cadence_step(STEP_2, 2, ContactChannel.SMS),
    )
    prior_run_workflow_id = UUID("00000000-0000-0000-0000-000000000099")
    prior_run_messages = tuple(
        replace(message, workflow_id=prior_run_workflow_id)
        for message in (
            _step_message(STEP_1, OutboundMessageStatus.SENT),
            _step_message(STEP_2, OutboundMessageStatus.SENT),
        )
    )
    workflow = replace(
        _workflow(),
        current_step_id=STEP_1,
        paused_search_track_version_id=None,
        paused_search_track_step_id=None,
    )

    progress = build_dormant_cadence_progress(
        flow_name="Dormant Buyers",
        cadence_steps=steps,
        outbound_messages=prior_run_messages,
        workflow=workflow,
    )

    assert progress is not None
    assert progress.completed_steps == 0
    statuses = {step.step_id: step.status for step in progress.steps}
    assert statuses[STEP_1] == CadenceStepProgressStatus.CURRENT
    assert statuses[STEP_2] == CadenceStepProgressStatus.UPCOMING


def test_dormant_cadence_progress_attributes_legacy_messages_by_run_start() -> None:
    """Messages without workflow attribution belong to the run only if created after it began."""
    steps = (_cadence_step(STEP_1, 1, ContactChannel.EMAIL),)
    stale = replace(
        _step_message(STEP_1, OutboundMessageStatus.SENT),
        created_at=NOW - timedelta(days=3),
    )
    workflow = replace(
        _workflow(),
        current_step_id=STEP_1,
        paused_search_track_version_id=None,
        paused_search_track_step_id=None,
    )

    progress = build_dormant_cadence_progress(
        flow_name="Dormant Buyers",
        cadence_steps=steps,
        outbound_messages=(stale,),
        workflow=workflow,
    )

    assert progress is not None
    assert progress.completed_steps == 0
    assert progress.steps[0].status == CadenceStepProgressStatus.CURRENT


def test_dormant_cadence_progress_terminal_workflow_has_no_current_step() -> None:
    steps = (_cadence_step(STEP_1, 1, ContactChannel.EMAIL),)
    workflow = replace(
        _workflow(),
        state=WorkflowState.COMPLETED,
        current_step_id=None,
    )

    progress = build_dormant_cadence_progress(
        flow_name="Dormant Buyers",
        cadence_steps=steps,
        outbound_messages=(),
        workflow=workflow,
    )

    assert progress is not None
    assert progress.current_step_order is None
    assert progress.steps[0].status == CadenceStepProgressStatus.UPCOMING


def test_dormant_cadence_progress_non_sendable_workflows_have_no_current_step() -> None:
    """Paused/handoff/human-owned workflows are not actively progressing."""
    steps = (
        _cadence_step(STEP_1, 1, ContactChannel.EMAIL),
        _cadence_step(STEP_2, 2, ContactChannel.EMAIL),
    )
    for state in (
        WorkflowState.PAUSED,
        WorkflowState.HUMAN_HANDOFF,
        WorkflowState.HUMAN_OWNED,
    ):
        # Mirrors the handoff path: the transition clears the cursor and
        # next_action_at, leaving one sent step and one never-sent step.
        workflow = replace(
            _workflow(),
            state=state,
            current_step_id=None,
            next_action_at=None,
            paused_search_track_version_id=None,
            paused_search_track_step_id=None,
        )

        progress = build_dormant_cadence_progress(
            flow_name="Dormant Buyers",
            cadence_steps=steps,
            outbound_messages=(_step_message(STEP_1, OutboundMessageStatus.SENT),),
            workflow=workflow,
        )

        assert progress is not None
        assert progress.current_step_order is None, state
        assert progress.completed_steps == 1
        assert progress.is_sendable is False
        assert progress.workflow_state == state
        statuses = {step.step_id: step.status for step in progress.steps}
        assert statuses[STEP_1] == CadenceStepProgressStatus.COMPLETED
        assert statuses[STEP_2] == CadenceStepProgressStatus.UPCOMING


def test_dormant_cadence_progress_paused_workflow_suppresses_cursor_current_step() -> None:
    """Pausing keeps current_step_id on the workflow; it must not surface."""
    steps = (
        _cadence_step(STEP_1, 1, ContactChannel.EMAIL),
        _cadence_step(STEP_2, 2, ContactChannel.EMAIL),
    )
    workflow = replace(
        _workflow(),
        state=WorkflowState.PAUSED,
        current_step_id=STEP_2,
        next_action_at=None,
        paused_search_track_version_id=None,
        paused_search_track_step_id=None,
    )

    progress = build_dormant_cadence_progress(
        flow_name="Dormant Buyers",
        cadence_steps=steps,
        outbound_messages=(_step_message(STEP_1, OutboundMessageStatus.SENT),),
        workflow=workflow,
    )

    assert progress is not None
    assert progress.current_step_order is None
    statuses = {step.step_id: step.status for step in progress.steps}
    assert statuses[STEP_1] == CadenceStepProgressStatus.COMPLETED
    assert statuses[STEP_2] == CadenceStepProgressStatus.UPCOMING


def test_paused_search_cadence_progress_uses_track_cursor() -> None:
    steps = (_paused_search_maintenance_step(), _paused_search_track_step())
    workflow = _workflow()  # cursor points at reactivation step ...16

    progress = build_paused_search_cadence_progress(
        flow_name="Rates Watch",
        track_steps=steps,
        outbound_messages=(),
        workflow=workflow,
    )

    assert progress is not None
    assert progress.journey == LeadCadenceJourney.PAUSED_SEARCH
    current = next(
        step
        for step in progress.steps
        if step.step_id == UUID("00000000-0000-0000-0000-000000000016")
    )
    assert current.status == CadenceStepProgressStatus.CURRENT
    assert current.phase == "reactivation"


def test_paused_search_cadence_progress_projects_occurrences_and_repeats() -> None:
    maintenance_step = replace(_paused_search_maintenance_step(), interval_days=30)
    reactivation_step = _paused_search_track_step()
    workflow = replace(
        _workflow(),
        paused_search_track_step_id=maintenance_step.step_id,
        next_action_at=NOW,
    )
    profile = LeadPausedSearchProfile(
        paused_search_active=True,
        paused_search_track_key="rates-watch",
        paused_search_track_version_id=TRACK_VERSION_ID,
        reengagement_not_before=datetime(2030, 6, 1, tzinfo=UTC),
    )

    progress = build_paused_search_cadence_progress(
        flow_name="Rates Watch",
        track_steps=(maintenance_step, reactivation_step),
        outbound_messages=(),
        workflow=workflow,
        profile=profile,
        track_version=_paused_search_track_version(),
        timezone="UTC",
        now=NOW,
    )

    assert progress is not None
    maintenance = next(
        step for step in progress.steps if step.step_id == maintenance_step.step_id
    )
    reactivation = next(
        step for step in progress.steps if step.step_id == reactivation_step.step_id
    )
    # Maintenance repeats every 30 days until the reactivation window opens
    # (2030-05-18 = reengagement 2030-06-01 minus the 14-day window).
    assert maintenance.interval_days == 30
    assert [occurrence.occurrence_number for occurrence in maintenance.occurrences] == [
        1,
        2,
        3,
        4,
    ]
    assert maintenance.occurrences[0].projected_for == NOW
    assert maintenance.occurrences[1].projected_for == datetime(2030, 3, 2, 12, 0, tzinfo=UTC)
    assert maintenance.occurrences[3].projected_for == datetime(2030, 5, 1, 12, 0, tzinfo=UTC)
    # The reactivation step is projected at the window start, rolled into
    # the allowed send window.
    assert len(reactivation.occurrences) == 1
    projected = reactivation.occurrences[0].projected_for
    assert projected == datetime(2030, 5, 18, 10, 0, tzinfo=UTC)
    assert reactivation.scheduled_for == projected


def test_paused_search_cadence_progress_does_not_project_when_human_handoff() -> None:
    """A handoff halts the track; projecting future sends would be misleading."""
    maintenance_step = replace(_paused_search_maintenance_step(), interval_days=30)
    reactivation_step = _paused_search_track_step()
    workflow = replace(
        _workflow(),
        state=WorkflowState.HUMAN_HANDOFF,
        next_action_at=None,
    )
    profile = LeadPausedSearchProfile(
        paused_search_active=True,
        paused_search_track_key="rates-watch",
        paused_search_track_version_id=TRACK_VERSION_ID,
        reengagement_not_before=datetime(2030, 6, 1, tzinfo=UTC),
    )

    progress = build_paused_search_cadence_progress(
        flow_name="Rates Watch",
        track_steps=(maintenance_step, reactivation_step),
        outbound_messages=(),
        workflow=workflow,
        profile=profile,
        track_version=_paused_search_track_version(),
        timezone="UTC",
        now=NOW,
    )

    assert progress is not None
    assert progress.current_step_order is None
    assert all(step.occurrences == () for step in progress.steps)
    assert all(step.scheduled_for is None for step in progress.steps)


def test_status_narrative_without_workflow() -> None:
    narrative = build_lead_status_narrative(workflow=None, progress_views=(), now=NOW)
    assert "No nurture workflow yet" in narrative


def test_status_narrative_includes_step_and_next_action() -> None:
    steps = (
        _cadence_step(STEP_1, 1, ContactChannel.EMAIL),
        _cadence_step(STEP_2, 2, ContactChannel.SMS),
    )
    workflow = replace(
        _workflow(),
        current_step_id=STEP_2,
        next_action_at=datetime(2030, 1, 2, 15, 0, tzinfo=UTC),
        paused_search_track_version_id=None,
        paused_search_track_step_id=None,
    )
    progress = build_dormant_cadence_progress(
        flow_name="Dormant Buyers",
        cadence_steps=steps,
        outbound_messages=(_step_message(STEP_1, OutboundMessageStatus.SENT),),
        workflow=workflow,
    )
    assert progress is not None

    narrative = build_lead_status_narrative(
        workflow=workflow,
        progress_views=(progress,),
        now=NOW,
    )

    assert "Waiting for the lead to respond" in narrative
    assert "step 2 of 2 in Dormant Buyers" in narrative
    assert "next action scheduled for" in narrative


def test_status_narrative_paused_includes_reason() -> None:
    workflow = replace(
        _workflow(),
        state=WorkflowState.PAUSED,
        pause_reason="Agent activity detected",
    )

    narrative = build_lead_status_narrative(workflow=workflow, progress_views=(), now=NOW)

    assert "AI outreach is paused" in narrative
    assert "Agent activity detected" in narrative


def test_status_narrative_between_runs_shows_reengagement_date() -> None:
    """A terminal run with an active paused-search profile leads with the
    profile's re-engagement plan, not the finished run."""
    workflow = replace(_workflow(), state=WorkflowState.COMPLETED)
    profile = LeadPausedSearchProfile(
        paused_search_active=True,
        paused_search_track_key="rates-watch",
        paused_search_track_version_id=TRACK_VERSION_ID,
        reengagement_not_before=datetime(2030, 6, 1, tzinfo=UTC),
    )

    narrative = build_lead_status_narrative(
        workflow=workflow,
        progress_views=(),
        now=NOW,
        paused_search_profile=profile,
    )

    assert "Paused — search on hold" in narrative
    assert "re-engages Jun 1, 2030" in narrative
    assert "previous run completed" in narrative


def test_status_narrative_between_runs_with_window_label() -> None:
    profile = LeadPausedSearchProfile(
        paused_search_active=True,
        paused_search_track_key="rates-watch",
        paused_search_track_version_id=TRACK_VERSION_ID,
        reengagement_window_label="in the spring",
    )

    narrative = build_lead_status_narrative(
        workflow=None,
        progress_views=(),
        now=NOW,
        paused_search_profile=profile,
    )

    assert "Paused — search on hold" in narrative
    assert "re-engages in the spring" in narrative


def test_status_narrative_active_run_ignores_paused_search_profile() -> None:
    """An active run's narrative is not overridden by a lingering profile."""
    profile = LeadPausedSearchProfile(
        paused_search_active=True,
        paused_search_track_key="rates-watch",
        paused_search_track_version_id=TRACK_VERSION_ID,
    )

    narrative = build_lead_status_narrative(
        workflow=_workflow(),
        progress_views=(),
        now=NOW,
        paused_search_profile=profile,
    )

    assert "Waiting for the lead to respond" in narrative
    assert "search on hold" not in narrative


def test_get_lead_detail_view_includes_cadence_progress_and_narrative() -> None:
    result = asyncio.run(
        get_lead_detail_view(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            lead_repository=FakeLeadRepository((_lead(),)),
            paused_search_history_repository=FakeLeadPausedSearchHistoryRepository(()),
            classification_artifact_repository=FakeLeadClassificationArtifactRepository(()),
            workflow_repository=FakeLeadWorkflowRepository((_workflow(),)),
            workflow_override_audit_repository=FakeLeadWorkflowOverrideAuditLogRepository(()),
            workflow_transition_repository=FakeWorkflowTransitionRepository(()),
            paused_search_track_repository=FakePausedSearchTrackAdminRepository(
                tracks=(_paused_search_track(),),
                versions=(_paused_search_track_version(),),
                steps=(_paused_search_maintenance_step(), _paused_search_track_step()),
            ),
            paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(
                (_paused_search_track_assignment(),)
            ),
            activity_repository=FakeLeadActivityRepository(()),
            rejected_draft_review_repository=FakeRejectedDraftReviewRepository(()),
            routing_review_repository=_routing_review_repository(),
            inbound_message_repository=FakeInboundMessageRepository(()),
            outbound_message_repository=FakeOutboundMessageRepository(()),
            handoff_repository=FakeHandoffRepository(()),
            user_repository=FakeUserRepository({USER_ID: _user()}),
            crm_agent_repository=FakeCRMAgentRepository(()),
            now=NOW,
        )
    )

    assert result.status == LeadReadStatus.OK
    assert result.view is not None
    assert len(result.view.cadence_progress) == 1
    paused_progress = result.view.cadence_progress[0]
    assert paused_progress.journey == LeadCadenceJourney.PAUSED_SEARCH
    assert paused_progress.flow_name == "Rates Watch"
    assert result.view.status_narrative is not None
    assert "Waiting for the lead to respond" in result.view.status_narrative


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
            paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
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
        paused_search_track_key="waiting-rates",
        paused_search_track_version_id=TRACK_VERSION_ID,
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
        selected_track_key="waiting-for-rates",
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
            '{"outcome":"paused_search","selected_track_key":"waiting-for-rates",'
            '"track_version_id":"00000000-0000-0000-0000-000000000010"}'
        ),
        parsed_llm_response={
            "outcome": "paused_search",
            "selected_track_key": "waiting-for-rates",
            "track_version_id": "00000000-0000-0000-0000-000000000010",
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
        track_version_id=TRACK_VERSION_ID,
        workspace_id=WORKSPACE_ID,
        track_id=UUID("00000000-0000-0000-0000-000000000018"),
        version_number=3,
        status=CampaignVersionStatus.PUBLISHED,
        selection_guidance="Select when a paused lead needs periodic follow-up.",
        enabled=True,
        allowed_channels=(ContactChannel.SMS, ContactChannel.EMAIL),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE,
        maintenance_interval_days=30,
        reactivation_window_days=14,
        max_total_touches=5,
        created_by_user_id=USER_ID,
        created_at=NOW,
        published_at=NOW,
    )


def _paused_search_track_assignment() -> PausedSearchTrackAssignment:
    return PausedSearchTrackAssignment(
        assignment_id=UUID("00000000-0000-0000-0000-000000000017"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        track_id=UUID("00000000-0000-0000-0000-000000000018"),
        track_version_id=UUID("00000000-0000-0000-0000-000000000015"),
        track_key_snapshot="rates-watch",
        track_name_snapshot="Rates Watch",
        track_version_snapshot=3,
        source=PausedSearchTrackAssignmentSource.CLASSIFICATION,
        assigned_by_user_id=USER_ID,
        assigned_at=NOW,
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
        selection_guidance="Use when a lead is waiting for suitable inventory to become available.",
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
        selection_guidance="Use when personal life timing has paused the lead's property search.",
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
            paused_search_track_key="waiting-for-rates",
            paused_search_track_version_id=UUID("00000000-0000-0000-0000-000000000010"),
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
