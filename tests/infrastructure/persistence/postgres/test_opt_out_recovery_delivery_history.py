from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.use_cases.recover_recorded_opt_outs import (
    RecoverOptOutsRequest,
    RecoveryStatus,
    recover_recorded_opt_outs,
)
from app.core.database import enable_postgres_service_access
from app.domain.leads import CanonicalLeadRecord
from app.infrastructure.persistence.postgres.models import (
    OutboundMessageModel,
    ProviderMessageEventModel,
)
from app.infrastructure.persistence.postgres.opt_out_recovery import (
    PostgresOptOutRecoveryRepository,
)
from tests.infrastructure.persistence.postgres.test_opt_out_recovery import NOW, read_lead
from tests.infrastructure.persistence.postgres.test_opt_out_recovery import (
    recovery_case as recovery_case,
)


@pytest.mark.parametrize("error_code", [None, "21614", "21610"])
async def test_delivery_history_never_invents_opt_out_and_flags_unverified_unsubscribe(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    error_code: str | None,
) -> None:
    sessions, lead = recovery_case
    message_id, event_id = uuid4(), uuid4()
    async with sessions() as session:
        await enable_postgres_service_access(session)
        session.add(OutboundMessageModel(
            message_id=message_id, workspace_id=lead.workspace_id, lead_id=lead.lead_id,
            campaign_id=uuid4(), cadence_step_id="synthetic-step", channel="sms", status="sent",
            idempotency_key="synthetic-delivery", body="Synthetic message",
            provider_send_status="accepted", provider_name="twilio",
            provider_message_id="SMsynthetic",
            created_at=NOW, updated_at=NOW,
        ))
        await session.flush()
        session.add(ProviderMessageEventModel(
            provider_event_id=event_id, workspace_id=lead.workspace_id, provider="twilio",
            provider_message_id="SMsynthetic", outbound_message_id=message_id,
            external_provider_event_id="SMsynthetic:undelivered", event_type="undelivered",
            status="undelivered", received_at=NOW,
            payload_redacted={"message_status": "undelivered", "error_code": error_code},
            created_at=NOW,
        ))
        await session.commit()
    report = await recover_recorded_opt_outs(
        request=RecoverOptOutsRequest(
            workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=True,
            reviewed_for_lifts=True,
        ), repository=PostgresOptOutRecoveryRepository(sessions),
    )
    assert report.changed == report.would_change == report.failed == 0
    if error_code == "21610":
        # The baseline callback writer did not record a consent decision. Do not
        # introduce carrier policy in this repair; keep the evidence for review.
        assert report.unresolved == 1
        assert report.leads[0].reasons == ("provider_unsubscribe_requires_review",)
        assert report.leads[0].references == (f"provider_message_events:{event_id}",)
    else:
        assert report.leads[0].status is RecoveryStatus.CLEAN
    assert await read_lead(sessions, lead) == lead