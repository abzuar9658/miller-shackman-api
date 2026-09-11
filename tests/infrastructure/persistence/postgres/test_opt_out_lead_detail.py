from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.services.crm_lead_refresh import (
    CrmLeadRefreshStatus,
    refresh_lead_from_crm,
)
from app.application.use_cases.recover_recorded_opt_outs import (
    RecoverOptOutsRequest,
    RecoveryStatus,
    recover_recorded_opt_outs,
)
from app.core.database import enable_postgres_service_access
from app.domain.compliance.contactability import ContactPermissionStatus
from app.domain.crm_sync import INBOUND_MESSAGE_RECEIVED_EVENT_TYPE
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import CanonicalLeadRecord
from app.domain.workflows import (
    LeadWorkflow,
    WorkflowState,
    WorkflowTransitionReasonCode,
    transition_workflow,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import (
    Base,
    ConversationModel,
    HandoffModel,
    InboundMessageModel,
    OutboundMessageModel,
)
from app.infrastructure.persistence.postgres.opt_out_recovery import (
    PostgresOptOutRecoveryRepository,
)
from app.infrastructure.persistence.postgres.workflow_models import CampaignEnrollmentModel
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from app.interfaces.api.dependencies.lead_read import get_lead_read_bundle
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.main import create_app
from tests.application.use_cases._crm_history_import_fakes import FakeCanonicalLeadRefreshSource
from tests.infrastructure.persistence.postgres import test_business_flow_harness as business_flow
from tests.infrastructure.persistence.postgres.test_opt_out_recovery import (
    NOW,
    read_lead,
    suppression_event,
)
from tests.infrastructure.persistence.postgres.test_opt_out_recovery import (
    recovery_case as recovery_case,
)


@pytest.mark.parametrize(
    ("kind", "sms_reasons", "email_reasons"),
    [
        pytest.param("sms_opt_out", ["sms_opted_out"], [], id="sms-opt-out"),
        pytest.param("email_unsubscribed", [], ["email_unsubscribed"], id="email-unsubscribe"),
        pytest.param(
            "do_not_contact", ["do_not_contact"], ["do_not_contact"], id="do-not-contact"
        ),
        pytest.param(None, [], [], id="clean"),
    ],
)
async def test_lead_detail_preserves_recovered_opt_outs_after_crm_refresh(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    kind: str | None,
    sms_reasons: list[str],
    email_reasons: list[str],
) -> None:
    sessions, lead = recovery_case
    lead = _contactable_lead(lead)
    async with sessions() as session:
        await enable_postgres_service_access(session)
        await PostgresLeadRepository(session).upsert(lead)
        if kind is not None:
            session.add(suppression_event(lead, kind=kind))
        await session.commit()

    report = await recover_recorded_opt_outs(
        request=RecoverOptOutsRequest(
            workspace_id=lead.workspace_id,
            lead_ids=(lead.lead_id,),
            apply=True,
            reviewed_for_lifts=True,
        ),
        repository=PostgresOptOutRecoveryRepository(sessions),
    )
    assert report.leads[0].status is (
        RecoveryStatus.CLEAN if kind is None else RecoveryStatus.CHANGED
    )
    recovered = await read_lead(sessions, lead)

    await _refresh_with_permissive_crm(sessions, lead)
    payload = (await _get_lead_detail(sessions, lead)).json()

    assert payload["status"] == "ok"
    api_lead = payload["lead"]
    assert api_lead["lead_id"] == str(lead.lead_id)
    assert api_lead["lead_stage"] == "crm-refreshed"
    assert api_lead["sms_opted_out"] is (kind == "sms_opt_out")
    assert api_lead["email_unsubscribed"] is (kind == "email_unsubscribed")
    assert api_lead["do_not_contact"] is (kind == "do_not_contact")
    sendability = api_lead["sendability"]
    expected_reasons = {"sms": sms_reasons, "email": email_reasons}
    for channel, reasons in expected_reasons.items():
        assert sendability[channel] == {
            "channel": channel,
            "sendable": not reasons,
            "reasons": reasons,
        }
    assert sendability["sendable_channels"] == [
        channel for channel, reasons in expected_reasons.items() if not reasons
    ]
    assert sendability["blocked_reasons"] == list(dict.fromkeys(sms_reasons + email_reasons))
    assert payload["latest_workflow"] is None
    assert payload["latest_handoff"] is None
    for field in (
        "inbound_messages",
        "outbound_messages",
        "workflow_transitions",
        "workflow_override_audits",
        "cadence_progress",
        "handoffs",
        "activity_log",
    ):
        assert payload[field] == [], field
    assert await read_lead(sessions, lead) == replace(recovered, lead_stage="crm-refreshed")


@pytest.mark.parametrize(
    ("state", "enrollment_status", "reason"),
    [
        (WorkflowState.PAUSED, "paused", WorkflowTransitionReasonCode.MANUAL_PAUSE),
        (
            WorkflowState.HUMAN_HANDOFF,
            "handoff",
            WorkflowTransitionReasonCode.HUMAN_HANDOFF_REQUIRED,
        ),
        (WorkflowState.COMPLETED, "completed", WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_SENT),
        (
            WorkflowState.SUPPRESSED,
            "suppressed",
            WorkflowTransitionReasonCode.CONTACT_SUPPRESSION_DETECTED,
        ),
        (WorkflowState.CLOSED, "closed", WorkflowTransitionReasonCode.LEAD_NOT_INTERESTED),
    ],
    ids=["paused", "human-handoff", "completed", "suppressed", "closed"],
)
async def test_recovery_and_crm_refresh_preserve_populated_lifecycle_in_lead_detail(
    postgres_session: AsyncSession,
    state: WorkflowState,
    enrollment_status: str,
    reason: WorkflowTransitionReasonCode,
) -> None:
    # Real Postgres savepoints let recovery commit without leaking the harness's
    # fixed seed IDs between cases; this is lifecycle isolation, not a race test.
    sessions = async_sessionmaker(
        await postgres_session.connection(),
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    lead = _contactable_lead(business_flow._lead())
    control = replace(
        lead,
        lead_id=uuid4(),
        crm_lead_id="unrelated-clean-control",
        primary_phone="+14155550162",
        primary_email="clean-control@example.test",
    )
    async with sessions() as session:
        await enable_postgres_service_access(session)
        await business_flow._seed_business_flow_prerequisites(session)
        for record in (lead, control):
            await PostgresLeadRepository(session).upsert(record)
        workflow = await _seed_lifecycle_history(session, lead, state, enrollment_status, reason)
        session.add(suppression_event(lead))
        await session.commit()

    before = await _lifecycle_snapshot(sessions, lead.workspace_id)
    assert {name: len(rows) for name, rows in before.items()} == {
        "lead_workflows": 1,
        "campaign_enrollments": 1,
        "handoffs": int(state is WorkflowState.HUMAN_HANDOFF),
        "workflow_transitions": 1,
        "outbound_messages": 1,
        "inbound_messages": 1,
        "conversations": 1,
        "external_events": 2,
    }
    before_payloads = {
        record.lead_id: (await _get_lead_detail(sessions, record)).json()
        for record in (lead, control)
    }
    prior = before_payloads[lead.lead_id]
    assert prior["latest_workflow"]["workflow_id"] == str(workflow.workflow_id)
    assert prior["latest_workflow"]["state"] == state.value
    assert prior["latest_workflow"]["next_action_at"] is None
    for field in ("workflow_transitions", "outbound_messages", "inbound_messages"):
        assert len(prior[field]) == 1, field
    if state is WorkflowState.HUMAN_HANDOFF:
        assert prior["latest_handoff"]["handoff_id"] == str(business_flow.HANDOFF_ID)
        assert prior["latest_handoff"]["status"] == "notified"
        assert len(prior["handoffs"]) == 1
    else:
        assert prior["latest_handoff"] is None
        assert prior["handoffs"] == []
    assert before_payloads[control.lead_id]["latest_workflow"] is None
    assert before_payloads[control.lead_id]["latest_handoff"] is None
    for payload in before_payloads.values():
        assert payload["lead"]["sms_opted_out"] is False
        assert payload["lead"]["sendability"]["sendable_channels"] == ["sms", "email"]

    report = await recover_recorded_opt_outs(
        request=RecoverOptOutsRequest(
            workspace_id=lead.workspace_id,
            lead_ids=(lead.lead_id, control.lead_id),
            apply=True,
            reviewed_for_lifts=True,
        ),
        repository=PostgresOptOutRecoveryRepository(sessions),
    )
    assert report.changed == report.candidate == 1
    assert report.failed == report.unresolved == 0
    assert {item.lead_id: item.status for item in report.leads} == {
        lead.lead_id: RecoveryStatus.CHANGED,
        control.lead_id: RecoveryStatus.CLEAN,
    }
    assert await _lifecycle_snapshot(sessions, lead.workspace_id) == before
    recovered = await read_lead(sessions, lead)
    assert recovered.sms_opted_out is True
    assert await read_lead(sessions, control) == control

    for record, expected_lead, opted_out in ((lead, recovered, True), (control, control, False)):
        await _refresh_with_permissive_crm(sessions, record)
        payload = (await _get_lead_detail(sessions, record)).json()
        assert payload["status"] == "ok"
        api_lead = payload["lead"]
        assert api_lead["lead_id"] == str(record.lead_id)
        assert api_lead["lead_stage"] == "crm-refreshed"
        assert api_lead["sms_opted_out"] is opted_out
        assert api_lead["email_unsubscribed"] is False
        assert api_lead["do_not_contact"] is False
        assert api_lead["suppression_types"] == (["sms_opt_out"] if opted_out else [])
        assert api_lead["sendability"] == {
            "sms": {
                "channel": "sms",
                "sendable": not opted_out,
                "reasons": ["sms_opted_out"] if opted_out else [],
            },
            "email": {"channel": "email", "sendable": True, "reasons": []},
            "sendable_channels": ["email"] if opted_out else ["sms", "email"],
            "blocked_reasons": ["sms_opted_out"] if opted_out else [],
        }
        for field in (
            "latest_workflow",
            "latest_handoff",
            "workflow_transitions",
            "workflow_override_audits",
            "outbound_messages",
            "inbound_messages",
            "handoffs",
            "cadence_progress",
            "activity_log",
        ):
            assert payload[field] == before_payloads[record.lead_id][field], field
        assert await read_lead(sessions, record) == replace(
            expected_lead, lead_stage="crm-refreshed"
        )
        assert await _lifecycle_snapshot(sessions, lead.workspace_id) == before


async def _seed_lifecycle_history(
    session: AsyncSession,
    lead: CanonicalLeadRecord,
    state: WorkflowState,
    enrollment_status: str,
    reason: WorkflowTransitionReasonCode,
) -> LeadWorkflow:
    terminal = state in {WorkflowState.COMPLETED, WorkflowState.SUPPRESSED, WorkflowState.CLOSED}
    enrollment_id = uuid4()
    session.add(
        CampaignEnrollmentModel(
            campaign_enrollment_id=enrollment_id,
            workspace_id=lead.workspace_id,
            campaign_id=business_flow.CAMPAIGN_ID,
            campaign_version_id=business_flow.CAMPAIGN_VERSION_ID,
            lead_id=lead.lead_id,
            source="manual_admin",
            status=enrollment_status,
            eligible_at=business_flow.SYNC_TIME,
            enrolled_at=business_flow.ENROLL_TIME,
            started_at=business_flow.EXECUTE_TIME,
            ended_at=business_flow.INBOUND_TIME if terminal else None,
            created_by_user_id=business_flow.ACTOR_ID,
            reason_codes=[reason.value],
            created_at=business_flow.ENROLL_TIME,
            updated_at=business_flow.INBOUND_TIME,
        )
    )
    await session.flush()
    transition = transition_workflow(
        workflow=LeadWorkflow(
            workflow_id=uuid4(),
            temporal_workflow_id=f"synthetic-lifecycle-{lead.lead_id}",
            workspace_id=lead.workspace_id,
            campaign_enrollment_id=enrollment_id,
            campaign_id=business_flow.CAMPAIGN_ID,
            lead_id=lead.lead_id,
            state=WorkflowState.WAITING_FOR_RESPONSE,
            current_step_id=business_flow.STEP_ID,
            next_action_at=business_flow.INBOUND_TIME,
            logical_touch_count=1,
            ai_interaction_count=1,
            last_transition_at=business_flow.EXECUTE_TIME,
            state_version=2,
            created_at=business_flow.ENROLL_TIME,
            updated_at=business_flow.EXECUTE_TIME,
        ),
        to_state=state,
        reason_code=reason,
        transition_id=uuid4(),
        now=business_flow.INBOUND_TIME,
        actor_user_id=business_flow.ACTOR_ID,
        pause_reason=reason.value,
        metadata={"source": "synthetic-history"},
    )
    workflow = await PostgresLeadWorkflowRepository(session).save(transition.workflow)
    await PostgresWorkflowTransitionRepository(session).append(transition.transition)
    session.add(
        ConversationModel(
            conversation_id=business_flow.CONVERSATION_ID,
            workspace_id=lead.workspace_id,
            lead_id=lead.lead_id,
            campaign_id=workflow.campaign_id,
            workflow_id=workflow.workflow_id,
            status="closed" if terminal else state.value,
            ai_interaction_count=1,
            last_message_at=business_flow.INBOUND_TIME,
            created_at=business_flow.EXECUTE_TIME,
            updated_at=business_flow.INBOUND_TIME,
        )
    )
    # A classified, non-opt-out inbound history needs its real source-event join
    # and processing audit; missing audit is unresolved under contract N2.
    reply = suppression_event(
        lead, event_id="historical-reply", occurred_at=business_flow.INBOUND_TIME
    )
    reply.event_type = INBOUND_MESSAGE_RECEIVED_EVENT_TYPE
    reply.payload_redacted = {
        "processing_audit": {
            "classifier": {"status": "classified", "opt_out_detected": False},
            "decision": {
                "inbound_action": (
                    "human_handoff" if state is WorkflowState.HUMAN_HANDOFF else "continue_ai"
                ),
                "reply_route": None,
            },
        }
    }
    session.add(reply)
    await session.flush()
    inbound_body = (
        "Can an agent call me?"
        if state is WorkflowState.HUMAN_HANDOFF
        else "Thanks for the update."
    )
    session.add(
        InboundMessageModel(
            inbound_message_id=business_flow.INBOUND_MESSAGE_ID,
            workspace_id=lead.workspace_id,
            conversation_id=business_flow.CONVERSATION_ID,
            lead_id=lead.lead_id,
            channel="email",
            provider=reply.provider,
            provider_message_id="historical-inbound-message",
            external_event_id=reply.external_event_id,
            from_address_redacted="***",
            to_address_redacted="***",
            body=inbound_body,
            received_at=business_flow.INBOUND_TIME,
            processed_at=business_flow.INBOUND_TIME,
            classification_status="classified",
            created_at=business_flow.INBOUND_TIME,
        )
    )
    session.add(
        OutboundMessageModel(
            message_id=uuid4(),
            workspace_id=lead.workspace_id,
            lead_id=lead.lead_id,
            campaign_id=workflow.campaign_id,
            workflow_id=workflow.workflow_id,
            cadence_step_id=str(business_flow.STEP_ID),
            channel="email",
            status="sent",
            idempotency_key="historical-outbound-message",
            body="Are you still considering a move?",
            subject="Checking in",
            scheduled_for=business_flow.ENROLL_TIME,
            sent_at=business_flow.EXECUTE_TIME,
            provider_send_status="accepted",
            provider_name="sendgrid",
            provider_message_id="historical-provider-message",
            provider_attempt_count=1,
            created_at=business_flow.EXECUTE_TIME,
            updated_at=business_flow.EXECUTE_TIME,
        )
    )
    await session.flush()
    if state is WorkflowState.HUMAN_HANDOFF:
        session.add(
            HandoffModel(
                handoff_id=business_flow.HANDOFF_ID,
                workspace_id=lead.workspace_id,
                lead_id=lead.lead_id,
                campaign_id=workflow.campaign_id,
                workflow_id=workflow.workflow_id,
                conversation_id=business_flow.CONVERSATION_ID,
                inbound_message_id=business_flow.INBOUND_MESSAGE_ID,
                assigned_agent_user_id=business_flow.ACTOR_ID,
                assigned_agent_crm_id=lead.assigned_agent_crm_id,
                reason_code="human_requested",
                summary="Lead asked to speak with an agent.",
                latest_inbound_text=inbound_body,
                preferences={"next_action": "call"},
                status="notified",
                created_at=business_flow.INBOUND_TIME,
                notified_at=business_flow.INBOUND_TIME,
            )
        )
        await session.flush()
    return workflow


async def _lifecycle_snapshot(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
) -> dict[str, tuple[tuple[object, ...], ...]]:
    snapshot: dict[str, tuple[tuple[object, ...], ...]] = {}
    async with sessions() as session:
        await enable_postgres_service_access(session)
        for name in (
            "lead_workflows",
            "campaign_enrollments",
            "handoffs",
            "workflow_transitions",
            "outbound_messages",
            "inbound_messages",
            "conversations",
            "external_events",
        ):
            table = Base.metadata.tables[name]
            rows = await session.execute(
                select(table)
                .where(table.c.workspace_id == workspace_id)
                .order_by(*table.primary_key)
            )
            snapshot[name] = tuple(tuple(row) for row in rows)
    return snapshot


def _contactable_lead(lead: CanonicalLeadRecord) -> CanonicalLeadRecord:
    return replace(
        lead,
        primary_phone="+14155550161",
        has_phone=True,
        has_sms_capable_phone=True,
        phone_count=1,
        primary_email="lead-detail@example.test",
        has_email=True,
        email_count=1,
        sms_permission_status=ContactPermissionStatus.CONFIRMED,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        sms_opted_out=False,
        email_unsubscribed=False,
        do_not_contact=False,
        suppression_types=frozenset(),
        permission_evidence={},
    )


async def _refresh_with_permissive_crm(
    sessions: async_sessionmaker[AsyncSession],
    lead: CanonicalLeadRecord,
) -> None:
    # Use the clean pre-recovery record, not the recovered restrictions, as CRM input.
    snapshot = replace(lead, lead_stage="crm-refreshed")
    async with sessions() as session:
        await enable_postgres_service_access(session)
        refreshed = await refresh_lead_from_crm(
            workspace_id=lead.workspace_id,
            crm_provider=lead.crm_provider,
            crm_lead_id=lead.crm_lead_id,
            lead_refresh_source=FakeCanonicalLeadRefreshSource({lead.crm_lead_id: snapshot}),
            lead_repository=PostgresLeadRepository(session),
            now=NOW,
        )
        assert refreshed.status is CrmLeadRefreshStatus.REFRESHED
        await session.commit()


async def _get_lead_detail(
    sessions: async_sessionmaker[AsyncSession],
    lead: CanonicalLeadRecord,
) -> httpx.Response:
    actor = AuthenticatedActor(
        user_id=uuid4(),
        user_status=UserStatus.ACTIVE,
        active_role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
        active_workspace_id=lead.workspace_id,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=uuid4(),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )
    async with sessions() as session:
        await enable_postgres_service_access(session)
        bundle = await get_lead_read_bundle(session)
        app = create_app()
        app.dependency_overrides[get_workspace_actor] = lambda: actor
        app.dependency_overrides[get_lead_read_bundle] = lambda: bundle
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            url = f"/api/v1/workspaces/{lead.workspace_id}/leads/{lead.lead_id}"
            response = await client.get(url)
            assert response.status_code == 200
            repeated = await client.get(url)
            assert repeated.status_code == 200
            assert repeated.json() == response.json()
            return response