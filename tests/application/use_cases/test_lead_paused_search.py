import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from app.application.use_cases.lead_paused_search import (
    LeadPausedSearchActionReasonCode,
    LeadPausedSearchActionStatus,
    update_lead_paused_search,
)
from app.domain.campaigns.enrollment import (
    CampaignEnrollment,
    CampaignEnrollmentSource,
    CampaignEnrollmentStatus,
)
from app.domain.campaigns.paused_search_tracks import PausedSearchTerminalBehavior
from app.domain.crm_sync import ExternalEvent
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
    PausedSearchSource,
)
from app.domain.workflows import LeadWorkflow, TemporalSignalName, WorkflowState
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeTemporalSignalOutboxRepository,
    FakeTemporalWorkflowStarter,
)
from tests.application.use_cases._lead_read_fakes import (
    FakeLeadPausedSearchHistoryRepository,
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
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
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000005")
ENROLLMENT_ID = UUID("00000000-0000-0000-0000-000000000006")
TRACK_ID = UUID("00000000-0000-0000-0000-000000000007")
TRACK_VERSION_ID = UUID("00000000-0000-0000-0000-000000000008")


def test_update_lead_paused_search_sets_profile_and_history() -> None:
    lead_repository = FakeLeadRepository((_lead(),))
    history_repository = FakeLeadPausedSearchHistoryRepository(())
    workflow_repository = FakeLeadWorkflowRepository((_workflow(),))
    signal_outbox_repository = FakeTemporalSignalOutboxRepository()

    result = asyncio.run(
        update_lead_paused_search(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            active=True,
            selected_track_key="waiting-rates",
            reason_note="Waiting until rates improve.",
            reengagement_not_before=NOW,
            reengagement_window_label="spring check-in",
            lead_repository=lead_repository,
            paused_search_history_repository=history_repository,
            lead_workflow_repository=workflow_repository,
            paused_search_track_repository=_track_repository(),
            paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
            temporal_signal_outbox_repository=signal_outbox_repository,
            now=NOW,
        )
    )

    assert result.status == LeadPausedSearchActionStatus.UPDATED
    assert result.profile is not None
    assert result.profile.paused_search_track_key == "waiting-rates"
    assert result.profile.paused_search_track_version_id == TRACK_VERSION_ID
    assert result.history_entry is not None
    assert result.history_entry.previous_profile is None
    pinned_workflow = asyncio.run(workflow_repository.get_latest_for_lead(WORKSPACE_ID, LEAD_ID))
    assert pinned_workflow is not None
    assert pinned_workflow.paused_search_track_version_id == TRACK_VERSION_ID
    signal_entry = next(iter(signal_outbox_repository.entries.values()))
    assert signal_entry.signal_name == TemporalSignalName.RESCHEDULE_REQUESTED


def test_update_lead_paused_search_returns_unchanged_for_duplicate_profile() -> None:
    lead_repository = FakeLeadRepository((_paused_search_lead(),))
    history_repository = FakeLeadPausedSearchHistoryRepository(())
    workflow_repository = FakeLeadWorkflowRepository((_workflow(),))
    assignment_repository = FakePausedSearchTrackAssignmentRepository()

    result = asyncio.run(
        update_lead_paused_search(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            active=True,
            selected_track_key="waiting-rates",
            reason_note="Waiting until rates improve.",
            reengagement_not_before=NOW,
            reengagement_window_label="spring check-in",
            lead_repository=lead_repository,
            paused_search_history_repository=history_repository,
            lead_workflow_repository=workflow_repository,
            paused_search_track_repository=_track_repository(),
            paused_search_track_assignment_repository=assignment_repository,
            now=NOW,
        )
    )

    assert result.status == LeadPausedSearchActionStatus.UNCHANGED
    assert result.history_entry is None
    pinned_workflow = asyncio.run(workflow_repository.get_latest_for_lead(WORKSPACE_ID, LEAD_ID))
    assert pinned_workflow is not None
    assert pinned_workflow.paused_search_track_version_id == TRACK_VERSION_ID
    assignment = asyncio.run(assignment_repository.get_active_for_lead(WORKSPACE_ID, LEAD_ID))
    assert assignment is not None


def test_update_lead_paused_search_clears_existing_profile() -> None:
    lead_repository = FakeLeadRepository((_paused_search_lead(),))
    history_repository = FakeLeadPausedSearchHistoryRepository(())
    workflow_repository = FakeLeadWorkflowRepository(
        (_workflow(paused_search_track_version_id=TRACK_VERSION_ID),)
    )
    assignment_repository = FakePausedSearchTrackAssignmentRepository()
    signal_outbox_repository = FakeTemporalSignalOutboxRepository()

    result = asyncio.run(
        update_lead_paused_search(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            active=False,
            selected_track_key=None,
            reason_note=None,
            reengagement_not_before=None,
            reengagement_window_label=None,
            lead_repository=lead_repository,
            paused_search_history_repository=history_repository,
            lead_workflow_repository=workflow_repository,
            paused_search_track_repository=_track_repository(),
            paused_search_track_assignment_repository=assignment_repository,
            temporal_signal_outbox_repository=signal_outbox_repository,
            now=NOW,
        )
    )

    assert result.status == LeadPausedSearchActionStatus.CLEARED
    assert result.profile is None
    assert result.history_entry is not None
    assert result.history_entry.current_profile is None
    pinned_workflow = asyncio.run(workflow_repository.get_latest_for_lead(WORKSPACE_ID, LEAD_ID))
    assert pinned_workflow is not None
    assert pinned_workflow.paused_search_track_version_id is None
    assert asyncio.run(assignment_repository.get_active_for_lead(WORKSPACE_ID, LEAD_ID)) is None
    signal_entry = next(iter(signal_outbox_repository.entries.values()))
    assert signal_entry.signal_name == TemporalSignalName.RESCHEDULE_REQUESTED


def test_assigned_agent_cannot_edit_unowned_paused_search_profile() -> None:
    result = asyncio.run(
        update_lead_paused_search(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            active=True,
            selected_track_key="waiting-rates",
            reason_note=None,
            reengagement_not_before=None,
            reengagement_window_label=None,
            lead_repository=FakeLeadRepository(
                (_lead(owner_id=UUID("00000000-0000-0000-0000-000000000099")),)
            ),
            paused_search_history_repository=FakeLeadPausedSearchHistoryRepository(()),
            lead_workflow_repository=FakeLeadWorkflowRepository((_workflow(),)),
            paused_search_track_repository=_track_repository(),
            paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
            now=NOW,
        )
    )

    assert result.status == LeadPausedSearchActionStatus.REJECTED
    assert result.reasons == (LeadPausedSearchActionReasonCode.PERMISSION_DENIED,)


def test_clear_with_terminal_behavior_terminalizes_active_workflow() -> None:
    lead_repository = FakeLeadRepository((_paused_search_lead(),))
    workflow_repository = FakeLeadWorkflowRepository(
        (_workflow(paused_search_track_version_id=TRACK_VERSION_ID),)
    )
    transition_repository = FakeWorkflowTransitionRepository(())
    signal_outbox_repository = FakeTemporalSignalOutboxRepository()

    result = asyncio.run(
        update_lead_paused_search(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            active=False,
            selected_track_key=None,
            reason_note=None,
            reengagement_not_before=None,
            reengagement_window_label=None,
            lead_repository=lead_repository,
            paused_search_history_repository=FakeLeadPausedSearchHistoryRepository(()),
            lead_workflow_repository=workflow_repository,
            paused_search_track_repository=_track_repository(),
            paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
            temporal_signal_outbox_repository=signal_outbox_repository,
            terminal_behavior=PausedSearchTerminalBehavior.COMPLETE_KEEP_PAUSED,
            terminal_reason="Switching to dormant path",
            workflow_transition_repository=transition_repository,
            external_event_repository=FakeExternalEventRepository(),
            now=NOW,
        )
    )

    assert result.status == LeadPausedSearchActionStatus.CLEARED
    assert result.workflow_terminalized is True
    assert result.workflow_state == WorkflowState.COMPLETED
    workflow = asyncio.run(workflow_repository.get_latest_for_lead(WORKSPACE_ID, LEAD_ID))
    assert workflow is not None
    assert workflow.state == WorkflowState.COMPLETED
    assert not signal_outbox_repository.entries


def test_clear_with_terminal_behavior_completes_track_run_without_restarting() -> None:
    """Clearing a track ends its run and stops there: no fresh dormant run, no
    automatic send. What happens next is a separate explicit admin enrollment."""
    lead_repository = FakeLeadRepository((_paused_search_lead(),))
    workflow_repository = FakeLeadWorkflowRepository(
        (
            replace(
                _workflow(paused_search_track_version_id=TRACK_VERSION_ID),
                state=WorkflowState.ACTIVE_NURTURE,
            ),
        )
    )
    transition_repository = FakeWorkflowTransitionRepository(())
    enrollment_repository = FakeCampaignEnrollmentRepository()
    asyncio.run(enrollment_repository.save(_enrollment()))
    starter = FakeTemporalWorkflowStarter()

    result = asyncio.run(
        update_lead_paused_search(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            active=False,
            selected_track_key=None,
            reason_note=None,
            reengagement_not_before=None,
            reengagement_window_label=None,
            lead_repository=lead_repository,
            paused_search_history_repository=FakeLeadPausedSearchHistoryRepository(()),
            lead_workflow_repository=workflow_repository,
            paused_search_track_repository=_track_repository(),
            paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
            temporal_signal_outbox_repository=FakeTemporalSignalOutboxRepository(),
            terminal_behavior=PausedSearchTerminalBehavior.COMPLETE_KEEP_PAUSED,
            terminal_reason="Switching to dormant path",
            workflow_transition_repository=transition_repository,
            campaign_enrollment_repository=enrollment_repository,
            temporal_workflow_starter=starter,
            external_event_repository=FakeExternalEventRepository(),
            now=NOW,
        )
    )

    assert result.status == LeadPausedSearchActionStatus.CLEARED
    assert result.workflow_terminalized is True
    assert result.workflow_state == WorkflowState.COMPLETED
    workflow = asyncio.run(workflow_repository.get_latest_for_lead(WORKSPACE_ID, LEAD_ID))
    assert workflow is not None
    assert workflow.workflow_id == WORKFLOW_ID
    assert workflow.state == WorkflowState.COMPLETED
    assert starter.calls == []


def test_clear_without_terminal_behavior_completes_orphaned_track_run() -> None:
    """Even without an explicit choice, a live track-pinned run must end on clear:
    its track is gone, so the paused-search execution has no valid plan left.
    The run is completed (re-enrollable), never restarted."""
    lead_repository = FakeLeadRepository((_paused_search_lead(),))
    workflow_repository = FakeLeadWorkflowRepository(
        (
            replace(
                _workflow(paused_search_track_version_id=TRACK_VERSION_ID),
                state=WorkflowState.ACTIVE_NURTURE,
            ),
        )
    )
    transition_repository = FakeWorkflowTransitionRepository(())
    enrollment_repository = FakeCampaignEnrollmentRepository()
    asyncio.run(enrollment_repository.save(_enrollment()))
    starter = FakeTemporalWorkflowStarter()

    result = asyncio.run(
        update_lead_paused_search(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            active=False,
            selected_track_key=None,
            reason_note=None,
            reengagement_not_before=None,
            reengagement_window_label=None,
            lead_repository=lead_repository,
            paused_search_history_repository=FakeLeadPausedSearchHistoryRepository(()),
            lead_workflow_repository=workflow_repository,
            paused_search_track_repository=_track_repository(),
            paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
            terminal_behavior=None,
            workflow_transition_repository=transition_repository,
            campaign_enrollment_repository=enrollment_repository,
            temporal_workflow_starter=starter,
            external_event_repository=FakeExternalEventRepository(),
            now=NOW,
        )
    )

    assert result.status == LeadPausedSearchActionStatus.CLEARED
    assert result.workflow_terminalized is True
    assert result.workflow_state == WorkflowState.COMPLETED
    workflow = asyncio.run(workflow_repository.get_latest_for_lead(WORKSPACE_ID, LEAD_ID))
    assert workflow is not None
    assert workflow.workflow_id == WORKFLOW_ID
    assert workflow.state == WorkflowState.COMPLETED
    assert starter.calls == []


def test_clear_without_terminal_behavior_leaves_dormant_run_alone() -> None:
    """A live dormant (unpinned) run is not the cleared track's run, so a plain
    clear does not touch it."""
    lead_repository = FakeLeadRepository((_paused_search_lead(),))
    workflow_repository = FakeLeadWorkflowRepository(
        (replace(_workflow(), state=WorkflowState.ACTIVE_NURTURE),)
    )

    result = asyncio.run(
        update_lead_paused_search(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            active=False,
            selected_track_key=None,
            reason_note=None,
            reengagement_not_before=None,
            reengagement_window_label=None,
            lead_repository=lead_repository,
            paused_search_history_repository=FakeLeadPausedSearchHistoryRepository(()),
            lead_workflow_repository=workflow_repository,
            paused_search_track_repository=_track_repository(),
            paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
            terminal_behavior=None,
            workflow_transition_repository=FakeWorkflowTransitionRepository(()),
            external_event_repository=FakeExternalEventRepository(),
            now=NOW,
        )
    )

    assert result.status == LeadPausedSearchActionStatus.CLEARED
    assert result.workflow_terminalized is False
    assert result.workflow_state == WorkflowState.ACTIVE_NURTURE
    workflow = asyncio.run(workflow_repository.get_latest_for_lead(WORKSPACE_ID, LEAD_ID))
    assert workflow is not None
    assert workflow.workflow_id == WORKFLOW_ID
    assert workflow.state == WorkflowState.ACTIVE_NURTURE


def test_clear_with_close_automation_terminalizes_without_restart() -> None:
    """Close-automation is an explicit stop intent: no fresh dormant run starts."""
    lead_repository = FakeLeadRepository((_paused_search_lead(),))
    workflow_repository = FakeLeadWorkflowRepository(
        (
            replace(
                _workflow(paused_search_track_version_id=TRACK_VERSION_ID),
                state=WorkflowState.ACTIVE_NURTURE,
            ),
        )
    )
    transition_repository = FakeWorkflowTransitionRepository(())
    enrollment_repository = FakeCampaignEnrollmentRepository()
    asyncio.run(enrollment_repository.save(_enrollment()))
    starter = FakeTemporalWorkflowStarter()

    result = asyncio.run(
        update_lead_paused_search(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            active=False,
            selected_track_key=None,
            reason_note=None,
            reengagement_not_before=None,
            reengagement_window_label=None,
            lead_repository=lead_repository,
            paused_search_history_repository=FakeLeadPausedSearchHistoryRepository(()),
            lead_workflow_repository=workflow_repository,
            paused_search_track_repository=_track_repository(),
            paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
            terminal_behavior=PausedSearchTerminalBehavior.CLOSE_AUTOMATION,
            terminal_reason="Stop automation",
            workflow_transition_repository=transition_repository,
            campaign_enrollment_repository=enrollment_repository,
            temporal_workflow_starter=starter,
            external_event_repository=FakeExternalEventRepository(),
            now=NOW,
        )
    )

    assert result.status == LeadPausedSearchActionStatus.CLEARED
    assert result.workflow_terminalized is True
    assert result.workflow_state == WorkflowState.CLOSED
    workflow = asyncio.run(workflow_repository.get_latest_for_lead(WORKSPACE_ID, LEAD_ID))
    assert workflow is not None
    assert workflow.workflow_id == WORKFLOW_ID
    assert workflow.state == WorkflowState.CLOSED
    assert starter.calls == []


def test_clear_with_terminal_behavior_skips_already_terminal_workflow() -> None:
    lead_repository = FakeLeadRepository((_paused_search_lead(),))
    workflow = LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture:test",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=WorkflowState.COMPLETED,
        last_transition_at=NOW,
        state_version=2,
        created_at=NOW,
        updated_at=NOW,
    )
    workflow_repository = FakeLeadWorkflowRepository((workflow,))

    result = asyncio.run(
        update_lead_paused_search(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            active=False,
            selected_track_key=None,
            reason_note=None,
            reengagement_not_before=None,
            reengagement_window_label=None,
            lead_repository=lead_repository,
            paused_search_history_repository=FakeLeadPausedSearchHistoryRepository(()),
            lead_workflow_repository=workflow_repository,
            paused_search_track_repository=_track_repository(),
            paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
            terminal_behavior=PausedSearchTerminalBehavior.CLOSE_AUTOMATION,
            terminal_reason=None,
            workflow_transition_repository=FakeWorkflowTransitionRepository(()),
            external_event_repository=FakeExternalEventRepository(),
            now=NOW,
        )
    )

    assert result.status == LeadPausedSearchActionStatus.CLEARED
    assert result.workflow_terminalized is False
    saved = asyncio.run(workflow_repository.get_latest_for_lead(WORKSPACE_ID, LEAD_ID))
    assert saved is not None
    assert saved.state == WorkflowState.COMPLETED


def test_terminal_behavior_rejected_when_setting_profile() -> None:
    result = asyncio.run(
        update_lead_paused_search(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            active=True,
            selected_track_key="waiting-rates",
            reason_note=None,
            reengagement_not_before=None,
            reengagement_window_label=None,
            lead_repository=FakeLeadRepository((_lead(),)),
            paused_search_history_repository=FakeLeadPausedSearchHistoryRepository(()),
            lead_workflow_repository=FakeLeadWorkflowRepository((_workflow(),)),
            paused_search_track_repository=_track_repository(),
            paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
            terminal_behavior=PausedSearchTerminalBehavior.COMPLETE_KEEP_PAUSED,
            terminal_reason=None,
            workflow_transition_repository=FakeWorkflowTransitionRepository(()),
            external_event_repository=FakeExternalEventRepository(),
            now=NOW,
        )
    )

    assert result.status == LeadPausedSearchActionStatus.REJECTED
    assert result.reasons == (LeadPausedSearchActionReasonCode.TERMINAL_BEHAVIOR_INVALID,)


def test_terminal_behavior_rejected_without_required_repositories() -> None:
    result = asyncio.run(
        update_lead_paused_search(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            active=False,
            selected_track_key=None,
            reason_note=None,
            reengagement_not_before=None,
            reengagement_window_label=None,
            lead_repository=FakeLeadRepository((_paused_search_lead(),)),
            paused_search_history_repository=FakeLeadPausedSearchHistoryRepository(()),
            lead_workflow_repository=FakeLeadWorkflowRepository((_workflow(),)),
            paused_search_track_repository=_track_repository(),
            paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
            terminal_behavior=PausedSearchTerminalBehavior.COMPLETE_KEEP_PAUSED,
            terminal_reason=None,
            now=NOW,
        )
    )

    assert result.status == LeadPausedSearchActionStatus.REJECTED
    assert result.reasons == (LeadPausedSearchActionReasonCode.TERMINAL_BEHAVIOR_INVALID,)


def test_unchanged_clear_still_terminalizes_active_workflow() -> None:
    lead_repository = FakeLeadRepository((_lead(),))
    workflow_repository = FakeLeadWorkflowRepository((_workflow(),))
    transition_repository = FakeWorkflowTransitionRepository(())

    result = asyncio.run(
        update_lead_paused_search(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            active=False,
            selected_track_key=None,
            reason_note=None,
            reengagement_not_before=None,
            reengagement_window_label=None,
            lead_repository=lead_repository,
            paused_search_history_repository=FakeLeadPausedSearchHistoryRepository(()),
            lead_workflow_repository=workflow_repository,
            paused_search_track_repository=_track_repository(),
            paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
            terminal_behavior=PausedSearchTerminalBehavior.CLOSE_AUTOMATION,
            terminal_reason="Stop automation",
            workflow_transition_repository=transition_repository,
            external_event_repository=FakeExternalEventRepository(),
            now=NOW,
        )
    )

    assert result.status == LeadPausedSearchActionStatus.UNCHANGED
    assert result.workflow_terminalized is True
    assert result.workflow_state == WorkflowState.CLOSED
    workflow = asyncio.run(workflow_repository.get_latest_for_lead(WORKSPACE_ID, LEAD_ID))
    assert workflow is not None
    assert workflow.state == WorkflowState.CLOSED


class FakeExternalEventRepository:
    async def save(self, event: ExternalEvent) -> ExternalEvent:
        return event

    async def get_by_provider_event_id(
        self,
        workspace_id: UUID,
        provider: str,
        provider_event_id: str,
    ) -> ExternalEvent | None:
        return None


def _lead(*, owner_id: UUID = USER_ID) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        assigned_agent_user_id=owner_id,
        effective_owner_user_id=owner_id,
        mapped_custom_fields={"display_name": "Jordan Seller"},
    )


def _paused_search_lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        assigned_agent_user_id=USER_ID,
        effective_owner_user_id=USER_ID,
        mapped_custom_fields={"display_name": "Jordan Seller"},
        paused_search_active=True,
        paused_search_track_key="waiting-rates",
        paused_search_track_version_id=TRACK_VERSION_ID,
        pause_reason_note="Waiting until rates improve.",
        reengagement_not_before=NOW,
        reengagement_window_label="spring check-in",
        paused_search_source=PausedSearchSource.OPERATOR,
        paused_search_recorded_at=NOW,
        paused_search_recorded_by_user_id=USER_ID,
        paused_search_last_confirmed_at=NOW,
    )


def _workflow(*, paused_search_track_version_id: UUID | None = None) -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture:test",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=WorkflowState.PAUSED,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
        paused_search_track_version_id=paused_search_track_version_id,
    )


def _enrollment() -> CampaignEnrollment:
    return CampaignEnrollment(
        campaign_enrollment_id=ENROLLMENT_ID,
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=UUID("00000000-0000-0000-0000-000000000009"),
        lead_id=LEAD_ID,
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        status=CampaignEnrollmentStatus.ACTIVE,
        eligible_at=NOW,
        enrolled_at=NOW,
        started_at=NOW,
        ended_at=None,
        created_by_user_id=USER_ID,
        reason_codes=("manual",),
        created_at=NOW,
        updated_at=NOW,
    )


def _track_repository() -> FakePausedSearchTrackAdminRepository:
    from app.domain.campaigns import (
        PausedSearchFallbackTimingPolicy,
        PausedSearchTrack,
        PausedSearchTrackStatus,
        PausedSearchTrackVersion,
    )
    from app.domain.campaigns.execution import CampaignVersionStatus
    from app.domain.compliance.contactability import ContactChannel

    return FakePausedSearchTrackAdminRepository(
        tracks=(
            PausedSearchTrack(
                track_id=TRACK_ID,
                workspace_id=WORKSPACE_ID,
                track_key="waiting-rates",
                display_name="Waiting for rates",
                status=PausedSearchTrackStatus.ACTIVE,
                active_version_id=TRACK_VERSION_ID,
                created_by_user_id=USER_ID,
                created_at=NOW,
                updated_at=NOW,
            ),
        ),
        versions=(
            PausedSearchTrackVersion(
                track_version_id=TRACK_VERSION_ID,
                workspace_id=WORKSPACE_ID,
                track_id=TRACK_ID,
                version_number=1,
                status=CampaignVersionStatus.PUBLISHED,
                selection_guidance="Select when a paused lead needs periodic follow-up.",
                enabled=True,
                allowed_channels=(ContactChannel.EMAIL,),
                fallback_timing_policy=(
                    PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE
                ),
                maintenance_interval_days=90,
                reactivation_window_days=45,
                max_total_touches=2,
                created_by_user_id=USER_ID,
                created_at=NOW,
                published_at=NOW,
            ),
        ),
    )


def _actor(role: WorkspaceMembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=USER_ID,
        user_status=UserStatus.ACTIVE,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=UUID("00000000-0000-0000-0000-000000000020"),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
        active_role=role,
    )
