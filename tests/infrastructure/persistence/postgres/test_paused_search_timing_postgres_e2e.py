from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.schedule_next_paused_search_action import (
    PausedSearchNextActionScheduleResult,
    PausedSearchScheduleStatus,
    schedule_next_paused_search_action,
)
from app.domain.campaigns import (
    CampaignEnrollmentSource,
    CampaignEnrollmentStatus,
    PausedSearchFallbackTimingPolicy,
    PausedSearchStepAction,
    PausedSearchTimingBasis,
    PausedSearchTimingReasonCode,
    PausedSearchTrack,
    PausedSearchTrackMode,
    PausedSearchTrackStatus,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.compliance.contactability import ContactChannel, ContactPermissionStatus
from app.domain.leads import (
    ActivityReliability,
    CanonicalLeadRecord,
    CRMProvider,
    LeadClassificationReason,
    LeadType,
    PausedSearchSource,
)
from app.domain.workflows import LeadWorkflow, WorkflowState
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import (
    CampaignModel,
    CampaignVersionModel,
    UserModel,
    WorkspaceModel,
)
from app.infrastructure.persistence.postgres.paused_search_occurrence_repository import (
    PostgresPausedSearchOccurrenceRepository,
)
from app.infrastructure.persistence.postgres.paused_search_track_repository import (
    PostgresPausedSearchTrackAdminRepository,
)
from app.infrastructure.persistence.postgres.workflow_models import (
    CampaignEnrollmentModel,
    WorkflowTransitionModel,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
USER_ID = UUID("22222222-2222-2222-2222-222222222222")
CAMPAIGN_ID = UUID("33333333-3333-3333-3333-333333333333")
CAMPAIGN_VERSION_ID = UUID("44444444-4444-4444-4444-444444444444")
ENROLLMENT_ID = UUID("55555555-5555-5555-5555-555555555555")
LEAD_ID = UUID("66666666-6666-6666-6666-666666666666")
WORKFLOW_ID = UUID("77777777-7777-7777-7777-777777777777")
TRACK_ID = UUID("88888888-8888-8888-8888-888888888888")
TRACK_VERSION_ID = UUID("99999999-9999-9999-9999-999999999999")
MAINTENANCE_STEP_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
REACTIVATION_STEP_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@dataclass(frozen=True)
class Scenario:
    lead_repository: PostgresLeadRepository
    workflow_repository: PostgresLeadWorkflowRepository
    track_repository: PostgresPausedSearchTrackAdminRepository
    occurrence_repository: PostgresPausedSearchOccurrenceRepository
    transition_repository: PostgresWorkflowTransitionRepository
    lead: CanonicalLeadRecord
    workflow: LeadWorkflow


@pytest.mark.asyncio
async def test_explicit_date_derives_three_maintenance_occurrences_before_reactivation(
    postgres_session: AsyncSession,
) -> None:
    scenario = await _seed(
        postgres_session, reengagement_not_before=NOW + timedelta(days=120)
    )

    first = await _schedule(scenario, NOW)
    assert first.occurrence is not None
    await _mark_sent(scenario, first.occurrence, NOW)
    second = await _schedule(scenario, NOW + timedelta(days=30))
    assert second.occurrence is not None
    assert second.occurrence.due_at == NOW + timedelta(days=30)
    await _mark_sent(scenario, second.occurrence, NOW + timedelta(days=30))
    third = await _schedule(scenario, NOW + timedelta(days=60))
    assert third.occurrence is not None
    assert third.occurrence.due_at == NOW + timedelta(days=60)
    await _mark_sent(scenario, third.occurrence, NOW + timedelta(days=60))

    switched = await _schedule(scenario, NOW + timedelta(days=60))

    assert switched.status is PausedSearchScheduleStatus.SCHEDULED
    assert switched.occurrence is None
    assert switched.phase is PausedSearchTrackStepPhase.REACTIVATION
    assert switched.step_id == REACTIVATION_STEP_ID
    assert switched.next_action_at == NOW + timedelta(days=90)
    assert len(
        await scenario.occurrence_repository.list_for_workspace(
            WORKSPACE_ID, lead_id=LEAD_ID
        )
    ) == 3


@pytest.mark.asyncio
async def test_missing_date_default_pause_duration_uses_fallback_boundary(
    postgres_session: AsyncSession,
) -> None:
    scenario = await _seed(
        postgres_session,
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_DEFAULT_PAUSE_DURATION,
        default_pause_duration_days=90,
        reactivation_window_days=30,
        reengagement_not_before=None,
    )

    first = await _schedule(scenario, NOW)
    assert first.occurrence is not None
    await _mark_sent(scenario, first.occurrence, NOW)
    second = await _schedule(scenario, NOW + timedelta(days=30))
    assert second.occurrence is not None
    await _mark_sent(scenario, second.occurrence, NOW + timedelta(days=30))
    switched = await _schedule(scenario, NOW + timedelta(days=45))

    assert switched.phase is PausedSearchTrackStepPhase.REACTIVATION
    assert switched.next_action_at == NOW + timedelta(days=60)
    await _assert_no_reactivation_date(scenario)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "policy",
    [
        PausedSearchFallbackTimingPolicy.HOLD_FOR_REVIEW,
        PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE,
    ],
)
async def test_missing_date_hold_policies_create_no_occurrence(
    postgres_session: AsyncSession,
    policy: PausedSearchFallbackTimingPolicy,
) -> None:
    scenario = await _seed(
        postgres_session,
        fallback_timing_policy=policy,
        reengagement_not_before=None,
    )

    result = await _schedule(scenario, NOW)

    assert result.status is PausedSearchScheduleStatus.HOLD
    assert result.reason_code is PausedSearchTimingReasonCode.HOLD_FOR_REVIEW
    assert result.occurrence is None
    assert await scenario.occurrence_repository.list_for_workspace(
        WORKSPACE_ID, lead_id=LEAD_ID
    ) == ()


@pytest.mark.asyncio
async def test_missing_date_maintenance_interval_is_bounded_by_touch_cap_and_duration(
    postgres_session: AsyncSession,
) -> None:
    scenario = await _seed(
        postgres_session,
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL,
        reengagement_not_before=None,
        max_total_touches=1,
        max_duration_days=45,
        maintenance_delay_hours=24 * 30,
    )

    first = await _schedule(scenario, NOW)
    assert first.occurrence is not None
    await _mark_sent(scenario, first.occurrence, NOW)
    await scenario.workflow_repository.save(
        replace(scenario.workflow, logical_touch_count=1, updated_at=NOW)
    )
    capped = await _schedule(scenario, NOW + timedelta(days=31))

    assert capped.status is PausedSearchScheduleStatus.TERMINAL
    assert capped.reason_code is PausedSearchTimingReasonCode.TOUCH_LIMIT_REACHED
    assert capped.workflow is not None
    assert capped.workflow.state is WorkflowState.COMPLETED
    await _assert_no_reactivation_date(scenario)
    transitions = (
        await postgres_session.execute(
            select(WorkflowTransitionModel).where(
                WorkflowTransitionModel.workflow_id == WORKFLOW_ID
            )
        )
    ).scalars().all()
    assert len(transitions) == 1


@pytest.mark.asyncio
async def test_missing_date_duration_expiry_does_not_create_reactivation_date(
    postgres_session: AsyncSession,
) -> None:
    scenario = await _seed(
        postgres_session,
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL,
        reengagement_not_before=None,
        max_total_touches=5,
        max_duration_days=45,
        maintenance_delay_hours=24 * 30,
    )

    first = await _schedule(scenario, NOW)
    assert first.occurrence is not None
    await _mark_sent(scenario, first.occurrence, NOW)
    expired = await _schedule(scenario, NOW + timedelta(days=100))

    assert expired.status is PausedSearchScheduleStatus.TERMINAL
    assert expired.reason_code is PausedSearchTimingReasonCode.DURATION_EXPIRED
    assert len(
        await scenario.occurrence_repository.list_for_workspace(
            WORKSPACE_ID, lead_id=LEAD_ID
        )
    ) == 1
    await _assert_no_reactivation_date(scenario)


@pytest.mark.asyncio
async def test_duplicate_scheduling_is_persistently_idempotent(
    postgres_session: AsyncSession,
) -> None:
    scenario = await _seed(postgres_session)

    first = await _schedule(scenario, NOW)
    duplicate = await _schedule(scenario, NOW)

    assert first.occurrence is not None
    assert duplicate.occurrence == first.occurrence
    assert len(
        await scenario.occurrence_repository.list_for_workspace(
            WORKSPACE_ID, lead_id=LEAD_ID
        )
    ) == 1


@pytest.mark.asyncio
async def test_next_real_scheduler_call_observes_changed_reactivation_date(
    postgres_session: AsyncSession,
) -> None:
    scenario = await _seed(postgres_session, reengagement_not_before=NOW + timedelta(days=120))

    first = await _schedule(scenario, NOW)
    assert first.occurrence is not None
    await _mark_sent(scenario, first.occurrence, NOW)
    changed_lead = replace(
        scenario.lead,
        reengagement_not_before=NOW + timedelta(days=60),
        paused_search_recorded_at=NOW + timedelta(minutes=1),
    )
    await scenario.lead_repository.upsert(changed_lead)
    observed = await _schedule(scenario, NOW + timedelta(days=1))

    assert observed.phase is PausedSearchTrackStepPhase.REACTIVATION
    assert observed.step_id == REACTIVATION_STEP_ID
    assert observed.occurrence is None


async def _schedule(
    scenario: Scenario, now: datetime
) -> PausedSearchNextActionScheduleResult:
    return await schedule_next_paused_search_action(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=scenario.lead_repository,
        paused_search_track_repository=scenario.track_repository,
        lead_workflow_repository=scenario.workflow_repository,
        occurrence_repository=scenario.occurrence_repository,
        workflow_transition_repository=scenario.transition_repository,
        timezone="UTC",
        now=now,
    )


async def _mark_sent(
    scenario: Scenario, occurrence: RecurringOccurrence, now: datetime
) -> None:
    saved = await scenario.occurrence_repository.update_status(
        workspace_id=WORKSPACE_ID,
        occurrence_id=occurrence.occurrence_id,
        status=RecurringOccurrenceStatus.SENT.value,
        now=now,
    )
    assert saved is not None


async def _assert_no_reactivation_date(scenario: Scenario) -> None:
    lead = await scenario.lead_repository.get_by_id(WORKSPACE_ID, LEAD_ID)
    assert lead is not None
    assert lead.reengagement_not_before is None


async def _seed(
    session: AsyncSession,
    *,
    fallback_timing_policy: PausedSearchFallbackTimingPolicy = (
        PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL
    ),
    reengagement_not_before: datetime | None = NOW + timedelta(days=90),
    default_pause_duration_days: int = 60,
    reactivation_window_days: int = 30,
    max_total_touches: int = 5,
    max_duration_days: int = 365,
    maintenance_delay_hours: int = 0,
) -> Scenario:
    session.add(
        WorkspaceModel(
            workspace_id=WORKSPACE_ID,
            name="Timing Workspace",
            status="active",
            default_timezone="UTC",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()
    session.add(
        UserModel(
            user_id=USER_ID,
            email="timing@example.com",
            email_normalized="timing@example.com",
            status="active",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()
    session.add(
        CampaignModel(
            campaign_id=CAMPAIGN_ID,
            workspace_id=WORKSPACE_ID,
            name="Timing Campaign",
            status=CampaignStatus.ACTIVE.value,
            active_version_id=None,
            created_by_user_id=USER_ID,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()
    session.add(
        CampaignVersionModel(
            campaign_version_id=CAMPAIGN_VERSION_ID,
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            version_number=1,
            status=CampaignVersionStatus.PUBLISHED.value,
            enabled_channels=[ContactChannel.EMAIL.value],
            daily_start_cap=50,
            dormant_threshold_days=60,
            quiet_hours_start=time(10),
            quiet_hours_end=time(17),
            timezone="UTC",
            preflight_digest_enabled=False,
            prompt_version="test-v1",
            approved_model="test-model",
            prompt_text="test",
            sms_prompt_text="test",
            sms_template="test",
            email_prompt_text="test",
            email_template="test",
            email_subject_template="test",
            enabled_extraction_fields=[],
            created_by_user_id=USER_ID,
            published_at=NOW,
            created_at=NOW,
        )
    )
    await session.flush()
    campaign = await session.get(CampaignModel, CAMPAIGN_ID)
    assert campaign is not None
    campaign.active_version_id = CAMPAIGN_VERSION_ID
    await session.flush()
    lead = _lead(reengagement_not_before=reengagement_not_before)
    lead_repository = PostgresLeadRepository(session)
    await lead_repository.upsert(lead)
    session.add(
        CampaignEnrollmentModel(
            campaign_enrollment_id=ENROLLMENT_ID,
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
            lead_id=LEAD_ID,
            source=CampaignEnrollmentSource.MANUAL_ADMIN.value,
            status=CampaignEnrollmentStatus.ACTIVE.value,
            enrolled_at=NOW,
            created_by_user_id=USER_ID,
            reason_codes=[CampaignEnrollmentSource.MANUAL_ADMIN.value],
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()
    track_repository = PostgresPausedSearchTrackAdminRepository(session)
    await track_repository.save_track(_track())
    await track_repository.save_version(
        _version(
            fallback_timing_policy=fallback_timing_policy,
            default_pause_duration_days=default_pause_duration_days,
            reactivation_window_days=reactivation_window_days,
            max_total_touches=max_total_touches,
            max_duration_days=max_duration_days,
        )
    )
    steps = [
        _step(
            PausedSearchTrackStepPhase.MAINTENANCE,
            MAINTENANCE_STEP_ID,
            1,
            maintenance_delay_hours,
        )
    ]
    steps.append(
        _step(PausedSearchTrackStepPhase.REACTIVATION, REACTIVATION_STEP_ID, 2, 0)
    )
    await track_repository.replace_steps(WORKSPACE_ID, TRACK_VERSION_ID, tuple(steps))
    workflow = LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="paused-search-timing-e2e",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=WorkflowState.ACTIVE_NURTURE,
        paused_search_track_version_id=TRACK_VERSION_ID,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    workflow_repository = PostgresLeadWorkflowRepository(session)
    await workflow_repository.save(workflow)
    return Scenario(
        lead_repository=lead_repository,
        workflow_repository=workflow_repository,
        track_repository=track_repository,
        occurrence_repository=PostgresPausedSearchOccurrenceRepository(session),
        transition_repository=PostgresWorkflowTransitionRepository(session),
        lead=lead,
        workflow=workflow,
    )


def _lead(*, reengagement_not_before: datetime | None) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="timing-lead",
        facts_derived_at=NOW,
        source_payload_version="test-v1",
        lead_type=LeadType.BUYER,
        classification_reason=LeadClassificationReason.CRM_TYPE_BUYER,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        activity_reliability=ActivityReliability.RELIABLE,
        paused_search_active=True,
        paused_search_track_key="timing-track",
        paused_search_track_version_id=TRACK_VERSION_ID,
        reengagement_not_before=reengagement_not_before,
        paused_search_source=PausedSearchSource.OPERATOR,
        paused_search_recorded_at=NOW,
    )


def _track() -> PausedSearchTrack:
    return PausedSearchTrack(
        track_id=TRACK_ID,
        workspace_id=WORKSPACE_ID,
        track_key="timing-track",
        display_name="Timing Track",
        status=PausedSearchTrackStatus.ACTIVE,
        active_version_id=TRACK_VERSION_ID,
        created_by_user_id=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _version(
    *,
    fallback_timing_policy: PausedSearchFallbackTimingPolicy,
    default_pause_duration_days: int,
    reactivation_window_days: int,
    max_total_touches: int,
    max_duration_days: int,
) -> PausedSearchTrackVersion:
    return PausedSearchTrackVersion(
        track_version_id=TRACK_VERSION_ID,
        workspace_id=WORKSPACE_ID,
        track_id=TRACK_ID,
        version_number=1,
        status=CampaignVersionStatus.PUBLISHED,
        selection_guidance="Timing test",
        enabled=True,
        allowed_channels=(ContactChannel.EMAIL,),
        fallback_timing_policy=fallback_timing_policy,
        maintenance_interval_days=30,
        reactivation_window_days=reactivation_window_days,
        max_total_touches=max_total_touches,
        max_duration_days=max_duration_days,
        default_pause_duration_days=default_pause_duration_days,
        track_mode=PausedSearchTrackMode.CUSTOM_BOUNDED,
        created_by_user_id=USER_ID,
        created_at=NOW,
        published_at=NOW,
    )


def _step(
    phase: PausedSearchTrackStepPhase,
    step_id: UUID,
    step_order: int,
    delay_hours: int,
) -> PausedSearchTrackStep:
    return PausedSearchTrackStep(
        step_id=step_id,
        workspace_id=WORKSPACE_ID,
        track_version_id=TRACK_VERSION_ID,
        step_order=step_order,
        phase=phase,
        channel=ContactChannel.EMAIL,
        delay_hours=delay_hours,
        message_goal="Timing test",
        template_key="timing-test",
        max_attempts=1,
        review_required=False,
        timing_basis=PausedSearchTimingBasis.CUSTOMER_REENGAGEMENT_DATE,
        interval_days=30 if phase is PausedSearchTrackStepPhase.MAINTENANCE else None,
        max_occurrences=1,
        action=PausedSearchStepAction.SEND,
        created_at=NOW,
    )