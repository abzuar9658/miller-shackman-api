from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.application.use_cases.preview_paused_search_track import (
    PausedSearchTrackPreviewStatus,
    preview_paused_search_track_version,
)
from app.domain.campaigns import (
    CampaignVersionStatus,
    PausedSearchChannelSequence,
    PausedSearchFallbackTimingPolicy,
    PausedSearchInterimContactPolicy,
    PausedSearchReplyPolicy,
    PausedSearchStepAction,
    PausedSearchTimingBasis,
    PausedSearchTrack,
    PausedSearchTrackMode,
    PausedSearchTrackStatus,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
)
from app.domain.compliance.contactability import ContactChannel, ContactPermissionStatus
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
    LeadPausedSearchProfile,
    LeadType,
    PausedSearchSource,
)
from app.domain.workflows import LeadWorkflow, WorkflowState
from tests.application.use_cases.paused_search_time_machine import PausedSearchTimeMachine

NOW = datetime(2026, 7, 1, 15, 0, tzinfo=UTC)
TIMEZONE = "America/Chicago"
WORKSPACE_ID = UUID("50000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("50000000-0000-0000-0000-000000000002")
TRACK_ID = UUID("50000000-0000-0000-0000-000000000003")
VERSION_ID = UUID("50000000-0000-0000-0000-000000000004")
WORKFLOW_ID = UUID("50000000-0000-0000-0000-000000000005")
MAINTENANCE_ID = UUID("50000000-0000-0000-0000-000000000006")
REACTIVATION_EMAIL_ID = UUID("50000000-0000-0000-0000-000000000007")
REACTIVATION_SMS_ID = UUID("50000000-0000-0000-0000-000000000008")
USER_ID = UUID("50000000-0000-0000-0000-000000000009")


@pytest.mark.asyncio
async def test_time_machine_full_lifecycle_matches_preview_and_preserves_sequence() -> None:
    version = _version()
    steps = _steps()
    preview = await preview_paused_search_track_version(
        actor=_actor(),
        track=_track(),
        version=version,
        steps=steps,
        profile=replace(
            _lead_profile(),
            reengagement_not_before=NOW + timedelta(days=90),
        ),
        workflow=_workflow(),
        timezone=TIMEZONE,
        now=NOW,
    )
    machine = _machine(version=version, steps=steps, reengagement_days=90)

    await machine.run_until_quiescent()
    snapshot = machine.snapshot()
    scheduled_preview = tuple(item for item in preview.occurrences if item.plan.next_action_at)

    assert preview.status is PausedSearchTrackPreviewStatus.READY
    assert snapshot.sent_channels == ("email", "email", "email", "sms")
    assert snapshot.occurrence_statuses == ("sent", "sent", "sent", "sent")
    assert snapshot.occurrence_times == tuple(
        item.plan.next_action_at for item in scheduled_preview
    )
    assert snapshot.workflow.state is WorkflowState.WAITING_FOR_RESPONSE
    assert snapshot.workflow.logical_touch_count == version.max_total_touches
    assert snapshot.transition_count >= len(snapshot.sent_channels)


@pytest.mark.asyncio
async def test_time_machine_does_not_cross_reactivation_boundary_early() -> None:
    version = replace(
        _version(),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.HOLD_FOR_REVIEW,
    )
    steps = (_step(REACTIVATION_EMAIL_ID, phase=PausedSearchTrackStepPhase.REACTIVATION),)
    machine = _machine(version=version, steps=steps)
    machine.now = NOW + timedelta(days=29)

    result = await machine.schedule()

    assert result.status.value == "hold"
    assert result.skip_reason == "no remaining step in maintenance phase"
    assert machine.email_provider.messages == []
    machine.now = NOW + timedelta(days=31)
    resumed = await machine.schedule()
    assert resumed.status.value == "scheduled"
    assert resumed.cadence_step_id == REACTIVATION_EMAIL_ID


@pytest.mark.asyncio
async def test_time_machine_blocks_maintenance_without_explicit_permission() -> None:
    version = replace(
        _version(),
        track_mode=PausedSearchTrackMode.PERMISSION_BASED_INTERIM_CONTACT,
        interim_contact_policy=PausedSearchInterimContactPolicy.NOT_ALLOWED,
    )
    machine = _machine(version=version, steps=(_step(MAINTENANCE_ID),))

    result = await machine.schedule()

    assert result.status.value == "hold"
    assert result.skip_reason == "Maintenance outreach is not permitted for this track."
    assert machine.email_provider.messages == []


@pytest.mark.asyncio
async def test_time_machine_allows_maintenance_when_published_track_allows_it() -> None:
    version = replace(
        _version(),
        interim_contact_policy=PausedSearchInterimContactPolicy.ALLOWED_BY_PUBLISHED_TRACK,
    )
    machine = _machine(
        version=version,
        steps=(_step(MAINTENANCE_ID, interval_days=30, max_occurrences=2),),
    )

    result = await machine.schedule()

    assert result.status.value == "scheduled"
    assert result.cadence_step_id == MAINTENANCE_ID


@pytest.mark.asyncio
async def test_time_machine_reminder_and_skip_actions_never_call_providers() -> None:
    reminder_machine = _machine(
        version=_version(),
        steps=(_step(MAINTENANCE_ID, action=PausedSearchStepAction.REMINDER),),
    )
    reminder_schedule = await reminder_machine.schedule()
    await reminder_machine.execute(reminder_schedule)
    reminder_snapshot = reminder_machine.snapshot()
    assert reminder_snapshot.reminder_count == 1
    assert reminder_snapshot.occurrence_statuses == ("reminder_created",)
    assert reminder_machine.email_provider.messages == []

    skip_machine = _machine(
        version=_version(),
        steps=(_step(MAINTENANCE_ID, action=PausedSearchStepAction.SKIP),),
    )
    skip_schedule = await skip_machine.schedule()
    await skip_machine.execute(skip_schedule)
    assert skip_machine.snapshot().occurrence_statuses == ("skipped",)
    assert skip_machine.email_provider.messages == []


@pytest.mark.asyncio
async def test_time_machine_caps_repeated_occurrences_and_schedule_is_idempotent() -> None:
    version = replace(_version(), max_total_touches=2)
    machine = _machine(version=version, steps=_steps(), reengagement_days=90)

    first = await machine.schedule()
    duplicate = await machine.schedule()
    assert duplicate.occurrence_id == first.occurrence_id
    await machine.execute(first)
    machine.now = NOW + timedelta(days=30)
    second = await machine.schedule()
    await machine.execute(second)
    terminal = await machine.schedule()

    assert len(machine.occurrence_repository.occurrences) == 2
    assert terminal.status.value == "terminal"
    assert terminal.skip_reason == "track logical-touch limit has been reached"
    assert machine.snapshot().workflow.logical_touch_count == 2


@pytest.mark.asyncio
async def test_time_machine_provider_failure_is_recorded_without_counting_a_touch() -> None:
    machine = _machine(
        version=_version(),
        steps=(_step(MAINTENANCE_ID),),
        email_result=RuntimeError("provider unavailable"),
    )
    scheduled = await machine.schedule()
    result = await machine.execute(scheduled)
    snapshot = machine.snapshot()

    assert result.status.value == "failed"
    assert snapshot.workflow.state is WorkflowState.PAUSED
    assert snapshot.workflow.logical_touch_count == 0
    assert snapshot.occurrence_statuses == ("failed",)


def _machine(
    *,
    version: PausedSearchTrackVersion,
    steps: tuple[PausedSearchTrackStep, ...],
    email_result: str | Exception = "time-machine-email",
    reengagement_days: int = 60,
) -> PausedSearchTimeMachine:
    lead = replace(_lead(), reengagement_not_before=NOW + timedelta(days=reengagement_days))
    return PausedSearchTimeMachine(
        now=NOW,
        timezone=TIMEZONE,
        lead=lead,
        workflow=_workflow(),
        track_version=version,
        steps=steps,
        email_result=email_result,
    )


def _version() -> PausedSearchTrackVersion:
    return PausedSearchTrackVersion(
        track_version_id=VERSION_ID,
        workspace_id=WORKSPACE_ID,
        track_id=TRACK_ID,
        version_number=1,
        status=CampaignVersionStatus.PUBLISHED,
        selection_guidance="Use for bounded paused-search follow-up.",
        enabled=True,
        allowed_channels=(ContactChannel.EMAIL, ContactChannel.SMS),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL,
        maintenance_interval_days=30,
        reactivation_window_days=30,
        max_total_touches=4,
        created_by_user_id=USER_ID,
        created_at=NOW,
        published_at=NOW,
        max_duration_days=365,
        track_mode=PausedSearchTrackMode.PERMISSION_BASED_INTERIM_CONTACT,
        interim_contact_policy=PausedSearchInterimContactPolicy.REQUIRES_EXPLICIT_LEAD_PERMISSION,
        reply_policy=PausedSearchReplyPolicy.RESTART_AFTER_DELAY,
        channel_sequence=PausedSearchChannelSequence.SEQUENTIAL,
        max_cycles=2,
    )


def _steps() -> tuple[PausedSearchTrackStep, ...]:
    return (
        _step(MAINTENANCE_ID, interval_days=30, max_occurrences=2),
        _step(REACTIVATION_EMAIL_ID, phase=PausedSearchTrackStepPhase.REACTIVATION),
        _step(
            REACTIVATION_SMS_ID,
            phase=PausedSearchTrackStepPhase.REACTIVATION,
            channel=ContactChannel.SMS,
            delay_hours=24,
        ),
    )


def _step(
    step_id: UUID,
    *,
    phase: PausedSearchTrackStepPhase = PausedSearchTrackStepPhase.MAINTENANCE,
    channel: ContactChannel = ContactChannel.EMAIL,
    delay_hours: int = 0,
    interval_days: int | None = None,
    max_occurrences: int = 1,
    action: PausedSearchStepAction = PausedSearchStepAction.SEND,
) -> PausedSearchTrackStep:
    return PausedSearchTrackStep(
        step_id=step_id,
        workspace_id=WORKSPACE_ID,
        track_version_id=VERSION_ID,
        step_order={MAINTENANCE_ID: 1, REACTIVATION_EMAIL_ID: 2, REACTIVATION_SMS_ID: 3}[step_id],
        phase=phase,
        channel=channel,
        delay_hours=delay_hours,
        message_goal="Check whether the lead's plans have changed.",
        template_key=f"time-machine-{step_id}",
        max_attempts=1,
        review_required=False,
        created_at=NOW,
        timing_basis=(
            PausedSearchTimingBasis.PREVIOUS_OCCURRENCE
            if phase is PausedSearchTrackStepPhase.MAINTENANCE
            else PausedSearchTimingBasis.CUSTOMER_REENGAGEMENT_DATE
        ),
        interval_days=interval_days,
        max_occurrences=max_occurrences,
        action=action,
    )


def _track() -> PausedSearchTrack:
    return PausedSearchTrack(
        track_id=TRACK_ID,
        workspace_id=WORKSPACE_ID,
        track_key="waiting-for-rates",
        display_name="Waiting for rates",
        status=PausedSearchTrackStatus.ACTIVE,
        active_version_id=VERSION_ID,
        created_by_user_id=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="time-machine-lead",
        facts_derived_at=NOW,
        source_payload_version="time-machine:v1",
        lead_type=LeadType.BUYER,
        primary_email="lead@example.com",
        primary_phone="+15551234567",
        has_email=True,
        has_phone=True,
        has_sms_capable_phone=True,
        email_count=1,
        phone_count=1,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        sms_permission_status=ContactPermissionStatus.CONFIRMED,
        paused_search_active=True,
        paused_search_track_key="waiting-for-rates",
        paused_search_track_version_id=VERSION_ID,
        reengagement_not_before=NOW + timedelta(days=60),
        paused_search_source=PausedSearchSource.OPERATOR,
        paused_search_recorded_at=NOW,
    )


def _lead_profile() -> LeadPausedSearchProfile:
    return LeadPausedSearchProfile(
        paused_search_active=True,
        paused_search_track_key="waiting-for-rates",
        paused_search_track_version_id=VERSION_ID,
        reengagement_not_before=NOW + timedelta(days=60),
    )


def _workflow() -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="time-machine-workflow",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=UUID("50000000-0000-0000-0000-000000000010"),
        campaign_id=UUID("50000000-0000-0000-0000-000000000011"),
        lead_id=LEAD_ID,
        state=WorkflowState.ACTIVE_NURTURE,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
        paused_search_track_version_id=VERSION_ID,
    )


def _actor() -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=USER_ID,
        user_status=UserStatus.ACTIVE,
        active_role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=UUID("50000000-0000-0000-0000-000000000012"),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )