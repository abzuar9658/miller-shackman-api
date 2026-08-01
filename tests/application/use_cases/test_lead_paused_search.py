import asyncio
from datetime import UTC, datetime
from uuid import UUID

from app.application.use_cases.lead_paused_search import (
    LeadPausedSearchActionReasonCode,
    LeadPausedSearchActionStatus,
    update_lead_paused_search,
)
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
    PausedSearchReasonCode,
    PausedSearchSource,
)
from app.domain.workflows import LeadWorkflow, TemporalSignalName, WorkflowState
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeTemporalSignalOutboxRepository,
)
from tests.application.use_cases._lead_read_fakes import (
    FakeLeadPausedSearchHistoryRepository,
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
)
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
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
            reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
            reason_note="Waiting until rates improve.",
            reengagement_not_before=NOW,
            reengagement_window_label="spring check-in",
            lead_repository=lead_repository,
            paused_search_history_repository=history_repository,
            lead_workflow_repository=workflow_repository,
            paused_search_track_repository=_track_repository(),
            temporal_signal_outbox_repository=signal_outbox_repository,
            now=NOW,
        )
    )

    assert result.status == LeadPausedSearchActionStatus.UPDATED
    assert result.profile is not None
    assert result.profile.pause_reason_code == PausedSearchReasonCode.WAITING_FOR_RATES
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

    result = asyncio.run(
        update_lead_paused_search(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            active=True,
            reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
            reason_note="Waiting until rates improve.",
            reengagement_not_before=NOW,
            reengagement_window_label="spring check-in",
            lead_repository=lead_repository,
            paused_search_history_repository=history_repository,
            lead_workflow_repository=workflow_repository,
            paused_search_track_repository=_track_repository(),
            now=NOW,
        )
    )

    assert result.status == LeadPausedSearchActionStatus.UNCHANGED
    assert result.history_entry is None


def test_update_lead_paused_search_clears_existing_profile() -> None:
    lead_repository = FakeLeadRepository((_paused_search_lead(),))
    history_repository = FakeLeadPausedSearchHistoryRepository(())
    workflow_repository = FakeLeadWorkflowRepository(
        (_workflow(paused_search_track_version_id=TRACK_VERSION_ID),)
    )
    signal_outbox_repository = FakeTemporalSignalOutboxRepository()

    result = asyncio.run(
        update_lead_paused_search(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            active=False,
            reason_code=None,
            reason_note=None,
            reengagement_not_before=None,
            reengagement_window_label=None,
            lead_repository=lead_repository,
            paused_search_history_repository=history_repository,
            lead_workflow_repository=workflow_repository,
            paused_search_track_repository=_track_repository(),
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
    signal_entry = next(iter(signal_outbox_repository.entries.values()))
    assert signal_entry.signal_name == TemporalSignalName.RESCHEDULE_REQUESTED


def test_assigned_agent_cannot_edit_unowned_paused_search_profile() -> None:
    result = asyncio.run(
        update_lead_paused_search(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            active=True,
            reason_code=PausedSearchReasonCode.TIMING_NOT_RIGHT,
            reason_note=None,
            reengagement_not_before=None,
            reengagement_window_label=None,
            lead_repository=FakeLeadRepository(
                (_lead(owner_id=UUID("00000000-0000-0000-0000-000000000099")),)
            ),
            paused_search_history_repository=FakeLeadPausedSearchHistoryRepository(()),
            lead_workflow_repository=FakeLeadWorkflowRepository((_workflow(),)),
            paused_search_track_repository=_track_repository(),
            now=NOW,
        )
    )

    assert result.status == LeadPausedSearchActionStatus.REJECTED
    assert result.reasons == (LeadPausedSearchActionReasonCode.PERMISSION_DENIED,)


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
        pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
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


def _track_repository() -> FakePausedSearchTrackAdminRepository:
    from app.domain.campaigns import (
        PausedSearchFallbackTimingPolicy,
        PausedSearchReasonMapping,
        PausedSearchTrackFamily,
        PausedSearchTrackVersion,
    )
    from app.domain.campaigns.execution import CampaignVersionStatus
    from app.domain.compliance.contactability import ContactChannel

    return FakePausedSearchTrackAdminRepository(
        mappings=(
            PausedSearchReasonMapping(
                mapping_id=UUID("00000000-0000-0000-0000-000000000009"),
                workspace_id=WORKSPACE_ID,
                reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
                track_id=TRACK_ID,
                track_version_id=TRACK_VERSION_ID,
                created_by_user_id=USER_ID,
                created_at=NOW,
            ),
        ),
        versions=(
            PausedSearchTrackVersion(
                track_version_id=TRACK_VERSION_ID,
                workspace_id=WORKSPACE_ID,
                track_id=TRACK_ID,
                version_number=1,
                status=CampaignVersionStatus.PUBLISHED,
                track_family=PausedSearchTrackFamily.MAINTENANCE,
                enabled=True,
                allowed_channels=(ContactChannel.EMAIL,),
                default_for_reason_codes=(PausedSearchReasonCode.WAITING_FOR_RATES,),
                fallback_timing_policy=(
                    PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE
                ),
                maintenance_interval_days=90,
                reactivation_window_days=45,
                max_total_touches=2,
                requires_review_before_publish=False,
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
