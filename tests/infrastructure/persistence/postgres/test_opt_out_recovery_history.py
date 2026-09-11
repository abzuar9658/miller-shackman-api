from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.use_cases.process_inbound_message_event import (
    InboundMessageEvent,
    process_inbound_message_event,
)
from app.application.use_cases.recover_recorded_opt_outs import (
    RecoverOptOutsRequest,
    RecoveryStatus,
    recover_recorded_opt_outs,
)
from app.core.database import enable_postgres_service_access
from app.domain.compliance import ContactChannel, SuppressionType
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresConversationRepository,
    PostgresConversationSummaryRepository,
    PostgresHandoffRepository,
    PostgresInboundMessageRepository,
)
from app.infrastructure.persistence.postgres.crm_sync_repository import (
    PostgresExternalEventRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import (
    ExternalEventModel,
    InboundMessageModel,
    LeadModel,
)
from app.infrastructure.persistence.postgres.opt_out_recovery import (
    PostgresOptOutRecoveryRepository,
)
from tests.application.use_cases.test_process_inbound_message_event import (
    _classification_json,
    _FakeLLMClientForContinuation,
    _reply_route_json,
)
from tests.infrastructure.persistence.postgres.test_opt_out_recovery import (
    NOW,
    ORIGINAL_AT,
    read_lead,
    suppression_event,
)
from tests.infrastructure.persistence.postgres.test_opt_out_recovery import (
    recovery_case as recovery_case,
)


async def record_inbound_reply(
    sessions: async_sessionmaker[AsyncSession],
    lead: CanonicalLeadRecord,
    origin: str,
) -> _FakeLLMClientForContinuation:
    channel = ContactChannel.EMAIL if origin == "classified" else ContactChannel.SMS
    provider = "sendgrid" if channel is ContactChannel.EMAIL else "twilio"
    llm = _FakeLLMClientForContinuation(
        classification_text=_classification_json(
            intent="opt_out" if origin == "classified" else "general_reply",
            opt_out_detected=origin == "classified", summary_text="Synthetic reply.",
        ),
        draft_text="must not draft",
        reply_route_text=_reply_route_json(
            decision="suppressed", continue_percent=5, human_handoff_percent=10,
            suppressed_percent=85,
        ),
    )
    async with sessions() as session:
        await enable_postgres_service_access(session)
        outcome = await process_inbound_message_event(
            event=InboundMessageEvent(
                workspace_id=lead.workspace_id, provider=provider,
                provider_event_id="inbound-original", provider_message_id="message-id-is-different",
                crm_provider=CRMProvider.FOLLOW_UP_BOSS, crm_lead_id=lead.crm_lead_id,
                channel=channel, body="STOP" if origin == "hard-keyword" else "No more outreach.",
                received_at=ORIGINAL_AT,
            ),
            lead_repository=PostgresLeadRepository(session),
            external_event_repository=PostgresExternalEventRepository(session),
            conversation_repository=PostgresConversationRepository(session),
            inbound_message_repository=PostgresInboundMessageRepository(session),
            conversation_summary_repository=PostgresConversationSummaryRepository(session),
            handoff_repository=PostgresHandoffRepository(session), llm_client=llm, now=NOW,
        )
        assert outcome.inbound_action is not None
        assert outcome.inbound_action.value == "suppress"
        await session.commit()
    return llm


async def erase_recorded_restrictions(
    sessions: async_sessionmaker[AsyncSession], lead: CanonicalLeadRecord,
) -> None:
    async with sessions() as session:
        await enable_postgres_service_access(session)
        # Simulate the old CRM whole-record overwrite, not an authorized consent lift.
        await session.execute(update(LeadModel).where(
            LeadModel.workspace_id == lead.workspace_id, LeadModel.lead_id == lead.lead_id,
        ).values(sms_opted_out=False, email_unsubscribed=False,
                 suppression_types=[], permission_evidence={}))
        await session.commit()


@pytest.mark.parametrize("origin", ["hard-keyword", "classified", "reply-route"])
async def test_recovery_uses_real_inbound_processing_audit_not_body_or_message_id(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    origin: str,
) -> None:
    sessions, lead = recovery_case
    llm = await record_inbound_reply(sessions, lead, origin)
    channel = ContactChannel.EMAIL if origin == "classified" else ContactChannel.SMS
    before_erasure = await read_lead(sessions, lead)
    assert before_erasure.sms_opted_out is (channel is ContactChannel.SMS)
    assert before_erasure.email_unsubscribed is (channel is ContactChannel.EMAIL)
    await erase_recorded_restrictions(sessions, lead)
    assert await read_lead(sessions, lead) == lead
    llm_calls_before_recovery = len(llm.requests)
    report = await recover_recorded_opt_outs(
        request=RecoverOptOutsRequest(
            workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=True,
            reviewed_for_lifts=True,
        ), repository=PostgresOptOutRecoveryRepository(sessions),
    )
    assert report.changed == report.candidate == 1
    assert report.unresolved == report.failed == 0
    saved = await read_lead(sessions, lead)
    if channel is ContactChannel.SMS:
        assert saved.suppression_types == frozenset({SuppressionType.SMS_OPT_OUT})
        assert saved.permission_evidence == {
            "sms_opt_out_source_provider": "twilio",
            "sms_opt_out_source_event_id": "inbound-original",
            "sms_opt_out_occurred_at": "2026-08-01T10:00:00+00:00",
        }
    else:
        assert saved.suppression_types == frozenset({SuppressionType.EMAIL_UNSUBSCRIBED})
        assert saved.permission_evidence == {
            "email_unsubscribed_source_provider": "sendgrid",
            "email_unsubscribed_source_event_id": "inbound-original",
            "email_unsubscribed_occurred_at": "2026-08-01T10:00:00+00:00",
        }
    assert len(llm.requests) == llm_calls_before_recovery


@pytest.mark.parametrize("invalid_occurrence", [None, 123])
async def test_recovery_reports_malformed_provenance_and_continues_other_scoped_leads(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    invalid_occurrence: int | None,
) -> None:
    sessions, lead = recovery_case
    other = replace(lead, lead_id=uuid4(), crm_lead_id="other-recovery-person")
    async with sessions() as session:
        await enable_postgres_service_access(session)
        # Old JSON may not satisfy today's canonical Mapping[str, str] annotation.
        await session.execute(update(LeadModel).where(
            LeadModel.workspace_id == lead.workspace_id, LeadModel.lead_id == lead.lead_id,
        ).values(sms_opted_out=True, permission_evidence={
            "sms_opt_out_source_provider": "twilio",
            "sms_opt_out_source_event_id": "malformed-original",
            "sms_opt_out_occurred_at": invalid_occurrence,
        }))
        await PostgresLeadRepository(session).upsert(other)
        session.add(suppression_event(other))
        await session.commit()
    before = await read_lead(sessions, lead)
    report = await recover_recorded_opt_outs(
        request=RecoverOptOutsRequest(
            workspace_id=lead.workspace_id, lead_ids=(lead.lead_id, other.lead_id),
            apply=True, reviewed_for_lifts=True,
        ), repository=PostgresOptOutRecoveryRepository(sessions),
    )
    assert report.unresolved == report.changed == 1
    assert report.failed == 0
    assert report.leads[0].reasons == ("partial_platform_provenance",)
    assert await read_lead(sessions, lead) == before
    assert (await read_lead(sessions, other)).sms_opted_out is True


@pytest.mark.parametrize("missing_link", ["deleted-row", "repointed-row"])
async def test_recovery_inventory_holds_retained_inbound_event_without_matching_message(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    missing_link: str,
) -> None:
    sessions, lead = recovery_case
    await record_inbound_reply(sessions, lead, "hard-keyword")
    await erase_recorded_restrictions(sessions, lead)
    async with sessions() as session:
        await enable_postgres_service_access(session)
        inbound = (await session.scalars(select(InboundMessageModel).where(
            InboundMessageModel.workspace_id == lead.workspace_id,
        ))).one()
        original_event_id = inbound.external_event_id
        if missing_link == "deleted-row":
            await session.delete(inbound)
        else:
            other = await PostgresLeadRepository(session).upsert(replace(
                lead, lead_id=uuid4(), crm_lead_id="unrelated-message-owner",
            ))
            inbound.external_event_id = None
            inbound.lead_id = other.lead_id
        await session.commit()
    report = await recover_recorded_opt_outs(
        request=RecoverOptOutsRequest(
            workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=True,
            reviewed_for_lifts=True,
        ), repository=PostgresOptOutRecoveryRepository(sessions),
    )
    assert report.unresolved == 1
    assert report.changed == report.failed == report.would_change == 0
    assert report.leads[0].reasons == ("missing_inbound_message",)
    assert report.leads[0].references == (f"external_events:{original_event_id}",)
    assert await read_lead(sessions, lead) == lead


@pytest.mark.parametrize("restriction_active", [False, True])
async def test_recovery_holds_provenance_that_names_a_recorded_non_opt_out_reply(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    restriction_active: bool,
) -> None:
    sessions, lead = recovery_case
    await record_inbound_reply(sessions, lead, "hard-keyword")
    async with sessions() as session:
        await enable_postgres_service_access(session)
        event = (await session.scalars(select(ExternalEventModel).where(
            ExternalEventModel.workspace_id == lead.workspace_id,
        ))).one()
        event_id = event.external_event_id
        # Contradictory retained data: the lead cites this event as a STOP, but
        # its saved application decision explicitly records an ordinary reply.
        event.payload_redacted = {"processing_audit": {
            "classifier": {"status": "classified", "opt_out_detected": False},
            "decision": {"inbound_action": "continue_ai", "reply_route": None},
        }}
        await session.execute(update(LeadModel).where(
            LeadModel.workspace_id == lead.workspace_id, LeadModel.lead_id == lead.lead_id,
        ).values(sms_opted_out=restriction_active,
                 suppression_types=["sms_opt_out"] if restriction_active else []))
        await session.commit()
    before = await read_lead(sessions, lead)
    report = await recover_recorded_opt_outs(
        request=RecoverOptOutsRequest(
            workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=True,
            reviewed_for_lifts=True,
        ), repository=PostgresOptOutRecoveryRepository(sessions),
    )
    assert report.unresolved == 1
    assert report.changed == report.already_correct == report.failed == 0
    assert report.leads[0].reasons == ("conflicting_platform_provenance",)
    assert f"external_events:{event_id}" in report.leads[0].references
    assert await read_lead(sessions, lead) == before


@pytest.mark.parametrize("conflict", [None, "channel", "occurrence"])
async def test_recovery_deduplicates_matching_evidence_but_holds_conflicting_source_facts(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    conflict: str | None,
) -> None:
    sessions, lead = recovery_case
    await record_inbound_reply(sessions, lead, "hard-keyword")
    await erase_recorded_restrictions(sessions, lead)
    async with sessions() as session:
        await enable_postgres_service_access(session)
        inbound = (await session.scalars(select(InboundMessageModel).where(
            InboundMessageModel.workspace_id == lead.workspace_id,
        ))).one()
        session.add(InboundMessageModel(
            inbound_message_id=uuid4(), workspace_id=lead.workspace_id,
            conversation_id=inbound.conversation_id, lead_id=lead.lead_id,
            channel="email" if conflict == "channel" else "sms", provider="twilio",
            provider_message_id="duplicate-retained-message",
            external_event_id=inbound.external_event_id,
            from_address_redacted="***", to_address_redacted="***", body="Synthetic history",
            received_at=NOW if conflict == "occurrence" else ORIGINAL_AT,
            processed_at=NOW, classification_status="classified", created_at=NOW,
        ))
        await session.commit()
    report = await recover_recorded_opt_outs(
        request=RecoverOptOutsRequest(
            workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=True,
            reviewed_for_lifts=True,
        ), repository=PostgresOptOutRecoveryRepository(sessions),
    )
    saved = await read_lead(sessions, lead)
    if conflict is not None:
        assert report.unresolved == 1
        assert report.changed == report.failed == 0
        assert report.leads[0].reasons == ("conflicting_event_provenance",)
        assert saved == lead
    else:
        assert report.candidate == report.changed == 1
        assert report.unresolved == report.failed == 0
        assert saved.sms_opted_out is True
        assert saved.email_unsubscribed is False
        assert saved.permission_evidence["sms_opt_out_source_event_id"] == "inbound-original"
        assert saved.permission_evidence["sms_opt_out_occurred_at"] == "2026-08-01T10:00:00+00:00"


@pytest.mark.parametrize(
    ("variant", "reason"),
    [
        ("missing-source", "missing_inbound_source_event"),
        ("missing-audit", "missing_inbound_processing_audit"),
        ("provider-mismatch", "conflicting_inbound_identity"),
        ("crm-mismatch", "conflicting_inbound_identity"),
        ("pending", "unverified_inbound_processing"),
        ("missing-flag", "invalid_inbound_processing_audit"),
        ("string-flag", "invalid_inbound_processing_audit"),
        ("conflicting-decision", "conflicting_inbound_processing_audit"),
        ("intent-only", "unverified_inbound_suppression"),
        ("ordinary-reply", None),
    ],
)
async def test_recovery_never_guesses_from_incomplete_inbound_history(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    variant: str,
    reason: str | None,
) -> None:
    sessions, lead = recovery_case
    await record_inbound_reply(sessions, lead, "hard-keyword")
    await erase_recorded_restrictions(sessions, lead)
    async with sessions() as session:
        await enable_postgres_service_access(session)
        event = (await session.scalars(select(ExternalEventModel).where(
            ExternalEventModel.workspace_id == lead.workspace_id,
        ))).one()
        inbound = (await session.scalars(select(InboundMessageModel).where(
            InboundMessageModel.workspace_id == lead.workspace_id,
        ))).one()
        if variant == "missing-source":
            inbound.external_event_id = None
        elif variant == "missing-audit":
            event.payload_redacted = {}
        elif variant == "provider-mismatch":
            inbound.provider = "different-provider"
        elif variant == "crm-mismatch":
            event.crm_lead_id = "different-lead"
        elif variant == "pending":
            inbound.classification_status = "pending"
        else:
            classifier: dict[str, object] = {"status": "classified", "opt_out_detected": True}
            decision = {"inbound_action": "suppress", "reply_route": None}
            if variant == "missing-flag":
                classifier.pop("opt_out_detected")
            elif variant == "string-flag":
                classifier["opt_out_detected"] = "true"
            elif variant == "conflicting-decision":
                decision["inbound_action"] = "continue_ai"
            else:
                classifier["opt_out_detected"] = False
                if variant == "intent-only":
                    classifier["intent"] = "opt_out"
                else:
                    decision["inbound_action"] = "continue_ai"
            event.payload_redacted = {"processing_audit": {
                "classifier": classifier, "decision": decision,
            }}
        await session.commit()
    report = await recover_recorded_opt_outs(
        request=RecoverOptOutsRequest(
            workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=True,
            reviewed_for_lifts=True,
        ), repository=PostgresOptOutRecoveryRepository(sessions),
    )
    assert report.changed == report.would_change == report.failed == 0
    if reason is not None:
        assert report.unresolved == 1
        assert reason in report.leads[0].reasons
    else:
        # A recorded non-opt-out reply is not suppression evidence, even with STOP in its body.
        assert report.leads[0].status is RecoveryStatus.CLEAN
    assert await read_lead(sessions, lead) == lead