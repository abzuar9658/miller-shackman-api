from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.application.services.paused_search_drafting_templates import (
    get_paused_search_drafting_template,
)
from app.application.use_cases.process_inbound_message_event import (
    InboundMessageEvent,
    ProcessInboundMessageEventResult,
    ProcessInboundMessageEventStatus,
    process_inbound_message_event,
)
from app.application.use_cases.seed_default_paused_search_tracks import (
    DEFAULT_PAUSED_SEARCH_TRACK_TEMPLATES,
    _DefaultPausedSearchTrackTemplate,
    seed_default_paused_search_tracks,
)
from app.core.config import Settings
from app.domain.campaigns.enrollment import (
    CampaignEnrollment,
    CampaignEnrollmentSource,
    CampaignEnrollmentStatus,
)
from app.domain.campaigns.template_registry import TemplateChannel, TemplateStatus, TemplateVersion
from app.domain.common.ids import WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SmsComplianceState,
    WorkspaceContactPolicy,
)
from app.domain.conversations import WorkspaceHandoffConfig
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    Workspace,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import (
    ActivityReliability,
    CanonicalLeadRecord,
    CRMProvider,
    LeadType,
    PausedSearchReasonCode,
    PausedSearchSource,
)
from app.domain.workflows import LeadWorkflow, WorkflowState
from app.domain.workspace_automation import WorkspaceOperationalControl
from app.infrastructure.messaging.sink import SinkEmailProvider, SinkSMSProvider
from app.infrastructure.persistence.postgres.campaign_enrollment_repository import (
    PostgresCampaignEnrollmentRepository,
)
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresConversationRepository,
    PostgresConversationSummaryRepository,
    PostgresHandoffCompletionRepository,
    PostgresHandoffRepository,
    PostgresInboundMessageRepository,
)
from app.infrastructure.persistence.postgres.crm_sync_repository import (
    PostgresExternalEventRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresWorkspaceRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import (
    CampaignCadenceStepModel,
    CampaignModel,
    CampaignVersionModel,
    UserModel,
    WorkspaceMembershipModel,
)
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.paused_search_occurrence_repository import (
    PostgresPausedSearchOccurrenceRepository,
)
from app.infrastructure.persistence.postgres.paused_search_track_repository import (
    PostgresPausedSearchTrackAdminAuditLogRepository,
    PostgresPausedSearchTrackAdminRepository,
)
from app.infrastructure.persistence.postgres.template_repository import PostgresTemplateRepository
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from app.infrastructure.persistence.postgres.workspace_contact_policy_repository import (
    PostgresWorkspaceContactPolicyRepository,
)
from app.infrastructure.persistence.postgres.workspace_handoff_config_repository import (
    PostgresWorkspaceHandoffConfigRepository,
)
from app.infrastructure.persistence.postgres.workspace_operational_control_repository import (
    PostgresWorkspaceOperationalControlRepository,
)
from app.infrastructure.workflows.temporal import activities
from app.infrastructure.workflows.temporal.lead_nurture import (
    InboundProcessedWorkflowSignal,
    LeadNurtureExecutionMode,
    LeadNurtureWorkflow,
    LeadNurtureWorkflowInput,
)
from tests.infrastructure.persistence.postgres._harness import PostgresHarnessDatabase
from tests.infrastructure.persistence.postgres.test_business_flow_harness import (
    FakeCRMClient,
    FakeInboundReplyLLMClient,
    _classification_json,
)

NOW = datetime(2026, 7, 27, 15, 0, tzinfo=UTC)
CAMPAIGN_ID = UUID("71000000-0000-0000-0000-000000000001")
CAMPAIGN_VERSION_ID = UUID("71000000-0000-0000-0000-000000000002")
ACTOR_ID = UUID("71000000-0000-0000-0000-000000000003")
MEMBERSHIP_ID = UUID("71000000-0000-0000-0000-000000000004")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "track_template",
    DEFAULT_PAUSED_SEARCH_TRACK_TEMPLATES,
    ids=lambda template: template.reason_code.value,
)
async def test_real_temporal_paused_search_track_runs_postgres_send_and_inbound_handoff(
    postgres_harness_database: PostgresHarnessDatabase,
    track_template: _DefaultPausedSearchTrackTemplate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = track_template
    reason_code = template.reason_code
    workspace_id = uuid5(NAMESPACE_URL, f"postgres-e2e-workspace:{reason_code.value}")
    lead_id = uuid5(NAMESPACE_URL, f"postgres-e2e-lead:{reason_code.value}")
    workflow_id = uuid5(NAMESPACE_URL, f"postgres-e2e-workflow:{reason_code.value}")
    enrollment_id = uuid5(NAMESPACE_URL, f"postgres-e2e-enrollment:{reason_code.value}")
    actor_id = uuid5(workspace_id, "actor")
    membership_id = uuid5(workspace_id, "membership")
    campaign_id = uuid5(workspace_id, "campaign")
    campaign_version_id = uuid5(workspace_id, "campaign-version")
    task_queue = f"postgres-e2e-{reason_code.value}"

    engine = create_async_engine(postgres_harness_database.async_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    email_provider = SinkEmailProvider()
    sms_provider = SinkSMSProvider()
    llm_client = _OutboundLLMClient()
    settings = Settings(
        sms_provider="sink",
        email_provider="sink",
        recurring_paused_search_pilot_workspace_ids=[workspace_id],
    )
    monkeypatch.setattr(activities, "async_session_factory", session_factory)
    monkeypatch.setattr(activities, "get_settings", lambda: settings)
    monkeypatch.setattr(activities, "build_email_provider", lambda _=None: email_provider)
    monkeypatch.setattr(activities, "build_sms_provider", lambda _=None: sms_provider)
    monkeypatch.setattr(activities, "build_llm_client", lambda _=None: llm_client)
    monkeypatch.setattr(activities, "build_crm_client", lambda _=None: None)
    monkeypatch.setattr(activities, "build_listing_search_client", lambda _=None: None)

    try:
        await _seed_database(
            session_factory,
            workspace_id,
            lead_id,
            workflow_id,
            enrollment_id,
            campaign_id,
            campaign_version_id,
            actor_id,
            membership_id,
            template,
        )
        env = await WorkflowEnvironment.start_time_skipping()
        async with env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[LeadNurtureWorkflow],
                activities=[
                    activities.schedule_next_paused_search_occurrence_activity,
                    activities.execute_paused_search_occurrence_activity,
                ],
            ):
                handle = await env.client.start_workflow(
                    LeadNurtureWorkflow.run,
                    LeadNurtureWorkflowInput(
                        workspace_id=workspace_id,
                        lead_id=lead_id,
                        campaign_version_id=campaign_version_id,
                        workflow_id=workflow_id,
                        execution_mode=LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING,
                        paused_search_track_version_id=None,
                    ),
                    id=f"postgres-e2e-{reason_code.value}",
                    task_queue=task_queue,
                )
                with env.auto_time_skipping_disabled():
                    await env.sleep(1)
                    waiting = await handle.query("snapshot")
                assert waiting["last_activity_status"] == "scheduled"
                scheduled_for = datetime.fromisoformat(str(waiting["scheduled_for"]))
                interval = template.maintenance_interval_days

                await env.sleep(timedelta(days=interval + 1))
                await env.sleep(1)
                if not email_provider.messages:
                    await env.sleep(timedelta(days=365))
                    await env.sleep(1)
                sent = await handle.query("snapshot")
                assert sent["last_activity_status"] in {"sent", "terminal"}
                assert len(email_provider.messages) == 1
                expected_subjects: set[str] = set()
                for phase in ("maintenance", "reactivation"):
                    expected = get_paused_search_drafting_template(
                        f"{template.track_key}-{phase}-email-1"
                    )
                    assert expected is not None
                    expected_subjects.add(expected.email_subject_template)
                assert email_provider.messages[0].subject in expected_subjects

                inbound_result = await _process_inbound_reply(
                    session_factory=session_factory,
                    workspace_id=workspace_id,
                    lead_id=lead_id,
                    reason_code=reason_code,
                )
                assert inbound_result.status is ProcessInboundMessageEventStatus.PROCESSED
                assert inbound_result.handoff_required is True
                if sent["last_activity_status"] == "terminal":
                    blocked = sent
                else:
                    await handle.signal(
                        "inbound-processed",
                        InboundProcessedWorkflowSignal(
                            workspace_id=workspace_id,
                            lead_id=lead_id,
                            occurred_at=(scheduled_for + timedelta(seconds=3)).isoformat(),
                            inbound_action="human_handoff",
                            reason="human_requested",
                        ),
                    )
                    with env.auto_time_skipping_disabled():
                        await env.sleep(1)
                        blocked = await handle.query("snapshot")
                    assert blocked["last_signal"] == "inbound_processed"
                    await env.sleep(timedelta(days=interval + 1))
                    await env.sleep(1)
                assert blocked["last_activity_status"] in {"blocked", "terminal"}
                assert len(email_provider.messages) == 1
                if sent["last_activity_status"] != "terminal":
                    await handle.signal("close")
                await handle.result()

        async with session_factory() as session:
            occurrences = await PostgresPausedSearchOccurrenceRepository(
                session
            ).list_for_workspace(workspace_id, lead_id=lead_id)
            messages = await PostgresOutboundMessageRepository(session).list_for_lead(
                workspace_id, lead_id
            )
            workflow = await PostgresLeadWorkflowRepository(session).get_latest_for_lead(
                workspace_id, lead_id
            )
            assert occurrences
            assert any(occurrence.status.value == "sent" for occurrence in occurrences)
            assert len(messages) == 1
            assert messages[0].provider_message_id is not None
            assert workflow is not None
            assert workflow.state is WorkflowState.HUMAN_HANDOFF
    finally:
        await engine.dispose()


async def _seed_database(
    session_factory: async_sessionmaker[AsyncSession],
    workspace_id: WorkspaceId,
    lead_id: UUID,
    workflow_id: UUID,
    enrollment_id: UUID,
    campaign_id: UUID,
    campaign_version_id: UUID,
    actor_id: UUID,
    membership_id: UUID,
    template: _DefaultPausedSearchTrackTemplate,
) -> None:
    async with session_factory() as session:
        await PostgresWorkspaceRepository(session).save(
            Workspace(
                workspace_id=workspace_id,
                name="Postgres Temporal E2E",
                status=WorkspaceStatus.ACTIVE,
                default_timezone="America/Chicago",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            UserModel(
                user_id=actor_id,
                email=f"admin-{workspace_id}@example.com",
                email_normalized=f"admin-{workspace_id}@example.com",
                full_name="E2E Admin",
                status="active",
                email_verified_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        session.add(
            WorkspaceMembershipModel(
                membership_id=membership_id,
                workspace_id=workspace_id,
                user_id=actor_id,
                role=WorkspaceMembershipRole.BROKERAGE_ADMIN.value,
                status=WorkspaceMembershipStatus.ACTIVE.value,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        await PostgresWorkspaceContactPolicyRepository(session).save(
            WorkspaceContactPolicy(
                workspace_id=workspace_id,
                sms_compliance_state=SmsComplianceState.APPROVED,
                quiet_hours_enabled=False,
            )
        )
        await PostgresWorkspaceHandoffConfigRepository(session).save(
            WorkspaceHandoffConfig(
                workspace_id=workspace_id,
                fallback_recipient_email="fallback@example.com",
            )
        )
        await PostgresWorkspaceOperationalControlRepository(session).save(
            WorkspaceOperationalControl(
                workspace_id=workspace_id,
                recurring_paused_search_enabled=True,
            )
        )
        await _seed_templates(session, workspace_id)
        await _seed_campaign_and_lead(
            session,
            workspace_id,
            lead_id,
            campaign_id,
            campaign_version_id,
            actor_id,
            template,
        )
        seed_result = await seed_default_paused_search_tracks(
            actor=_actor(workspace_id, actor_id, membership_id),
            workspace_id=workspace_id,
            repository=PostgresPausedSearchTrackAdminRepository(session),
            audit_log_repository=PostgresPausedSearchTrackAdminAuditLogRepository(session),
            template_repository=PostgresTemplateRepository(session),
            now=NOW,
        )
        track_repository = PostgresPausedSearchTrackAdminRepository(session)
        mapping = await track_repository.get_reason_mapping(workspace_id, template.reason_code)
        assert mapping is not None, seed_result.items
        steps = await track_repository.get_steps(workspace_id, mapping.track_version_id)
        await track_repository.replace_steps(
            workspace_id,
            mapping.track_version_id,
            tuple(
                replace(step, delay_hours=24) if step.phase.value == "reactivation" else step
                for step in steps
            ),
        )
        enrollment = CampaignEnrollment(
            campaign_enrollment_id=enrollment_id,
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            campaign_version_id=campaign_version_id,
            lead_id=lead_id,
            source=CampaignEnrollmentSource.MANUAL_ADMIN,
            status=CampaignEnrollmentStatus.ACTIVE,
            eligible_at=NOW,
            enrolled_at=NOW,
            started_at=NOW,
            ended_at=None,
            created_by_user_id=actor_id,
            reason_codes=(template.reason_code.value,),
            created_at=NOW,
            updated_at=NOW,
        )
        await PostgresCampaignEnrollmentRepository(session).save(enrollment)
        await PostgresLeadWorkflowRepository(session).save(
            LeadWorkflow(
                workflow_id=workflow_id,
                temporal_workflow_id=f"postgres-e2e-{template.reason_code.value}",
                workspace_id=workspace_id,
                campaign_enrollment_id=enrollment_id,
                campaign_id=campaign_id,
                lead_id=lead_id,
                state=WorkflowState.ACTIVE_NURTURE,
                last_transition_at=NOW,
                state_version=1,
                created_at=NOW,
                updated_at=NOW,
                paused_search_track_version_id=mapping.track_version_id,
            )
        )
        await session.commit()


async def _seed_templates(session: AsyncSession, workspace_id: WorkspaceId) -> None:
    repository = PostgresTemplateRepository(session)
    for track_template in DEFAULT_PAUSED_SEARCH_TRACK_TEMPLATES:
        for phase in ("maintenance", "reactivation"):
            template_key = f"{track_template.track_key}-{phase}-email-1"
            drafting_template = get_paused_search_drafting_template(template_key)
            assert drafting_template is not None
            await repository.save(
                TemplateVersion(
                    template_version_id=uuid5(workspace_id, template_key),
                    workspace_id=workspace_id,
                    template_key=template_key,
                    version=1,
                    channel=TemplateChannel.EMAIL,
                    purpose="paused_search",
                    content=drafting_template.email_template,
                    subject=drafting_template.email_subject_template,
                    prompt_text=drafting_template.email_prompt_text,
                    allowed_variables=(
                        "agent_name",
                        "brokerage_name",
                        "lead_first_name",
                        "message_body",
                    ),
                    permitted_use_tags=(
                        "no_prohibited_advice",
                        "no_financial_advice",
                        "listing_context_allowed",
                    ),
                    status=TemplateStatus.APPROVED,
                    approved_at=NOW,
                    created_at=NOW,
                )
            )


async def _seed_campaign_and_lead(
    session: AsyncSession,
    workspace_id: WorkspaceId,
    lead_id: UUID,
    campaign_id: UUID,
    campaign_version_id: UUID,
    actor_id: UUID,
    template: _DefaultPausedSearchTrackTemplate,
) -> None:
    campaign = CampaignModel(
        campaign_id=campaign_id,
        workspace_id=workspace_id,
        name="Paused Search E2E",
        status="active",
        active_version_id=None,
        created_by_user_id=actor_id,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(campaign)
    await session.flush()
    session.add(
        CampaignVersionModel(
            campaign_version_id=campaign_version_id,
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            version_number=1,
            status="published",
            enabled_channels=[ContactChannel.EMAIL.value],
            daily_start_cap=50,
            dormant_threshold_days=60,
            quiet_hours_start=time(10, 0),
            quiet_hours_end=time(17, 0),
            timezone="America/Chicago",
            sms_compliance_required=True,
            preflight_digest_enabled=False,
            prompt_version="v1",
            approved_model="openai/gpt-4o-mini",
            created_by_user_id=actor_id,
            published_at=NOW,
            created_at=NOW,
        )
    )
    await session.flush()
    campaign.active_version_id = campaign_version_id
    await session.flush()
    session.add(
        CampaignCadenceStepModel(
            cadence_step_id=uuid5(NAMESPACE_URL, f"cadence:{workspace_id}"),
            workspace_id=workspace_id,
            campaign_version_id=campaign_version_id,
            step_order=1,
            channel=ContactChannel.EMAIL.value,
            delay_hours=0,
            message_goal="Paused-search E2E",
            template_key=f"paused-search-{template.reason_code.value}-maintenance-email-1",
            max_attempts=1,
            created_at=NOW,
        )
    )
    await PostgresLeadRepository(session).upsert(
        CanonicalLeadRecord(
            workspace_id=workspace_id,
            lead_id=lead_id,
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            crm_lead_id=f"postgres-e2e-{workspace_id}",
            facts_derived_at=NOW,
            source_payload_version="postgres-e2e:v1",
            lead_type=LeadType.BUYER,
            lead_source="synthetic_e2e",
            lead_stage="long_term_nurture",
            activity_reliability=ActivityReliability.RELIABLE,
            primary_email=f"lead-{workspace_id}@example.com",
            has_email=True,
            email_permission_status=ContactPermissionStatus.CONFIRMED,
            do_not_contact=False,
            paused_search_active=True,
            pause_reason_code=template.reason_code,
            paused_search_source=PausedSearchSource.AI_CONVERSATION_CLASSIFICATION,
            paused_search_recorded_at=NOW,
            reengagement_not_before=NOW
            + timedelta(
                days=2 * template.maintenance_interval_days + template.reactivation_window_days
            ),
        )
    )
    await session.flush()


async def _process_inbound_reply(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    workspace_id: WorkspaceId,
    lead_id: UUID,
    reason_code: PausedSearchReasonCode,
) -> ProcessInboundMessageEventResult:
    async with session_factory() as session:
        result = await process_inbound_message_event(
            event=InboundMessageEvent(
                workspace_id=workspace_id,
                provider=CRMProvider.FOLLOW_UP_BOSS.value,
                provider_event_id=f"inbound-{reason_code.value}",
                provider_message_id=f"inbound-message-{reason_code.value}",
                crm_lead_id=f"postgres-e2e-{workspace_id}",
                channel=ContactChannel.EMAIL,
                body="Please have an agent contact me.",
                received_at=NOW + timedelta(days=1),
                payload_redacted={"source": "postgres-e2e"},
            ),
            lead_repository=PostgresLeadRepository(session),
            external_event_repository=PostgresExternalEventRepository(session),
            conversation_repository=PostgresConversationRepository(session),
            inbound_message_repository=PostgresInboundMessageRepository(session),
            conversation_summary_repository=PostgresConversationSummaryRepository(session),
            handoff_repository=PostgresHandoffRepository(session),
            crm_client=FakeCRMClient(),
            notification_provider=None,
            workspace_handoff_config_repository=PostgresWorkspaceHandoffConfigRepository(session),
            handoff_completion_repository=PostgresHandoffCompletionRepository(session),
            llm_client=FakeInboundReplyLLMClient(_classification_json()),
            now=NOW + timedelta(days=1),
            lead_workflow_repository=PostgresLeadWorkflowRepository(session),
            paused_search_occurrence_repository=PostgresPausedSearchOccurrenceRepository(session),
            workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        )
        await session.commit()
        return result


def _actor(workspace_id: WorkspaceId, actor_id: UUID, membership_id: UUID) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=actor_id,
        user_status=UserStatus.ACTIVE,
        active_role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
        active_workspace_id=workspace_id,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=membership_id,
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


class _OutboundLLMClient:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def complete(self, request: object) -> object:
        from app.application.ports.llm import LLMResult

        self.requests.append(request)
        return LLMResult(
            text=(
                '{"body":"Just checking in when the timing feels right.",'
                '"subject":"A gentle check-in","confidence":0.95,'
                '"personalization_notes":["safe"],"safety_flags":[]}'
            ),
            model="openai/gpt-4o-mini",
            prompt_version=getattr(request, "prompt_version", "v1"),
            latency_ms=1,
            usage_tokens=1,
        )
