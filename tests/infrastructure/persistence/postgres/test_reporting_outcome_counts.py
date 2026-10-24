from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_postgres_workspace_context
from app.domain.reporting import WorkflowStateCounts
from app.infrastructure.persistence.postgres.models import (
    CampaignModel,
    CampaignVersionModel,
    ConversationModel,
    HandoffModel,
    InboundMessageModel,
    LeadModel,
    OutboundMessageModel,
    UserModel,
    WorkspaceModel,
)
from app.infrastructure.persistence.postgres.reporting_repository import PostgresReportingRepository
from app.infrastructure.persistence.postgres.workflow_models import (
    CampaignEnrollmentModel,
    LeadWorkflowModel,
)

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_WORKSPACE_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("33333333-3333-3333-3333-333333333333")


@pytest.mark.asyncio
async def test_outcome_counts_count_distinct_leads_through_the_funnel(
    postgres_session: AsyncSession,
) -> None:
    session = postgres_session
    await _seed_workspaces(session)
    campaign_id, version_id = await _seed_campaign(session, WORKSPACE_ID)

    # Re-enrolled lead: two workflows, two sends, a reply, and a handoff.
    # Counted once at every step, by its latest workflow state.
    re_enrolled = await _seed_lead(session, WORKSPACE_ID, "re-enrolled")
    enrollment = await _seed_enrollment(session, WORKSPACE_ID, campaign_id, version_id, re_enrolled)
    await _seed_workflow(
        session,
        WORKSPACE_ID,
        campaign_id,
        enrollment,
        re_enrolled,
        "completed",
        NOW - timedelta(days=30),
    )
    workflow = await _seed_workflow(
        session, WORKSPACE_ID, campaign_id, enrollment, re_enrolled, "human_handoff", NOW
    )
    await _seed_outbound(
        session, WORKSPACE_ID, campaign_id, re_enrolled, "sent", sent_at=NOW - timedelta(days=40)
    )
    await _seed_outbound(
        session, WORKSPACE_ID, campaign_id, re_enrolled, "sent", sent_at=NOW - timedelta(days=2)
    )
    inbound = await _seed_inbound(session, WORKSPACE_ID, re_enrolled, NOW - timedelta(days=1))
    await _seed_handoff(
        session, WORKSPACE_ID, re_enrolled, "notified", workflow_id=workflow, inbound_id=inbound
    )

    # Uncertain send has no sent_at; its attempt time is the send time.
    uncertain = await _seed_lead(session, WORKSPACE_ID, "uncertain")
    enrollment = await _seed_enrollment(session, WORKSPACE_ID, campaign_id, version_id, uncertain)
    await _seed_workflow(
        session, WORKSPACE_ID, campaign_id, enrollment, uncertain, "active_nurture", NOW
    )
    await _seed_outbound(
        session,
        WORKSPACE_ID,
        campaign_id,
        uncertain,
        "uncertain",
        sent_at=None,
        attempted_at=NOW - timedelta(days=3),
    )
    await _seed_inbound(session, WORKSPACE_ID, uncertain, NOW - timedelta(days=2))

    # Inbound received before the first send is not a reply to outreach.
    early_inbound = await _seed_lead(session, WORKSPACE_ID, "early-inbound")
    enrollment = await _seed_enrollment(
        session, WORKSPACE_ID, campaign_id, version_id, early_inbound
    )
    await _seed_workflow(
        session, WORKSPACE_ID, campaign_id, enrollment, early_inbound, "waiting_for_response", NOW
    )
    await _seed_inbound(session, WORKSPACE_ID, early_inbound, NOW - timedelta(days=5))
    await _seed_outbound(
        session, WORKSPACE_ID, campaign_id, early_inbound, "sent", sent_at=NOW - timedelta(days=4)
    )

    # Replied, but the only handoff was cancelled; the lead later opted out.
    cancelled_handoff = await _seed_lead(session, WORKSPACE_ID, "cancelled-handoff")
    enrollment = await _seed_enrollment(
        session, WORKSPACE_ID, campaign_id, version_id, cancelled_handoff
    )
    await _seed_workflow(
        session, WORKSPACE_ID, campaign_id, enrollment, cancelled_handoff, "suppressed", NOW
    )
    await _seed_outbound(
        session,
        WORKSPACE_ID,
        campaign_id,
        cancelled_handoff,
        "sent",
        sent_at=NOW - timedelta(days=3),
    )
    await _seed_inbound(session, WORKSPACE_ID, cancelled_handoff, NOW - timedelta(days=2))
    await _seed_handoff(session, WORKSPACE_ID, cancelled_handoff, "cancelled")

    # Enrolled, but nothing actually went out: pending and failed sends only.
    never_sent = await _seed_lead(session, WORKSPACE_ID, "never-sent")
    enrollment = await _seed_enrollment(session, WORKSPACE_ID, campaign_id, version_id, never_sent)
    await _seed_workflow(session, WORKSPACE_ID, campaign_id, enrollment, never_sent, "queued", NOW)
    await _seed_outbound(session, WORKSPACE_ID, campaign_id, never_sent, "pending", sent_at=None)
    await _seed_outbound(session, WORKSPACE_ID, campaign_id, never_sent, "failed", sent_at=None)
    await _seed_inbound(session, WORKSPACE_ID, never_sent, NOW - timedelta(days=1))

    # Handoff for a lead that was never contacted is outside the funnel.
    not_enrolled = await _seed_lead(session, WORKSPACE_ID, "not-enrolled")
    await _seed_handoff(session, WORKSPACE_ID, not_enrolled, "created")

    # Another workspace's full funnel must not leak in.
    other_campaign_id, other_version_id = await _seed_campaign(session, OTHER_WORKSPACE_ID)
    other_lead = await _seed_lead(session, OTHER_WORKSPACE_ID, "other")
    enrollment = await _seed_enrollment(
        session, OTHER_WORKSPACE_ID, other_campaign_id, other_version_id, other_lead
    )
    await _seed_workflow(
        session, OTHER_WORKSPACE_ID, other_campaign_id, enrollment, other_lead, "human_owned", NOW
    )
    await _seed_outbound(
        session,
        OTHER_WORKSPACE_ID,
        other_campaign_id,
        other_lead,
        "sent",
        sent_at=NOW - timedelta(days=2),
    )
    await _seed_inbound(session, OTHER_WORKSPACE_ID, other_lead, NOW - timedelta(days=1))
    await _seed_handoff(session, OTHER_WORKSPACE_ID, other_lead, "acknowledged")

    await set_postgres_workspace_context(session, str(WORKSPACE_ID))
    report = await PostgresReportingRepository(session).get_workspace_operations_summary(
        WORKSPACE_ID
    )

    outcome = report.outcome_counts
    assert outcome.enrolled_leads == 5
    assert outcome.contacted_leads == 4
    assert outcome.replied_leads == 3
    assert outcome.handed_off_leads == 1
    assert outcome.replied_by_current_state == WorkflowStateCounts(
        human_handoff=1,
        active_nurture=1,
        suppressed=1,
    )


@pytest.mark.asyncio
async def test_outcome_counts_are_zero_for_an_empty_workspace(
    postgres_session: AsyncSession,
) -> None:
    await _seed_workspaces(postgres_session)
    await set_postgres_workspace_context(postgres_session, str(WORKSPACE_ID))

    report = await PostgresReportingRepository(postgres_session).get_workspace_operations_summary(
        WORKSPACE_ID
    )

    outcome = report.outcome_counts
    assert outcome.enrolled_leads == 0
    assert outcome.contacted_leads == 0
    assert outcome.replied_leads == 0
    assert outcome.handed_off_leads == 0
    assert outcome.replied_by_current_state == WorkflowStateCounts()


async def _seed_workspaces(session: AsyncSession) -> None:
    session.add_all(
        [
            WorkspaceModel(
                workspace_id=workspace_id,
                name=name,
                status="active",
                default_timezone="UTC",
                created_at=NOW,
                updated_at=NOW,
            )
            for workspace_id, name in (
                (WORKSPACE_ID, "Outcome Workspace"),
                (OTHER_WORKSPACE_ID, "Other Workspace"),
            )
        ]
    )
    session.add(
        UserModel(
            user_id=USER_ID,
            email="outcomes@example.com",
            email_normalized="outcomes@example.com",
            full_name="Outcome Admin",
            status="active",
            email_verified_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()


async def _seed_campaign(session: AsyncSession, workspace_id: UUID) -> tuple[UUID, UUID]:
    campaign_id = uuid4()
    version_id = uuid4()
    session.add(
        CampaignModel(
            campaign_id=campaign_id,
            workspace_id=workspace_id,
            name="Dormant Buyers",
            status="active",
            active_version_id=None,
            created_by_user_id=USER_ID,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()
    session.add(
        CampaignVersionModel(
            campaign_version_id=version_id,
            workspace_id=workspace_id,
            campaign_id=campaign_id,
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
        )
    )
    await session.flush()
    return campaign_id, version_id


async def _seed_lead(session: AsyncSession, workspace_id: UUID, crm_lead_id: str) -> UUID:
    lead_id = uuid4()
    session.add(
        LeadModel(
            lead_id=lead_id,
            workspace_id=workspace_id,
            crm_provider="follow_up_boss",
            crm_lead_id=crm_lead_id,
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
            primary_email=f"{crm_lead_id}@example.com",
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
        )
    )
    await session.flush()
    return lead_id


async def _seed_enrollment(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    version_id: UUID,
    lead_id: UUID,
) -> UUID:
    enrollment_id = uuid4()
    session.add(
        CampaignEnrollmentModel(
            campaign_enrollment_id=enrollment_id,
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            campaign_version_id=version_id,
            lead_id=lead_id,
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
        )
    )
    await session.flush()
    return enrollment_id


async def _seed_workflow(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    enrollment_id: UUID,
    lead_id: UUID,
    state: str,
    transitioned_at: datetime,
) -> UUID:
    workflow_id = uuid4()
    session.add(
        LeadWorkflowModel(
            workflow_id=workflow_id,
            temporal_workflow_id=f"workflow-{workflow_id}",
            workspace_id=workspace_id,
            campaign_enrollment_id=enrollment_id,
            campaign_id=campaign_id,
            lead_id=lead_id,
            state=state,
            current_step_id=None,
            next_action_at=None,
            last_transition_at=transitioned_at,
            pause_reason=None,
            resume_reason=None,
            state_version=1,
            created_at=transitioned_at,
            updated_at=transitioned_at,
        )
    )
    await session.flush()
    return workflow_id


async def _seed_outbound(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    lead_id: UUID,
    status: str,
    *,
    sent_at: datetime | None,
    attempted_at: datetime | None = None,
) -> None:
    message_id = uuid4()
    created_at = sent_at or attempted_at or NOW
    session.add(
        OutboundMessageModel(
            message_id=message_id,
            workspace_id=workspace_id,
            lead_id=lead_id,
            campaign_id=campaign_id,
            cadence_step_id=f"step-{message_id}",
            channel="email",
            status=status,
            idempotency_key=f"message-{message_id}",
            body="Hello",
            subject="Hi",
            html_body=None,
            scheduled_for=created_at,
            planned_at=created_at,
            sent_at=sent_at,
            message_version=1,
            provider_send_status="accepted" if status == "sent" else status,
            provider_name="sendgrid",
            provider_message_id=f"provider-{message_id}",
            provider_last_attempt_at=attempted_at,
            draft_personalization_notes=[],
            draft_safety_flags=[],
            created_at=created_at,
            updated_at=created_at,
        )
    )
    await session.flush()


async def _seed_inbound(
    session: AsyncSession,
    workspace_id: UUID,
    lead_id: UUID,
    received_at: datetime,
) -> UUID:
    conversation_id = uuid4()
    inbound_id = uuid4()
    session.add(
        ConversationModel(
            conversation_id=conversation_id,
            workspace_id=workspace_id,
            lead_id=lead_id,
            status="active",
            ai_interaction_count=0,
            last_message_at=received_at,
            created_at=received_at,
            updated_at=received_at,
        )
    )
    await session.flush()
    session.add(
        InboundMessageModel(
            inbound_message_id=inbound_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            lead_id=lead_id,
            channel="email",
            provider="sendgrid",
            provider_message_id=f"inbound-{inbound_id}",
            from_address_redacted="l***@example.com",
            to_address_redacted="a***@example.com",
            body="Yes, still looking",
            received_at=received_at,
            processed_at=received_at,
            classification_status="classified",
            created_at=received_at,
        )
    )
    await session.flush()
    return inbound_id


async def _seed_handoff(
    session: AsyncSession,
    workspace_id: UUID,
    lead_id: UUID,
    status: str,
    *,
    workflow_id: UUID | None = None,
    inbound_id: UUID | None = None,
) -> None:
    session.add(
        HandoffModel(
            handoff_id=uuid4(),
            workspace_id=workspace_id,
            lead_id=lead_id,
            workflow_id=workflow_id,
            inbound_message_id=inbound_id,
            reason_code="high_interest",
            summary="Lead wants to tour this weekend.",
            latest_inbound_text="Yes, still looking",
            preferences={},
            status=status,
            created_at=NOW,
        )
    )
    await session.flush()
