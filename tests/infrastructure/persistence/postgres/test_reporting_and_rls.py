from datetime import UTC, datetime, time
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import (
    clear_postgres_rls_context,
    enable_postgres_service_access,
    service_access_commit,
    service_access_rollback,
    set_postgres_workspace_context,
)
from app.infrastructure.persistence.postgres.models import (
    CampaignAdminAuditLogModel,
    CampaignModel,
    CampaignVersionModel,
    CRMSyncJobModel,
    ExternalEventModel,
    LeadModel,
    OutboundMessageModel,
    OutboxEventModel,
    PausedSearchTrackModel,
    PausedSearchTrackStepModel,
    PausedSearchTrackVersionModel,
    RecurringOccurrenceModel,
    UserModel,
    WorkspaceModel,
)
from app.infrastructure.persistence.postgres.reporting_repository import PostgresReportingRepository
from app.infrastructure.persistence.postgres.workflow_models import (
    CampaignEnrollmentModel,
    LeadWorkflowModel,
)
from tests.infrastructure.persistence.postgres._harness import PostgresHarnessDatabase

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_WORKSPACE_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("33333333-3333-3333-3333-333333333333")
CAMPAIGN_ID = UUID("44444444-4444-4444-4444-444444444444")
VERSION_ID = UUID("55555555-5555-5555-5555-555555555555")
LEAD_ID = UUID("66666666-6666-6666-6666-666666666666")
ENROLLMENT_ID = UUID("77777777-7777-7777-7777-777777777777")
WORKFLOW_ID = UUID("88888888-8888-8888-8888-888888888888")
MESSAGE_ID = UUID("99999999-9999-9999-9999-999999999999")
TRACK_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TRACK_VERSION_ID = UUID("abababab-abab-abab-abab-abababababab")
STEP_ID = UUID("acacacac-acac-acac-acac-acacacacacac")
AUDIT_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
SYNC_JOB_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
EXTERNAL_EVENT_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
OUTBOX_EVENT_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")


@pytest.mark.asyncio
async def test_reporting_repository_builds_workspace_and_campaign_summaries(
    postgres_session: AsyncSession,
) -> None:
    await _seed_reporting_fixture(postgres_session)
    await set_postgres_workspace_context(postgres_session, str(WORKSPACE_ID))

    repository = PostgresReportingRepository(postgres_session)
    workspace_report = await repository.get_workspace_operations_summary(WORKSPACE_ID)
    campaign_report = await repository.get_campaign_operations_summary(WORKSPACE_ID, CAMPAIGN_ID)
    audit_logs = await repository.list_campaign_audit_logs(WORKSPACE_ID, CAMPAIGN_ID)

    assert workspace_report.active_campaigns == 1
    assert workspace_report.workflow_counts.waiting_for_response == 1
    assert workspace_report.message_counts.sent == 1
    assert workspace_report.message_counts.delivered == 1
    assert workspace_report.handoff_counts.notified == 0
    assert workspace_report.pending_external_events == 1
    assert workspace_report.failed_outbox_events == 1
    assert workspace_report.last_successful_sync_at == NOW
    assert workspace_report.paused_search_occurrence_health.due == 1
    assert workspace_report.paused_search_occurrence_health.held == 1
    assert workspace_report.paused_search_occurrence_health.review_pending == 1
    assert workspace_report.paused_search_occurrence_health.expired == 1
    assert workspace_report.paused_search_occurrence_health.failed == 1
    assert workspace_report.paused_search_occurrence_health.uncertain == 1
    assert workspace_report.paused_search_occurrence_health.terminal == 2
    assert workspace_report.paused_search_occurrence_health.fallback == 1

    assert campaign_report is not None
    assert campaign_report.campaign_name == "Dormant Buyers"
    assert campaign_report.enrollment_counts.active == 1
    assert campaign_report.latest_audit_at == NOW
    assert len(audit_logs) == 1
    assert audit_logs[0].action.value == "campaign_version_published"


@pytest.mark.asyncio
async def test_workspace_rls_requires_workspace_context_or_service_access(
    postgres_session: AsyncSession,
) -> None:
    await _seed_reporting_fixture(postgres_session)
    await _enable_rls_test_role(postgres_session)

    await clear_postgres_rls_context(postgres_session)
    hidden_count = await postgres_session.scalar(
        select(func.count())
        .select_from(CampaignModel)
        .where(CampaignModel.workspace_id == WORKSPACE_ID)
    )

    await set_postgres_workspace_context(postgres_session, str(WORKSPACE_ID))
    visible_count = await postgres_session.scalar(
        select(func.count())
        .select_from(CampaignModel)
        .where(CampaignModel.workspace_id == WORKSPACE_ID)
    )

    await set_postgres_workspace_context(postgres_session, str(OTHER_WORKSPACE_ID))
    wrong_workspace_count = await postgres_session.scalar(
        select(func.count())
        .select_from(CampaignModel)
        .where(CampaignModel.workspace_id == WORKSPACE_ID)
    )

    await enable_postgres_service_access(postgres_session)
    service_access_count = await postgres_session.scalar(
        select(func.count())
        .select_from(CampaignModel)
        .where(CampaignModel.workspace_id == WORKSPACE_ID)
    )

    assert int(hidden_count or 0) == 0
    assert int(visible_count or 0) == 1
    assert int(wrong_workspace_count or 0) == 0
    assert int(service_access_count or 0) == 1


@pytest.mark.asyncio
async def test_service_access_commit_and_rollback_re_arm_guc(
    postgres_harness_database: PostgresHarnessDatabase,
) -> None:
    engine = create_async_engine(
        postgres_harness_database.async_url,
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    try:
        async with AsyncSession(bind=engine, expire_on_commit=False) as session:
            await enable_postgres_service_access(session)
            # A bare commit ends the transaction and resets transaction-local GUCs.
            await session.commit()
            assert await _service_access_setting(session) != "on"

            await enable_postgres_service_access(session)
            await service_access_commit(session)()
            assert await _service_access_setting(session) == "on"

            await service_access_rollback(session)()
            assert await _service_access_setting(session) == "on"
    finally:
        await engine.dispose()


async def _service_access_setting(session: AsyncSession) -> str | None:
    value = await session.scalar(text("select current_setting('app.service_access', true)"))
    return None if value is None else str(value)


async def _enable_rls_test_role(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rls_tester') THEN
                    CREATE ROLE app_rls_tester;
                END IF;
            END
            $$;
            """
        )
    )
    await session.execute(text("GRANT USAGE ON SCHEMA public TO app_rls_tester"))
    await session.execute(text("GRANT SELECT ON campaigns TO app_rls_tester"))
    await session.execute(text("SET LOCAL ROLE app_rls_tester"))


async def _seed_reporting_fixture(session: AsyncSession) -> None:
    if await session.get(WorkspaceModel, WORKSPACE_ID) is not None:
        return

    session.add_all(
        [
            WorkspaceModel(
                workspace_id=WORKSPACE_ID,
                name="Reporting Workspace",
                status="active",
                default_timezone="UTC",
                created_at=NOW,
                updated_at=NOW,
            ),
            WorkspaceModel(
                workspace_id=OTHER_WORKSPACE_ID,
                name="Other Workspace",
                status="active",
                default_timezone="UTC",
                created_at=NOW,
                updated_at=NOW,
            ),
            UserModel(
                user_id=USER_ID,
                email="reporting@example.com",
                email_normalized="reporting@example.com",
                full_name="Reporting Admin",
                status="active",
                email_verified_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            ),
        ]
    )
    await session.flush()

    session.add_all(
        [
            LeadModel(
                lead_id=LEAD_ID,
                workspace_id=WORKSPACE_ID,
                crm_provider="follow_up_boss",
                crm_lead_id="crm-123",
                source_payload_version="test:v1",
                source_updated_at=NOW,
                facts_derived_at=NOW,
                assigned_agent_crm_id="agent-1",
                assigned_agent_name_present=True,
                has_accountable_owner=True,
                ownership_last_changed_at=NOW,
                lead_type="buyer",
                classification_reason="test_fixture",
                crm_type_raw="lead",
                lead_source="website",
                lead_stage="active",
                created_via="import",
                tags=[],
                mapped_custom_fields={},
                primary_email="lead@example.com",
                primary_phone="+15555550123",
                has_email=True,
                email_count=1,
                has_phone=True,
                has_sms_capable_phone=True,
                phone_count=1,
                sms_permission_status="subscribed",
                email_permission_status="subscribed",
                sms_opted_out=False,
                email_unsubscribed=False,
                do_not_contact=False,
                last_agent_activity_at=None,
                suppression_types=[],
                permission_evidence={},
                crm_created_at=NOW,
                crm_updated_at=NOW,
                last_activity_at=NOW,
                last_meaningful_communication_at=NOW,
                contacted_count=0,
                activity_reliability="reliable",
                latest_property_context_present=False,
                created_at=NOW,
                updated_at=NOW,
            ),
            CampaignModel(
                campaign_id=CAMPAIGN_ID,
                workspace_id=WORKSPACE_ID,
                name="Dormant Buyers",
                status="active",
                active_version_id=None,
                created_by_user_id=USER_ID,
                created_at=NOW,
                updated_at=NOW,
            ),
            CampaignVersionModel(
                campaign_version_id=VERSION_ID,
                workspace_id=WORKSPACE_ID,
                campaign_id=CAMPAIGN_ID,
                version_number=1,
                status="published",
                enabled_channels=["email"],
                daily_start_cap=50,
                dormant_threshold_days=60,
                quiet_hours_start=time(10, 0),
                quiet_hours_end=time(17, 0),
                timezone="UTC",
                preflight_digest_enabled=True,
                prompt_version="v1",
                approved_model="openai/gpt-4o-mini",
                created_by_user_id=USER_ID,
                published_at=NOW,
                created_at=NOW,
            ),
            CampaignEnrollmentModel(
                campaign_enrollment_id=ENROLLMENT_ID,
                workspace_id=WORKSPACE_ID,
                campaign_id=CAMPAIGN_ID,
                campaign_version_id=VERSION_ID,
                lead_id=LEAD_ID,
                source="manual_admin",
                status="active",
                eligible_at=NOW,
                enrolled_at=NOW,
                started_at=NOW,
                ended_at=None,
                created_by_user_id=USER_ID,
                reason_codes=["test"],
                created_at=NOW,
                updated_at=NOW,
            ),
            PausedSearchTrackModel(
                track_id=TRACK_ID,
                workspace_id=WORKSPACE_ID,
                track_key="maintenance",
                display_name="Maintenance",
                status="published",
                active_version_id=TRACK_VERSION_ID,
                created_by_user_id=USER_ID,
                created_at=NOW,
                updated_at=NOW,
            ),
            PausedSearchTrackVersionModel(
                track_version_id=TRACK_VERSION_ID,
                workspace_id=WORKSPACE_ID,
                track_id=TRACK_ID,
                version_number=1,
                status="published",
                selection_guidance="Select when a paused lead needs periodic follow-up.",
                enabled=True,
                allowed_channels=["email"],
                fallback_timing_policy="use_maintenance_interval",
                maintenance_interval_days=30,
                reactivation_window_days=30,
                max_total_touches=5,
                max_duration_days=365,
                terminal_behavior="complete_keep_paused",
                created_by_user_id=USER_ID,
                published_at=NOW,
                created_at=NOW,
            ),
            LeadWorkflowModel(
                workflow_id=WORKFLOW_ID,
                temporal_workflow_id="workflow-1",
                workspace_id=WORKSPACE_ID,
                campaign_enrollment_id=ENROLLMENT_ID,
                campaign_id=CAMPAIGN_ID,
                lead_id=LEAD_ID,
                state="waiting_for_response",
                current_step_id=None,
                next_action_at=NOW,
                last_transition_at=NOW,
                pause_reason=None,
                resume_reason=None,
                state_version=1,
                created_at=NOW,
                updated_at=NOW,
            ),
            OutboundMessageModel(
                message_id=MESSAGE_ID,
                workspace_id=WORKSPACE_ID,
                lead_id=LEAD_ID,
                campaign_id=CAMPAIGN_ID,
                cadence_step_id="step-1",
                channel="email",
                status="sent",
                idempotency_key="message-1",
                body="Hello",
                subject="Hi",
                html_body=None,
                scheduled_for=NOW,
                planned_at=NOW,
                sent_at=NOW,
                message_version=1,
                provider_send_status="accepted",
                provider_name="sendgrid",
                provider_message_id="provider-1",
                provider_delivery_status="delivered",
                provider_status_updated_at=NOW,
                delivered_at=NOW,
                failure_reason=None,
                draft_prompt_version="v1",
                draft_model="openai/gpt-4o-mini",
                draft_latency_ms=10,
                draft_usage_tokens=20,
                draft_confidence=0.9,
                draft_personalization_notes=[],
                draft_safety_flags=[],
                created_at=NOW,
                updated_at=NOW,
            ),
        ]
    )
    await session.flush()

    session.add(
        PausedSearchTrackStepModel(
            step_id=STEP_ID,
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
            max_occurrences=10,
            created_at=NOW,
        )
    )
    session.add_all(
        [
            RecurringOccurrenceModel(
                occurrence_id=UUID(f"{index + 10:032x}"),
                workspace_id=WORKSPACE_ID,
                lead_id=LEAD_ID,
                workflow_id=WORKFLOW_ID,
                track_version_id=TRACK_VERSION_ID,
                step_id=STEP_ID,
                phase="maintenance",
                occurrence_number=index,
                scheduled_for=NOW,
                due_at=NOW,
                status=occurrence_status,
                idempotency_key=f"occurrence-{index}",
                logical_touch_count=1 if occurrence_status == "sent" else 0,
                fallback_used=occurrence_status == "sent",
                provider_message_id=None,
                provider_delivery_status=None,
                correlation_id=None,
                failure_reason=None,
                created_at=NOW,
                closed_at=NOW if occurrence_status in {"sent", "cancelled"} else None,
            )
            for index, occurrence_status in enumerate(
                (
                    "planned",
                    "deferred",
                    "review_requested",
                    "expired",
                    "failed",
                    "uncertain",
                    "sent",
                    "cancelled",
                ),
                start=1,
            )
        ]
    )
    await session.flush()

    campaign = await session.get(CampaignModel, CAMPAIGN_ID)
    assert campaign is not None
    campaign.active_version_id = VERSION_ID
    await session.flush()

    session.add_all(
        [
            CampaignAdminAuditLogModel(
                audit_log_id=AUDIT_ID,
                workspace_id=WORKSPACE_ID,
                campaign_id=CAMPAIGN_ID,
                campaign_version_id=VERSION_ID,
                actor_user_id=USER_ID,
                action="campaign_version_published",
                details={"version_number": 1},
                created_at=NOW,
            ),
            CRMSyncJobModel(
                sync_job_id=SYNC_JOB_ID,
                workspace_id=WORKSPACE_ID,
                crm_provider="follow_up_boss",
                sync_type="full",
                status="completed",
                started_at=NOW,
                finished_at=NOW,
                cursor_started_at=NOW,
                cursor_finished_at=NOW,
                total_seen=1,
                total_upserted=1,
                total_failed=0,
                failure_reason=None,
                last_heartbeat_at=NOW,
                created_by_user_id=USER_ID,
                created_at=NOW,
                updated_at=NOW,
            ),
            ExternalEventModel(
                external_event_id=EXTERNAL_EVENT_ID,
                workspace_id=WORKSPACE_ID,
                provider="follow_up_boss",
                event_type="message.received",
                provider_event_id="evt-1",
                crm_lead_id="crm-123",
                lead_id=LEAD_ID,
                received_at=NOW,
                processed_at=None,
                status="pending",
                payload_redacted={},
                failure_reason=None,
                created_at=NOW,
                updated_at=NOW,
            ),
            OutboxEventModel(
                outbox_event_id=OUTBOX_EVENT_ID,
                workspace_id=WORKSPACE_ID,
                aggregate_type="campaign",
                aggregate_id=CAMPAIGN_ID,
                event_type="campaign.published",
                payload={},
                status="failed",
                attempt_count=1,
                available_at=NOW,
                created_at=NOW,
                published_at=None,
                last_error="broker unavailable",
            ),
        ]
    )
    await session.flush()
