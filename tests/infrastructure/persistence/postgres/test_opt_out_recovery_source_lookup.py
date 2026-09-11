from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.use_cases.recover_recorded_opt_outs import (
    RecoverOptOutsRequest,
    RecoveryStatus,
    recover_recorded_opt_outs,
)
from app.core.database import enable_postgres_service_access
from app.domain.compliance import SuppressionType
from app.domain.leads import CanonicalLeadRecord
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import WorkspaceModel
from app.infrastructure.persistence.postgres.opt_out_recovery import (
    PostgresOptOutRecoveryRepository,
)
from tests.infrastructure.persistence.postgres.test_opt_out_lead_detail import _lifecycle_snapshot
from tests.infrastructure.persistence.postgres.test_opt_out_recovery import (
    NOW,
    ORIGINAL_AT,
    read_lead,
    suppression_event,
)
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
from tests.infrastructure.persistence.postgres.test_opt_out_recovery_references import (
    _recorded_inbound,
)


async def test_recovery_holds_local_provenance_referencing_another_leads_real_inbound(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
) -> None:
    sessions, lead = recovery_case
    other = replace(lead, lead_id=uuid4(), crm_lead_id="actual-inbound-owner")
    async with sessions() as session:
        await enable_postgres_service_access(session)
        await PostgresLeadRepository(session).upsert(other)
        await session.commit()
    llm = await record_inbound_reply(sessions, other, "hard-keyword")
    other = await read_lead(sessions, other)
    # Only ownership differs: copy the actual writer's provider, event ID and instant.
    lead = replace(lead, permission_evidence=dict(other.permission_evidence))
    async with sessions() as session:
        await enable_postgres_service_access(session)
        await PostgresLeadRepository(session).upsert(lead)
        inbound = await _recorded_inbound(session, other)
        inbound_id = inbound.inbound_message_id
        event_id = inbound.external_event_id
        assert event_id is not None
        await session.commit()
    original_event = await event_snapshot(sessions, lead.workspace_id, event_id)
    assert original_event["lead_id"] == other.lead_id
    assert original_event["crm_lead_id"] == other.crm_lead_id != lead.crm_lead_id
    original_history = await _lifecycle_snapshot(sessions, lead.workspace_id)
    llm_calls_before_recovery = len(llm.requests)

    for apply in (False, True, True):
        report = await recover_recorded_opt_outs(
            request=RecoverOptOutsRequest(
                workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=apply,
                reviewed_for_lifts=True,
            ), repository=PostgresOptOutRecoveryRepository(sessions),
        )
        assert report.unresolved == report.candidate == 1
        assert report.changed == report.would_change == report.failed == 0
        assert report.leads[0].reasons == ("conflicting_inbound_identity",)
        assert report.leads[0].references == tuple(sorted((
            f"leads:{lead.lead_id}:sms_opt_out", f"external_events:{event_id}",
            f"inbound_messages:{inbound_id}",
        )))
        assert await read_lead(sessions, lead) == lead
        assert await read_lead(sessions, other) == other
        assert await event_snapshot(sessions, lead.workspace_id, event_id) == original_event
        assert await _lifecycle_snapshot(sessions, lead.workspace_id) == original_history
        assert len(llm.requests) == llm_calls_before_recovery


@pytest.mark.parametrize(
    ("variant", "reason"),
    [
        ("exact-orphan", None),
        ("wrong-crm-id", "conflicting_event_identity"),
        ("null-crm-id", "conflicting_event_identity"),
        ("pending", "unverified_suppression_event"),
        ("processed-orphan", "unverified_suppression_event"),
        ("wrong-reason", "unverified_suppression_event"),
        ("bare-kind", "unverified_suppression_event"),
        ("unrelated-type", "unverified_suppression_event"),
    ],
)
async def test_recovery_validates_referenced_orphan_identity_status_and_exact_type(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    variant: str,
    reason: str | None,
) -> None:
    sessions, lead = recovery_case
    lead = replace(lead, permission_evidence={
        "sms_opt_out_source_provider": "follow_up_boss",
        "sms_opt_out_source_event_id": "referenced-orphan",
        "sms_opt_out_occurred_at": "2026-08-01T12:00:00+02:00",
    })
    event = suppression_event(lead, event_id="referenced-orphan")
    event.lead_id = None
    event.status = "ignored"
    event.failure_reason = "lead_not_found"
    if variant == "wrong-crm-id":
        event.crm_lead_id = "different-retained-crm"
    elif variant == "null-crm-id":
        event.crm_lead_id = None
    elif variant == "pending":
        event.status = "pending"
        event.processed_at = None
    elif variant == "processed-orphan":
        event.status = "processed"
    elif variant == "wrong-reason":
        event.failure_reason = "unsupported_provider"
    elif variant == "bare-kind":
        event.event_type = "sms_opt_out"
    elif variant == "unrelated-type":
        event.event_type = "lead.updated"
    async with sessions() as session:
        await enable_postgres_service_access(session)
        await PostgresLeadRepository(session).upsert(lead)
        session.add(event)
        await session.commit()
    original_event = await event_snapshot(sessions, lead.workspace_id, event.external_event_id)
    original_history = await _lifecycle_snapshot(sessions, lead.workspace_id)
    repaired = replace(
        lead, sms_opted_out=True, suppression_types=frozenset({SuppressionType.SMS_OPT_OUT}),
    )

    for apply, success_status in (
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
        expected_status = success_status if reason is None else RecoveryStatus.UNRESOLVED
        assert report.leads[0].status is expected_status
        assert report.candidate == 1
        assert report.failed == 0
        assert report.leads[0].reasons == (() if reason is None else (reason,))
        assert report.leads[0].references == tuple(sorted((
            f"leads:{lead.lead_id}:sms_opt_out", f"external_events:{event.external_event_id}",
        )))
        assert await read_lead(sessions, lead) == (repaired if apply and reason is None else lead)
        assert await event_snapshot(
            sessions, lead.workspace_id, event.external_event_id,
        ) == original_event
        assert await _lifecycle_snapshot(sessions, lead.workspace_id) == original_history


@pytest.mark.parametrize("source_kind", ["suppression", "inbound"])
async def test_recovery_ignores_same_event_id_in_other_provider_and_workspace(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    source_kind: str,
) -> None:
    sessions, lead = recovery_case
    other_provider = replace(lead, lead_id=uuid4(), crm_lead_id="other-provider-owner")
    other_workspace = replace(lead, workspace_id=uuid4(), lead_id=uuid4())
    lead = replace(lead, permission_evidence={
        "sms_opt_out_source_provider": "twilio",
        "sms_opt_out_source_event_id": "inbound-original",
        "sms_opt_out_occurred_at": "2026-08-01T12:00:00+02:00",
    })
    async with sessions() as session:
        await enable_postgres_service_access(session)
        session.add(WorkspaceModel(
            workspace_id=other_workspace.workspace_id, name="Other synthetic source workspace",
            status="active", default_timezone="UTC", created_at=NOW, updated_at=NOW,
        ))
        await session.flush()
        for record in (lead, other_provider, other_workspace):
            await PostgresLeadRepository(session).upsert(record)
        if source_kind == "suppression":
            session.add_all([
                suppression_event(
                    other_provider, provider="sendgrid", event_id="inbound-original",
                    kind="email_unsubscribed",
                ),
                suppression_event(
                    other_workspace, provider="twilio", event_id="inbound-original",
                ),
            ])
        await session.commit()
    if source_kind == "inbound":
        await record_inbound_reply(sessions, other_provider, "classified")
        await record_inbound_reply(sessions, other_workspace, "hard-keyword")
        other_provider = await read_lead(sessions, other_provider)
        other_workspace = await read_lead(sessions, other_workspace)
    original_history = await _lifecycle_snapshot(sessions, lead.workspace_id)
    other_history = await _lifecycle_snapshot(sessions, other_workspace.workspace_id)
    repaired = replace(
        lead, sms_opted_out=True, suppression_types=frozenset({SuppressionType.SMS_OPT_OUT}),
    )

    for apply, status in (
        (False, RecoveryStatus.WOULD_CHANGE),
        (True, RecoveryStatus.CHANGED),
        (True, RecoveryStatus.ALREADY_CORRECT),
    ):
        report = await recover_recorded_opt_outs(
            request=RecoverOptOutsRequest(
                workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=apply,
                reviewed_for_lifts=True, max_events_per_lead=1,
            ), repository=PostgresOptOutRecoveryRepository(sessions),
        )
        assert report.leads[0].status is status
        assert report.candidate == 1
        assert report.failed == report.unresolved == 0
        assert report.leads[0].reasons == ()
        # The actual scoped source is absent; neither collision belongs in this report.
        assert report.leads[0].references == (f"leads:{lead.lead_id}:sms_opt_out",)
        assert await read_lead(sessions, lead) == (repaired if apply else lead)
        assert await read_lead(sessions, other_provider) == other_provider
        assert await read_lead(sessions, other_workspace) == other_workspace
        assert await _lifecycle_snapshot(sessions, lead.workspace_id) == original_history
        assert await _lifecycle_snapshot(sessions, other_workspace.workspace_id) == other_history


@pytest.mark.parametrize("source_kind", ["suppression", "inbound"])
async def test_recovery_counts_referenced_sources_toward_complete_history_limit(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    source_kind: str,
) -> None:
    sessions, lead = recovery_case
    other = replace(lead, lead_id=uuid4(), crm_lead_id="bounded-source-owner")
    lead = replace(lead, permission_evidence={
        "sms_opt_out_source_provider": "twilio",
        "sms_opt_out_source_event_id": "inbound-original",
        "sms_opt_out_occurred_at": ORIGINAL_AT.isoformat(),
    })
    independent = suppression_event(lead, kind="email_unsubscribed", event_id="independent-email")
    async with sessions() as session:
        await enable_postgres_service_access(session)
        await PostgresLeadRepository(session).upsert(lead)
        await PostgresLeadRepository(session).upsert(other)
        session.add(independent)
        await session.commit()
    references = {
        f"leads:{lead.lead_id}:sms_opt_out", f"external_events:{independent.external_event_id}",
    }
    if source_kind == "inbound":
        await record_inbound_reply(sessions, other, "hard-keyword")
        other = await read_lead(sessions, other)
        async with sessions() as session:
            await enable_postgres_service_access(session)
            inbound = await _recorded_inbound(session, other)
            assert inbound.external_event_id is not None
            references.update((
                f"external_events:{inbound.external_event_id}",
                f"inbound_messages:{inbound.inbound_message_id}",
            ))
        identity_reason = "conflicting_inbound_identity"
    else:
        foreign = suppression_event(other, provider="twilio", event_id="inbound-original")
        async with sessions() as session:
            await enable_postgres_service_access(session)
            session.add(foreign)
            await session.commit()
        references.add(f"external_events:{foreign.external_event_id}")
        identity_reason = "conflicting_event_identity"
    original_history = await _lifecycle_snapshot(sessions, lead.workspace_id)

    for limit, reason in ((1, "event_limit_exceeded"), (2, identity_reason)):
        for apply in (False, True):
            report = await recover_recorded_opt_outs(
                request=RecoverOptOutsRequest(
                    workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=apply,
                    reviewed_for_lifts=True, max_events_per_lead=limit,
                ), repository=PostgresOptOutRecoveryRepository(sessions),
            )
            assert report.unresolved == report.candidate == 1
            assert report.changed == report.would_change == report.failed == 0
            assert report.leads[0].reasons == (reason,)
            assert report.leads[0].references == tuple(sorted(references))
            assert await read_lead(sessions, lead) == lead
            assert await read_lead(sessions, other) == other
            assert await _lifecycle_snapshot(sessions, lead.workspace_id) == original_history


@pytest.mark.parametrize("identity", ["different-event", "different-provider", "shared-source"])
async def test_recovery_requires_consistent_local_sources_before_repairing_any_restriction(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    identity: str,
) -> None:
    sessions, lead = recovery_case
    lead = replace(lead, permission_evidence={
        "sms_opt_out_source_provider": "follow_up_boss",
        "sms_opt_out_source_event_id": "local-source",
        "sms_opt_out_occurred_at": "2026-08-01T10:00:00+00:00",
        "email_unsubscribed_source_provider": (
            "sendgrid" if identity == "different-provider" else "follow_up_boss"
        ),
        "email_unsubscribed_source_event_id": (
            "independent-local-source" if identity == "different-event" else "local-source"
        ),
        "email_unsubscribed_occurred_at": "2026-08-01T12:00:00+02:00",
    })
    independent = suppression_event(
        lead, kind="do_not_contact", event_id="independent-global-block",
    )
    async with sessions() as session:
        await enable_postgres_service_access(session)
        await PostgresLeadRepository(session).upsert(lead)
        session.add(independent)
        await session.commit()
    original_history = await _lifecycle_snapshot(sessions, lead.workspace_id)
    repaired = replace(
        lead, sms_opted_out=True, email_unsubscribed=True, do_not_contact=True,
        suppression_types=frozenset({
            SuppressionType.SMS_OPT_OUT, SuppressionType.EMAIL_UNSUBSCRIBED,
        }),
        permission_evidence={
            **lead.permission_evidence,
            "do_not_contact_source_provider": "follow_up_boss",
            "do_not_contact_source_event_id": "independent-global-block",
            "do_not_contact_occurred_at": ORIGINAL_AT.isoformat(),
        },
    )
    conflict = identity == "shared-source"
    for apply, success_status in (
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
        assert report.leads[0].status is (RecoveryStatus.UNRESOLVED if conflict else success_status)
        assert report.candidate == 1
        assert report.failed == 0
        assert report.leads[0].reasons == (("conflicting_platform_provenance",) if conflict else ())
        references = {
            f"leads:{lead.lead_id}:sms_opt_out", f"leads:{lead.lead_id}:email_unsubscribed",
            f"external_events:{independent.external_event_id}",
        }
        if not conflict and success_status is RecoveryStatus.ALREADY_CORRECT:
            references.add(f"leads:{lead.lead_id}:do_not_contact")
        assert report.leads[0].references == tuple(sorted(references))
        assert await read_lead(sessions, lead) == (repaired if apply and not conflict else lead)
        assert await _lifecycle_snapshot(sessions, lead.workspace_id) == original_history


@pytest.mark.parametrize("conflict", ["channel", "occurrence"])
async def test_recovery_holds_local_history_contradictions_without_partial_repair(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    conflict: str,
) -> None:
    sessions, lead = recovery_case
    await record_inbound_reply(sessions, lead, "hard-keyword")
    await erase_recorded_restrictions(sessions, lead)
    kind = "email_unsubscribed" if conflict == "channel" else "sms_opt_out"
    lead = replace(lead, permission_evidence={
        f"{kind}_source_provider": "twilio",
        f"{kind}_source_event_id": "inbound-original",
        f"{kind}_occurred_at": (
            "2026-08-02T10:00:00+00:00" if conflict == "occurrence" else ORIGINAL_AT.isoformat()
        ),
    })
    independent = suppression_event(
        lead, kind="do_not_contact", event_id="independent-global-block",
    )
    async with sessions() as session:
        await enable_postgres_service_access(session)
        await PostgresLeadRepository(session).upsert(lead)
        session.add(independent)
        inbound = await _recorded_inbound(session, lead)
        inbound_id = inbound.inbound_message_id
        event_id = inbound.external_event_id
        assert event_id is not None
        await session.commit()
    original_history = await _lifecycle_snapshot(sessions, lead.workspace_id)

    for apply in (False, True, True):
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
            f"leads:{lead.lead_id}:{kind}", f"external_events:{event_id}",
            f"inbound_messages:{inbound_id}", f"external_events:{independent.external_event_id}",
        )))
        assert await read_lead(sessions, lead) == lead
        assert await _lifecycle_snapshot(sessions, lead.workspace_id) == original_history