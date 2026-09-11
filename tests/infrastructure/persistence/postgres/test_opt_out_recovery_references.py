from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.use_cases.recover_recorded_opt_outs import (
    RecoverOptOutsRequest,
    RecoveryStatus,
    recover_recorded_opt_outs,
)
from app.core.database import enable_postgres_service_access
from app.domain.leads import CanonicalLeadRecord
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import ExternalEventModel, InboundMessageModel
from app.infrastructure.persistence.postgres.opt_out_recovery import (
    PostgresOptOutRecoveryRepository,
)
from tests.infrastructure.persistence.postgres.test_opt_out_lead_detail import _lifecycle_snapshot
from tests.infrastructure.persistence.postgres.test_opt_out_recovery import read_lead
from tests.infrastructure.persistence.postgres.test_opt_out_recovery import (
    recovery_case as recovery_case,
)
from tests.infrastructure.persistence.postgres.test_opt_out_recovery_history import (
    erase_recorded_restrictions,
    record_inbound_reply,
)
from tests.infrastructure.persistence.postgres.test_opt_out_recovery_provenance import (
    event_snapshot,
)


async def _recorded_inbound(
    session: AsyncSession, lead: CanonicalLeadRecord,
) -> InboundMessageModel:
    return (await session.scalars(select(InboundMessageModel).where(
        InboundMessageModel.workspace_id == lead.workspace_id,
        InboundMessageModel.lead_id == lead.lead_id,
    ))).one()


async def test_recovery_reports_local_provenance_on_preview_apply_and_repeat(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
) -> None:
    sessions, lead = recovery_case
    lead = replace(lead, permission_evidence={
        "sms_opt_out_source_provider": "twilio",
        "sms_opt_out_source_event_id": "retained-local-stop",
        "sms_opt_out_occurred_at": "2026-08-01T12:00:00+02:00",
    })
    async with sessions() as session:
        await enable_postgres_service_access(session)
        await PostgresLeadRepository(session).upsert(lead)
        await session.commit()
    for apply, status in (
        (False, RecoveryStatus.WOULD_CHANGE),
        (True, RecoveryStatus.CHANGED),
        (True, RecoveryStatus.ALREADY_CORRECT),
    ):
        report = await recover_recorded_opt_outs(
            request=RecoverOptOutsRequest(
                workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=apply,
                reviewed_for_lifts=True,
            ), repository=PostgresOptOutRecoveryRepository(sessions),
        )
        assert report.leads[0].status is status
        assert report.leads[0].references == (f"leads:{lead.lead_id}:sms_opt_out",)
        saved = await read_lead(sessions, lead)
        assert saved.sms_opted_out is apply
        assert saved.permission_evidence == lead.permission_evidence


@pytest.mark.parametrize("origin", ["hard-keyword", "classified", "reply-route"])
async def test_recovery_reports_both_inbound_and_source_rows_through_repeat(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    origin: str,
) -> None:
    sessions, lead = recovery_case
    llm = await record_inbound_reply(sessions, lead, origin)
    original = await read_lead(sessions, lead)
    await erase_recorded_restrictions(sessions, lead)
    async with sessions() as session:
        await enable_postgres_service_access(session)
        inbound = await _recorded_inbound(session, lead)
        event_id = inbound.external_event_id
        assert event_id is not None
        duplicate_id = uuid4()
        session.add(InboundMessageModel(
            inbound_message_id=duplicate_id, workspace_id=lead.workspace_id,
            conversation_id=inbound.conversation_id, lead_id=lead.lead_id,
            channel=inbound.channel, provider=inbound.provider,
            provider_message_id="duplicate-inbound-reference", external_event_id=event_id,
            from_address_redacted=inbound.from_address_redacted,
            to_address_redacted=inbound.to_address_redacted,
            body="Synthetic duplicate retained reply.", received_at=inbound.received_at,
            processed_at=inbound.processed_at, classification_status=inbound.classification_status,
            created_at=inbound.created_at,
        ))
        inbound_ids = (inbound.inbound_message_id, duplicate_id)
        await session.commit()
    original_history = await _lifecycle_snapshot(sessions, lead.workspace_id)
    assert len(original_history["inbound_messages"]) == 2
    llm_calls_before_recovery = len(llm.requests)
    kind = "email_unsubscribed" if origin == "classified" else "sms_opt_out"
    for apply, status in (
        (False, RecoveryStatus.WOULD_CHANGE),
        (True, RecoveryStatus.CHANGED),
        (True, RecoveryStatus.ALREADY_CORRECT),
    ):
        report = await recover_recorded_opt_outs(
            request=RecoverOptOutsRequest(
                workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=apply,
                reviewed_for_lifts=True,
            ), repository=PostgresOptOutRecoveryRepository(sessions),
        )
        expected = {f"inbound_messages:{inbound_id}" for inbound_id in inbound_ids}
        expected.add(f"external_events:{event_id}")
        if status is RecoveryStatus.ALREADY_CORRECT:
            expected.add(f"leads:{lead.lead_id}:{kind}")
        assert report.leads[0].status is status
        assert report.leads[0].references == tuple(sorted(expected))
        assert await read_lead(sessions, lead) == (original if apply else lead)
        assert await _lifecycle_snapshot(sessions, lead.workspace_id) == original_history
        assert len(llm.requests) == llm_calls_before_recovery


@pytest.mark.parametrize("source_problem", ["conflicting-crm", "missing-link"])
async def test_recovery_retains_partial_local_and_source_refs_on_early_unresolved(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    source_problem: str,
) -> None:
    sessions, lead = recovery_case
    await record_inbound_reply(sessions, lead, "hard-keyword")
    await erase_recorded_restrictions(sessions, lead)
    lead = replace(lead, permission_evidence={
        "sms_opt_out_source_provider": "twilio",
        "sms_opt_out_source_event_id": "inbound-original",
    })
    async with sessions() as session:
        await enable_postgres_service_access(session)
        inbound = await _recorded_inbound(session, lead)
        inbound_id = inbound.inbound_message_id
        event_id = inbound.external_event_id
        assert event_id is not None
        event = await session.get(ExternalEventModel, event_id)
        assert event is not None
        if source_problem == "conflicting-crm":
            event.crm_lead_id = "conflicting-retained-crm"
        else:
            # Both original rows remain, but the retained message lost its source link.
            inbound.external_event_id = None
        await PostgresLeadRepository(session).upsert(lead)
        await session.commit()
    original_event = await event_snapshot(sessions, lead.workspace_id, event_id)
    original_history = await _lifecycle_snapshot(sessions, lead.workspace_id)
    expected_reasons = (
        ("conflicting_inbound_identity",) if source_problem == "conflicting-crm"
        else ("missing_inbound_message", "missing_inbound_source_event")
    )
    for apply in (False, True, True):
        report = await recover_recorded_opt_outs(
            request=RecoverOptOutsRequest(
                workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=apply,
                reviewed_for_lifts=True,
            ), repository=PostgresOptOutRecoveryRepository(sessions),
        )
        assert report.unresolved == report.candidate == 1
        assert report.changed == report.would_change == report.failed == 0
        # These adapter errors return before the planner validates the partial tuple.
        assert report.leads[0].reasons == expected_reasons
        assert report.leads[0].references == tuple(sorted((
            f"leads:{lead.lead_id}:sms_opt_out", f"external_events:{event_id}",
            f"inbound_messages:{inbound_id}",
        )))
        assert await read_lead(sessions, lead) == lead
        assert await event_snapshot(sessions, lead.workspace_id, event_id) == original_event
        assert await _lifecycle_snapshot(sessions, lead.workspace_id) == original_history