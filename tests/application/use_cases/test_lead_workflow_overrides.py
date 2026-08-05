from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.use_cases.lead_workflow_overrides import (
    PausedSearchWorkflowOverrideReasonCode,
    PausedSearchWorkflowOverrideStatus,
    migrate_paused_search_track_version,
    override_paused_search_timing,
    skip_paused_search_next_touch,
)
from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchReasonMapping,
    PausedSearchTrack,
    PausedSearchTrackAssignmentSource,
    PausedSearchTrackFamily,
    PausedSearchTrackStatus,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.compliance.contactability import ContactChannel
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    Workspace,
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
from app.domain.workflows import (
    LeadWorkflow,
    LeadWorkflowOverrideAction,
    TemporalSignalName,
    WorkflowState,
)
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakePausedSearchOccurrenceRepository,
    FakeWorkspaceRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeTemporalSignalOutboxRepository,
)
from tests.application.use_cases._lead_read_fakes import (
    FakeLeadPausedSearchHistoryRepository,
    FakeLeadWorkflowOverrideAuditLogRepository,
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
TARGET_TRACK_VERSION_ID = UUID("00000000-0000-0000-0000-000000000009")
STEP_ONE_ID = UUID("00000000-0000-0000-0000-000000000010")
STEP_TWO_ID = UUID("00000000-0000-0000-0000-000000000011")


async def test_override_paused_search_timing_updates_profile_and_appends_audit() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    await workflow_repository.save(_workflow(state=WorkflowState.ACTIVE_NURTURE))
    audit_repository = FakeLeadWorkflowOverrideAuditLogRepository(())
    outbox = FakeTemporalSignalOutboxRepository()

    result = await override_paused_search_timing(
        actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        reengagement_not_before=NOW + timedelta(days=120),
        reengagement_window_label="check back in 120 days",
        reason="Agent asked to push the timing back.",
        lead_repository=FakeLeadRepository(_lead()),
        paused_search_history_repository=FakeLeadPausedSearchHistoryRepository(()),
        lead_workflow_repository=workflow_repository,
        lead_workflow_override_audit_repository=audit_repository,
        paused_search_track_repository=_track_repository(),
        paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
        temporal_signal_outbox_repository=outbox,
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        now=NOW,
    )

    assert result.status == PausedSearchWorkflowOverrideStatus.UPDATED
    assert result.profile is not None
    assert result.profile.reengagement_window_label == "check back in 120 days"
    assert result.audit_log is not None
    assert result.audit_log.action == LeadWorkflowOverrideAction.TIMING_CHANGED
    assert result.workflow is not None
    assert result.workflow.next_action_at is not None
    assert len(outbox.entries) == 1


async def test_migrate_paused_search_track_version_rejects_assigned_agent() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    await workflow_repository.save(_workflow())

    result = await migrate_paused_search_track_version(
        actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        target_track_version_id=TARGET_TRACK_VERSION_ID,
        reason="Move to newer paused-search track.",
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        lead_workflow_override_audit_repository=FakeLeadWorkflowOverrideAuditLogRepository(()),
        paused_search_track_repository=_track_repository(),
        paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
        temporal_signal_outbox_repository=FakeTemporalSignalOutboxRepository(),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        now=NOW,
    )

    assert result.status == PausedSearchWorkflowOverrideStatus.REJECTED
    assert result.reasons == (PausedSearchWorkflowOverrideReasonCode.PERMISSION_DENIED,)


async def test_migrate_paused_search_track_version_rejects_unpublished_target() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    await workflow_repository.save(_workflow())
    unpublished_track = replace(
        _target_track_version(),
        status=CampaignVersionStatus.DRAFT,
    )

    result = await migrate_paused_search_track_version(
        actor=_actor(WorkspaceMembershipRole.MANAGER),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        target_track_version_id=TARGET_TRACK_VERSION_ID,
        reason="Move to newer paused-search track.",
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        lead_workflow_override_audit_repository=FakeLeadWorkflowOverrideAuditLogRepository(()),
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(
            tracks=(_track(),),
            versions=(_track_version(), unpublished_track),
            steps=_steps(),
        ),
        paused_search_track_assignment_repository=FakePausedSearchTrackAssignmentRepository(),
        temporal_signal_outbox_repository=FakeTemporalSignalOutboxRepository(),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        now=NOW,
    )

    assert result.status == PausedSearchWorkflowOverrideStatus.INVALID
    assert result.reasons == (PausedSearchWorkflowOverrideReasonCode.TRACK_VERSION_NOT_PUBLISHED,)


async def test_migrate_paused_search_track_version_updates_pinned_version_and_reschedules() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    await workflow_repository.save(_workflow())
    audit_repository = FakeLeadWorkflowOverrideAuditLogRepository(())
    outbox = FakeTemporalSignalOutboxRepository()
    occurrence_repository = FakePausedSearchOccurrenceRepository()
    assignment_repository = FakePausedSearchTrackAssignmentRepository()

    result = await migrate_paused_search_track_version(
        actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        target_track_version_id=TARGET_TRACK_VERSION_ID,
        reason="Apply the published replacement track.",
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        lead_workflow_override_audit_repository=audit_repository,
        paused_search_track_repository=_track_repository(),
        paused_search_track_assignment_repository=assignment_repository,
        temporal_signal_outbox_repository=outbox,
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        paused_search_occurrence_repository=occurrence_repository,
        now=NOW,
    )

    assert result.status == PausedSearchWorkflowOverrideStatus.UPDATED
    assert result.workflow is not None
    assert result.workflow.paused_search_track_version_id == TARGET_TRACK_VERSION_ID
    active_assignment = await assignment_repository.get_active_for_lead(WORKSPACE_ID, LEAD_ID)
    assert active_assignment is not None
    assert active_assignment.track_version_id == TARGET_TRACK_VERSION_ID
    assert active_assignment.source is PausedSearchTrackAssignmentSource.ADMIN_MIGRATION
    assert result.audit_log is not None
    assert result.audit_log.action == LeadWorkflowOverrideAction.TRACK_VERSION_MIGRATED
    entry = next(iter(outbox.entries.values()))
    assert entry.signal_name == TemporalSignalName.RESCHEDULE_REQUESTED


async def test_skip_paused_search_next_touch_advances_to_following_step() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    await workflow_repository.save(
        _workflow(
            state=WorkflowState.ACTIVE_NURTURE,
            paused_search_track_step_id=STEP_ONE_ID,
        )
    )
    audit_repository = FakeLeadWorkflowOverrideAuditLogRepository(())
    outbox = FakeTemporalSignalOutboxRepository()
    occurrence_repository = FakePausedSearchOccurrenceRepository()

    result = await skip_paused_search_next_touch(
        actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        reason="Skip the first maintenance touch.",
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        lead_workflow_override_audit_repository=audit_repository,
        paused_search_track_repository=_track_repository(),
        temporal_signal_outbox_repository=outbox,
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        paused_search_occurrence_repository=occurrence_repository,
        now=NOW,
    )

    assert result.status == PausedSearchWorkflowOverrideStatus.UPDATED
    assert result.skipped_step_id == STEP_ONE_ID
    assert result.workflow is not None
    assert result.workflow.paused_search_track_step_id == STEP_TWO_ID
    assert result.audit_log is not None
    assert result.audit_log.action == LeadWorkflowOverrideAction.NEXT_TOUCH_SKIPPED
    entry = next(iter(outbox.entries.values()))
    assert entry.signal_name == TemporalSignalName.RESCHEDULE_REQUESTED


async def test_skip_paused_search_next_touch_rejects_waiting_for_response_workflow() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    await workflow_repository.save(
        _workflow(
            state=WorkflowState.WAITING_FOR_RESPONSE,
            paused_search_track_step_id=STEP_ONE_ID,
        )
    )

    result = await skip_paused_search_next_touch(
        actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        reason="Do not send the currently queued step.",
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        lead_workflow_override_audit_repository=FakeLeadWorkflowOverrideAuditLogRepository(()),
        paused_search_track_repository=_track_repository(),
        temporal_signal_outbox_repository=FakeTemporalSignalOutboxRepository(),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        now=NOW,
    )

    assert result.status == PausedSearchWorkflowOverrideStatus.INVALID
    assert result.reasons == (
        PausedSearchWorkflowOverrideReasonCode.WORKFLOW_STATE_NOT_OVERRIDABLE,
    )


async def test_sent_occurrence_preserves_existing_logical_touch_count() -> None:
    occurrence_repository = FakePausedSearchOccurrenceRepository(
        replace(_occurrence(), logical_touch_count=3)
    )
    assert occurrence_repository.occurrence is not None

    saved = await occurrence_repository.update_status(
        workspace_id=WORKSPACE_ID,
        occurrence_id=occurrence_repository.occurrence.occurrence_id,
        status="sent",
        now=NOW,
    )

    assert saved is not None
    assert saved.logical_touch_count == 4


def _lead() -> CanonicalLeadRecord:
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
        reengagement_not_before=NOW + timedelta(days=90),
        reengagement_window_label="spring check-in",
        paused_search_source=PausedSearchSource.OPERATOR,
        paused_search_recorded_at=NOW,
        paused_search_recorded_by_user_id=USER_ID,
        paused_search_last_confirmed_at=NOW,
    )


def _workflow(
    *,
    state: WorkflowState = WorkflowState.PAUSED,
    paused_search_track_version_id: UUID = TRACK_VERSION_ID,
    paused_search_track_step_id: UUID | None = None,
) -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture:test-override",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=state,
        last_transition_at=NOW,
        state_version=1,
        paused_search_track_version_id=paused_search_track_version_id,
        paused_search_track_step_id=paused_search_track_step_id,
        created_at=NOW,
        updated_at=NOW,
    )


def _track_version() -> PausedSearchTrackVersion:
    return PausedSearchTrackVersion(
        track_version_id=TRACK_VERSION_ID,
        workspace_id=WORKSPACE_ID,
        track_id=TRACK_ID,
        version_number=1,
        status=CampaignVersionStatus.PUBLISHED,
        track_family=PausedSearchTrackFamily.MAINTENANCE,
        enabled=True,
        allowed_channels=(ContactChannel.SMS,),
        default_for_reason_codes=(PausedSearchReasonCode.WAITING_FOR_RATES,),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL,
        maintenance_interval_days=60,
        reactivation_window_days=30,
        max_total_touches=4,
        requires_review_before_publish=False,
        created_by_user_id=USER_ID,
        created_at=NOW,
        published_at=NOW,
    )


def _target_track_version() -> PausedSearchTrackVersion:
    return replace(
        _track_version(),
        track_version_id=TARGET_TRACK_VERSION_ID,
        version_number=2,
    )


def _steps() -> tuple[PausedSearchTrackStep, ...]:
    return (
        PausedSearchTrackStep(
            step_id=STEP_ONE_ID,
            workspace_id=WORKSPACE_ID,
            track_version_id=TRACK_VERSION_ID,
            step_order=1,
            phase=PausedSearchTrackStepPhase.MAINTENANCE,
            channel=ContactChannel.SMS,
            delay_hours=0,
            message_goal="check in",
            template_key="m1",
            max_attempts=1,
            review_required=False,
            created_at=NOW,
        ),
        PausedSearchTrackStep(
            step_id=STEP_TWO_ID,
            workspace_id=WORKSPACE_ID,
            track_version_id=TRACK_VERSION_ID,
            step_order=2,
            phase=PausedSearchTrackStepPhase.MAINTENANCE,
            channel=ContactChannel.SMS,
            delay_hours=24,
            message_goal="follow up",
            template_key="m2",
            max_attempts=1,
            review_required=False,
            created_at=NOW,
        ),
        replace(
            PausedSearchTrackStep(
                step_id=UUID("00000000-0000-0000-0000-000000000012"),
                workspace_id=WORKSPACE_ID,
                track_version_id=TARGET_TRACK_VERSION_ID,
                step_order=1,
                phase=PausedSearchTrackStepPhase.MAINTENANCE,
                channel=ContactChannel.SMS,
                delay_hours=0,
                message_goal="check in",
                template_key="m1-target",
                max_attempts=1,
                review_required=False,
                created_at=NOW,
            )
        ),
    )


def _track_repository() -> FakePausedSearchTrackAdminRepository:
    return FakePausedSearchTrackAdminRepository(
        tracks=(_track(),),
        mappings=(
            PausedSearchReasonMapping(
                mapping_id=UUID("00000000-0000-0000-0000-000000000013"),
                workspace_id=WORKSPACE_ID,
                reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
                track_id=TRACK_ID,
                track_version_id=TRACK_VERSION_ID,
                created_by_user_id=USER_ID,
                created_at=NOW,
            ),
        ),
        versions=(_track_version(), _target_track_version()),
        steps=_steps(),
    )


def _track() -> PausedSearchTrack:
    return PausedSearchTrack(
        track_id=TRACK_ID,
        workspace_id=WORKSPACE_ID,
        track_key="waiting-rates",
        display_name="Waiting for rates",
        status=PausedSearchTrackStatus.ACTIVE,
        active_version_id=TARGET_TRACK_VERSION_ID,
        created_by_user_id=USER_ID,
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


def _occurrence() -> RecurringOccurrence:
    return RecurringOccurrence(
        occurrence_id=UUID("00000000-0000-0000-0000-000000000021"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        track_version_id=TRACK_VERSION_ID,
        step_id=STEP_ONE_ID,
        phase=PausedSearchTrackStepPhase.MAINTENANCE,
        occurrence_number=1,
        scheduled_for=NOW,
        due_at=NOW,
        status=RecurringOccurrenceStatus.PLANNED,
        idempotency_key="test-occurrence",
        created_at=NOW,
    )


def _actor(role: WorkspaceMembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=USER_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=UUID("00000000-0000-0000-0000-000000000020"),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )
