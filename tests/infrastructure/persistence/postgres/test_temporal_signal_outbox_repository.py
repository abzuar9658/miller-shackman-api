import asyncio
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.use_cases.schedule_next_paused_search_action import (
    PausedSearchNextActionScheduleResult,
    schedule_next_paused_search_action,
)
from app.domain.campaigns import (
    PausedSearchTrackStepPhase,
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.outbound_message import ProviderDeliveryStatus
from app.domain.workflows import (
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    TemporalSignalOutboxStatus,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import (
    CampaignModel,
    CampaignVersionModel,
    LeadModel,
    PausedSearchTrackModel,
    PausedSearchTrackStepModel,
    PausedSearchTrackVersionModel,
    RecurringOccurrenceModel,
    UserModel,
    WorkspaceModel,
)
from app.infrastructure.persistence.postgres.paused_search_occurrence_repository import (
    PostgresPausedSearchOccurrenceRepository,
)
from app.infrastructure.persistence.postgres.paused_search_track_repository import (
    PostgresPausedSearchTrackAdminRepository,
)
from app.infrastructure.persistence.postgres.temporal_signal_outbox_repository import (
    PostgresTemporalSignalOutboxRepository,
)
from app.infrastructure.persistence.postgres.workflow_models import (
    CampaignEnrollmentModel,
    LeadWorkflowModel,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
)
from tests.infrastructure.persistence.postgres._harness import (
    PostgresHarnessDatabase,
)

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("21111111-1111-1111-1111-111111111111")
USER_ID = UUID("21111111-1111-1111-1111-111111111112")
LEAD_ID = UUID("21111111-1111-1111-1111-111111111113")
CAMPAIGN_ID = UUID("21111111-1111-1111-1111-111111111114")
CAMPAIGN_VERSION_ID = UUID("21111111-1111-1111-1111-111111111115")
ENROLLMENT_ID = UUID("21111111-1111-1111-1111-111111111116")
WORKFLOW_ID = UUID("21111111-1111-1111-1111-111111111117")
SIGNAL_ID = UUID("21111111-1111-1111-1111-111111111118")
EXTERNAL_EVENT_ID = UUID("21111111-1111-1111-1111-111111111119")
TRACK_ID = UUID("21111111-1111-1111-1111-111111111120")
TRACK_VERSION_ID = UUID("21111111-1111-1111-1111-111111111121")
TRACK_STEP_ID = UUID("21111111-1111-1111-1111-111111111122")
OCCURRENCE_ID = UUID("21111111-1111-1111-1111-111111111123")


@pytest.mark.asyncio
async def test_temporal_signal_outbox_repository_appends_claims_and_marks_sent(
    postgres_session: AsyncSession,
) -> None:
    await _create_workflow_graph(postgres_session)
    repository = PostgresTemporalSignalOutboxRepository(postgres_session)

    appended = await repository.append(_entry())
    claimed = await repository.claim_available_batch(
        now=NOW,
        limit=10,
        lease_duration=timedelta(minutes=5),
        max_attempts=3,
    )

    assert appended.status == TemporalSignalOutboxStatus.PENDING
    assert len(claimed) == 1
    assert claimed[0].status == TemporalSignalOutboxStatus.DISPATCHING
    assert claimed[0].attempt_count == 1
    assert claimed[0].claimed_until == NOW + timedelta(minutes=5)

    sent = await repository.mark_sent(claimed[0].temporal_signal_id, now=NOW)
    assert sent.status == TemporalSignalOutboxStatus.SENT
    assert sent.sent_at == NOW


@pytest.mark.asyncio
async def test_paused_search_occurrence_repository_is_idempotent(
    postgres_session: AsyncSession,
) -> None:
    await _create_workflow_graph(postgres_session)
    postgres_session.add(
        PausedSearchTrackModel(
            track_id=TRACK_ID,
            workspace_id=WORKSPACE_ID,
            track_key="maintenance",
            display_name="Maintenance",
            status="draft",
            active_version_id=None,
            created_by_user_id=USER_ID,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()
    postgres_session.add(
        PausedSearchTrackVersionModel(
            track_version_id=TRACK_VERSION_ID,
            workspace_id=WORKSPACE_ID,
            track_id=TRACK_ID,
            version_number=1,
            status="published",
            track_family="maintenance",
            enabled=True,
            allowed_channels=["email"],
            default_for_reason_codes=[],
            fallback_timing_policy="use_maintenance_interval",
            maintenance_interval_days=30,
            reactivation_window_days=30,
            max_total_touches=5,
            requires_review_before_publish=False,
            max_duration_days=365,
            terminal_behavior="complete_keep_paused",
            created_by_user_id=USER_ID,
            published_at=NOW,
            created_at=NOW,
        )
    )
    await postgres_session.commit()
    postgres_session.add(
        PausedSearchTrackStepModel(
            step_id=TRACK_STEP_ID,
            workspace_id=WORKSPACE_ID,
            track_version_id=TRACK_VERSION_ID,
            step_order=1,
            phase="maintenance",
            channel="email",
            delay_hours=0,
            message_goal="Check in",
            template_key="maintenance-1",
            max_attempts=1,
            review_required=False,
            interval_days=30,
            max_occurrences=3,
            created_at=NOW,
        )
    )
    await postgres_session.commit()

    repository = PostgresPausedSearchOccurrenceRepository(postgres_session)
    first = await repository.create_or_get(_occurrence())
    duplicate = await repository.create_or_get(_occurrence())
    latest = await repository.get_latest_for_step(
        WORKSPACE_ID,
        WORKFLOW_ID,
        TRACK_VERSION_ID,
        TRACK_STEP_ID,
    )

    assert duplicate.occurrence_id == first.occurrence_id == OCCURRENCE_ID
    assert latest == first

    sent = await repository.update_status(
        workspace_id=WORKSPACE_ID,
        occurrence_id=OCCURRENCE_ID,
        status=RecurringOccurrenceStatus.SENT.value,
        now=NOW,
        provider_message_id="provider-message-1",
        provider_delivery_status=ProviderDeliveryStatus.ACCEPTED,
        fallback_used=True,
    )
    assert sent is not None
    assert sent.status == RecurringOccurrenceStatus.SENT
    assert sent.logical_touch_count == 1
    assert sent.provider_message_id == "provider-message-1"
    assert sent.provider_delivery_status == ProviderDeliveryStatus.ACCEPTED
    assert sent.fallback_used is True

    linked = await repository.get_by_provider_message_id_for_update(
        WORKSPACE_ID,
        "provider-message-1",
    )
    assert linked == sent

    delivered = await repository.update_status(
        workspace_id=WORKSPACE_ID,
        occurrence_id=OCCURRENCE_ID,
        status=RecurringOccurrenceStatus.SENT.value,
        now=NOW + timedelta(minutes=1),
        provider_delivery_status=ProviderDeliveryStatus.DELIVERED,
    )
    assert delivered is not None
    assert delivered.logical_touch_count == 1
    assert delivered.provider_delivery_status == ProviderDeliveryStatus.DELIVERED
    assert delivered.fallback_used is True

    terminal_is_idempotent = await repository.update_status(
        workspace_id=WORKSPACE_ID,
        occurrence_id=OCCURRENCE_ID,
        status=RecurringOccurrenceStatus.FAILED.value,
        now=NOW + timedelta(minutes=2),
    )
    assert terminal_is_idempotent is not None
    assert terminal_is_idempotent.status == RecurringOccurrenceStatus.SENT


@pytest.mark.asyncio
async def test_concurrent_paused_search_occurrence_creation_is_idempotent(
    postgres_harness_database: PostgresHarnessDatabase,
) -> None:
    engine = create_async_engine(
        postgres_harness_database.async_url,
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as setup_session:
            await _create_workflow_graph(setup_session)
            setup_session.add(
                PausedSearchTrackModel(
                    track_id=TRACK_ID,
                    workspace_id=WORKSPACE_ID,
                    track_key="maintenance",
                    display_name="Maintenance",
                    status="draft",
                    active_version_id=None,
                    created_by_user_id=USER_ID,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await setup_session.commit()
            setup_session.add(
                PausedSearchTrackVersionModel(
                    track_version_id=TRACK_VERSION_ID,
                    workspace_id=WORKSPACE_ID,
                    track_id=TRACK_ID,
                    version_number=1,
                    status="published",
                    track_family="maintenance",
                    enabled=True,
                    allowed_channels=["email"],
                    default_for_reason_codes=[],
                    fallback_timing_policy="use_maintenance_interval",
                    maintenance_interval_days=30,
                    reactivation_window_days=30,
                    max_total_touches=5,
                    requires_review_before_publish=False,
                    max_duration_days=365,
                    terminal_behavior="complete_keep_paused",
                    created_by_user_id=USER_ID,
                    published_at=NOW,
                    created_at=NOW,
                )
            )
            await setup_session.commit()
            setup_session.add(
                PausedSearchTrackStepModel(
                    step_id=TRACK_STEP_ID,
                    workspace_id=WORKSPACE_ID,
                    track_version_id=TRACK_VERSION_ID,
                    step_order=1,
                    phase="maintenance",
                    channel="email",
                    delay_hours=0,
                    message_goal="Check in",
                    template_key="maintenance-1",
                    max_attempts=1,
                    review_required=False,
                    interval_days=30,
                    max_occurrences=3,
                    created_at=NOW,
                )
            )
            await setup_session.commit()

            await setup_session.execute(
                update(LeadModel)
                .where(LeadModel.lead_id == LEAD_ID)
                .values(
                    paused_search_active=True,
                    pause_reason_code="rented_temporarily",
                    paused_search_source="operator",
                    paused_search_recorded_at=NOW,
                    reengagement_not_before=NOW + timedelta(days=120),
                )
            )
            await setup_session.execute(
                update(LeadWorkflowModel)
                .where(LeadWorkflowModel.workflow_id == WORKFLOW_ID)
                .values(
                    state="active_nurture",
                    paused_search_track_version_id=TRACK_VERSION_ID,
                    paused_search_track_step_id=TRACK_STEP_ID,
                )
            )
            await setup_session.commit()

        occurrence = _occurrence()

        async def create_in_isolated_transaction() -> RecurringOccurrence:
            async with engine.begin() as connection:
                session = AsyncSession(bind=connection, expire_on_commit=False)
                try:
                    repository = PostgresPausedSearchOccurrenceRepository(session)
                    return await repository.create_or_get(occurrence)
                finally:
                    await session.close()

        saved = await asyncio.gather(
            create_in_isolated_transaction(),
            create_in_isolated_transaction(),
        )

        assert saved[0].occurrence_id == saved[1].occurrence_id
        async with engine.connect() as connection:
            result = await connection.execute(
                select(func.count())
                .select_from(RecurringOccurrenceModel)
                .where(RecurringOccurrenceModel.idempotency_key == occurrence.idempotency_key)
            )
            assert result.scalar_one() == 1

        async with engine.begin() as connection:
            await connection.execute(
                update(RecurringOccurrenceModel)
                .where(RecurringOccurrenceModel.occurrence_id == OCCURRENCE_ID)
                .values(status=RecurringOccurrenceStatus.SENT.value)
            )

        async def schedule_in_isolated_transaction() -> PausedSearchNextActionScheduleResult:
            async with engine.begin() as connection:
                session = AsyncSession(bind=connection, expire_on_commit=False)
                try:
                    return await schedule_next_paused_search_action(
                        workspace_id=WORKSPACE_ID,
                        lead_id=LEAD_ID,
                        lead_repository=PostgresLeadRepository(session),
                        paused_search_track_repository=PostgresPausedSearchTrackAdminRepository(
                            session
                        ),
                        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
                        occurrence_repository=PostgresPausedSearchOccurrenceRepository(session),
                        timezone="UTC",
                        now=NOW + timedelta(days=31),
                    )
                finally:
                    await session.close()

        scheduled = await asyncio.gather(
            schedule_in_isolated_transaction(),
            schedule_in_isolated_transaction(),
        )
        assert scheduled[0].occurrence is not None
        assert scheduled[0].occurrence == scheduled[1].occurrence
        assert scheduled[0].occurrence.occurrence_number == 2

        async with engine.connect() as connection:
            occurrence_count = await connection.execute(
                select(func.count())
                .select_from(RecurringOccurrenceModel)
                .where(
                    RecurringOccurrenceModel.workflow_id == WORKFLOW_ID,
                    RecurringOccurrenceModel.occurrence_number == 2,
                )
            )
            assert occurrence_count.scalar_one() == 1
            cursor = await connection.execute(
                select(
                    LeadWorkflowModel.paused_search_track_step_id,
                    LeadWorkflowModel.next_action_at,
                ).where(LeadWorkflowModel.workflow_id == WORKFLOW_ID)
            )
            cursor_step_id, cursor_next_action_at = cursor.one()
            assert cursor_step_id == TRACK_STEP_ID
            assert cursor_next_action_at == scheduled[0].next_action_at
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE TABLE users, workspaces CASCADE"))
        await engine.dispose()


@pytest.mark.asyncio
async def test_temporal_signal_outbox_repository_deduplicates_and_reclaims_failed_entries(
    postgres_session: AsyncSession,
) -> None:
    await _create_workflow_graph(postgres_session)
    repository = PostgresTemporalSignalOutboxRepository(postgres_session)

    first = await repository.append(_entry())
    duplicate = await repository.append(_entry())
    claimed = await repository.claim_available_batch(
        now=NOW,
        limit=10,
        lease_duration=timedelta(minutes=5),
        max_attempts=3,
    )
    failed = await repository.mark_failed(
        claimed[0].temporal_signal_id,
        error="temporal unavailable",
        available_at=NOW + timedelta(minutes=1),
        now=NOW,
    )

    not_ready = await repository.claim_available_batch(
        now=NOW + timedelta(seconds=30),
        limit=10,
        lease_duration=timedelta(minutes=5),
        max_attempts=3,
    )
    ready = await repository.claim_available_batch(
        now=NOW + timedelta(minutes=1),
        limit=10,
        lease_duration=timedelta(minutes=5),
        max_attempts=3,
    )

    assert duplicate.temporal_signal_id == first.temporal_signal_id
    assert failed.status == TemporalSignalOutboxStatus.FAILED
    assert failed.last_error == "temporal unavailable"
    assert not_ready == ()
    assert len(ready) == 1
    assert ready[0].attempt_count == 2


def _entry() -> TemporalSignalOutboxEntry:
    return TemporalSignalOutboxEntry(
        temporal_signal_id=SIGNAL_ID,
        workspace_id=WORKSPACE_ID,
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="workflow-123",
        signal_name=TemporalSignalName.INBOUND_PROCESSED,
        payload={
            "lead_id": str(LEAD_ID),
            "occurred_at": NOW.isoformat(),
            "external_event_id": str(EXTERNAL_EVENT_ID),
            "conversation_id": None,
            "inbound_message_id": None,
            "workflow_transition_id": None,
            "inbound_action": "human_handoff",
            "reason": "human_requested",
        },
        idempotency_key=f"inbound-processed:{EXTERNAL_EVENT_ID}",
        status=TemporalSignalOutboxStatus.PENDING,
        attempt_count=0,
        available_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _occurrence() -> RecurringOccurrence:
    return RecurringOccurrence(
        occurrence_id=OCCURRENCE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        track_version_id=TRACK_VERSION_ID,
        step_id=TRACK_STEP_ID,
        phase=PausedSearchTrackStepPhase.MAINTENANCE,
        occurrence_number=1,
        scheduled_for=NOW,
        due_at=NOW,
        status=RecurringOccurrenceStatus.PLANNED,
        idempotency_key="occurrence-1",
        created_at=NOW,
    )


async def _create_workflow_graph(postgres_session: AsyncSession) -> None:
    postgres_session.add(
        WorkspaceModel(
            workspace_id=WORKSPACE_ID,
            name="Test Workspace",
            status="active",
            default_timezone="UTC",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    postgres_session.add(
        UserModel(
            user_id=USER_ID,
            email="owner@example.com",
            email_normalized="owner@example.com",
            full_name="Owner",
            status="active",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    postgres_session.add(
        LeadModel(
            lead_id=LEAD_ID,
            workspace_id=WORKSPACE_ID,
            crm_provider="follow_up_boss",
            crm_lead_id="crm-123",
            source_payload_version="test:v1",
            facts_derived_at=NOW,
            assigned_agent_name_present=False,
            has_accountable_owner=True,
            lead_type="buyer",
            classification_reason="crm_type_buyer",
            lead_source="website",
            lead_stage="nurture",
            created_via="sync",
            tags=[],
            mapped_custom_fields={},
            primary_phone="+15555550123",
            primary_email="lead@example.com",
            has_email=True,
            has_phone=True,
            has_sms_capable_phone=True,
            email_count=1,
            phone_count=1,
            sms_permission_status="unknown",
            email_permission_status="unknown",
            sms_opted_out=False,
            email_unsubscribed=False,
            suppression_types=[],
            permission_evidence={},
            activity_reliability="reliable",
            latest_property_context_present=False,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()

    postgres_session.add(
        CampaignModel(
            campaign_id=CAMPAIGN_ID,
            workspace_id=WORKSPACE_ID,
            name="Dormant Reengagement",
            status="active",
            active_version_id=None,
            created_by_user_id=USER_ID,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()

    postgres_session.add(
        CampaignVersionModel(
            campaign_version_id=CAMPAIGN_VERSION_ID,
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            version_number=1,
            status="published",
            enabled_channels=["sms"],
            daily_start_cap=50,
            dormant_threshold_days=60,
            quiet_hours_start=time(10, 0),
            quiet_hours_end=time(17, 0),
            timezone="UTC",
            sms_compliance_required=True,
            preflight_digest_enabled=False,
            allow_assigned_agent_manual_enrollment=True,
            prompt_version="reply-classifier:v1",
            approved_model="openai/gpt-4o-mini",
            created_by_user_id=USER_ID,
            created_at=NOW,
        )
    )
    await postgres_session.commit()

    postgres_session.add(
        CampaignEnrollmentModel(
            campaign_enrollment_id=ENROLLMENT_ID,
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
            lead_id=LEAD_ID,
            source="manual",
            status="active",
            reason_codes=[],
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()

    postgres_session.add(
        LeadWorkflowModel(
            workflow_id=WORKFLOW_ID,
            temporal_workflow_id="workflow-123",
            workspace_id=WORKSPACE_ID,
            campaign_enrollment_id=ENROLLMENT_ID,
            campaign_id=CAMPAIGN_ID,
            lead_id=LEAD_ID,
            state="waiting_for_response",
            last_transition_at=NOW,
            state_version=3,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()
