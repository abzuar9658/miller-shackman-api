from dataclasses import replace
from uuid import UUID, uuid4

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
from app.infrastructure.persistence.postgres.models import ExternalEventModel
from app.infrastructure.persistence.postgres.opt_out_recovery import (
    PostgresOptOutRecoveryRepository,
)
from tests.infrastructure.persistence.postgres.test_opt_out_recovery import (
    read_lead,
    suppression_event,
)
from tests.infrastructure.persistence.postgres.test_opt_out_recovery import (
    recovery_case as recovery_case,
)


async def event_snapshot(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, event_id: UUID,
) -> dict[str, object]:
    async with sessions() as session:
        await enable_postgres_service_access(session)
        result = await session.execute(select(ExternalEventModel.__table__).where(
            ExternalEventModel.workspace_id == workspace_id,
            ExternalEventModel.external_event_id == event_id,
        ))
        return dict(result.mappings().one())


@pytest.mark.parametrize("apply", [False, True])
async def test_recovery_holds_provenance_referencing_another_leads_event(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    apply: bool,
) -> None:
    sessions, lead = recovery_case
    other = replace(lead, lead_id=uuid4(), crm_lead_id="actual-event-owner")
    lead = replace(lead, permission_evidence={
        "sms_opt_out_source_provider": "follow_up_boss",
        "sms_opt_out_source_event_id": "another-leads-stop",
        "sms_opt_out_occurred_at": "2026-08-01T10:00:00+00:00",
    })
    event = suppression_event(other, event_id="another-leads-stop")
    async with sessions() as session:
        await enable_postgres_service_access(session)
        await PostgresLeadRepository(session).upsert(lead)
        await PostgresLeadRepository(session).upsert(other)
        session.add(event)
        await session.commit()
    original_event = await event_snapshot(sessions, lead.workspace_id, event.external_event_id)

    report = await recover_recorded_opt_outs(
        request=RecoverOptOutsRequest(
            workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=apply,
            reviewed_for_lifts=True,
        ), repository=PostgresOptOutRecoveryRepository(sessions),
    )

    assert report.unresolved == report.candidate == 1
    assert report.changed == report.would_change == report.failed == 0
    assert report.leads[0].status is RecoveryStatus.UNRESOLVED
    assert report.leads[0].reasons == ("conflicting_event_identity",)
    assert f"external_events:{event.external_event_id}" in report.leads[0].references
    assert f"leads:{lead.lead_id}:sms_opt_out" in report.leads[0].references
    assert await read_lead(sessions, lead) == lead
    assert await read_lead(sessions, other) == other
    assert await event_snapshot(
        sessions, lead.workspace_id, event.external_event_id,
    ) == original_event


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize(
    "email_occurred_at",
    ["2026-08-01T12:00:00+02:00", "2026-08-02T10:00:00+00:00"],
    ids=["same-instant", "different-instant"],
)
async def test_recovery_holds_contradictory_local_provenance_without_history(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    apply: bool,
    email_occurred_at: str,
) -> None:
    sessions, lead = recovery_case
    lead = replace(lead, permission_evidence={
        "sms_opt_out_source_provider": "twilio",
        "sms_opt_out_source_event_id": "one-source-two-channels",
        "sms_opt_out_occurred_at": "2026-08-01T10:00:00+00:00",
        "email_unsubscribed_source_provider": "twilio",
        "email_unsubscribed_source_event_id": "one-source-two-channels",
        "email_unsubscribed_occurred_at": email_occurred_at,
    })
    async with sessions() as session:
        await enable_postgres_service_access(session)
        await PostgresLeadRepository(session).upsert(lead)
        await session.commit()

    report = await recover_recorded_opt_outs(
        request=RecoverOptOutsRequest(
            workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=apply,
            reviewed_for_lifts=True,
        ), repository=PostgresOptOutRecoveryRepository(sessions),
    )

    assert report.unresolved == report.candidate == 1
    assert report.changed == report.would_change == report.failed == 0
    assert report.leads[0].reasons == ("conflicting_platform_provenance",)
    assert report.leads[0].references == tuple(sorted((
        f"leads:{lead.lead_id}:sms_opt_out", f"leads:{lead.lead_id}:email_unsubscribed",
    )))
    assert await read_lead(sessions, lead) == lead