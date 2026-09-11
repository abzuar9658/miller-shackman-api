from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.use_cases.recover_recorded_opt_outs import (
    RecoverOptOutsRequest,
    RecoveryStatus,
    recover_recorded_opt_outs,
)
from app.core.database import enable_postgres_service_access
from app.domain.compliance.contactability import SuppressionType
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import ExternalEventModel, WorkspaceModel
from app.infrastructure.persistence.postgres.opt_out_recovery import (
    PostgresOptOutRecoveryRepository,
)
from tests.infrastructure.persistence.postgres._harness import PostgresHarnessDatabase

NOW = datetime(2026, 9, 9, 14, tzinfo=UTC)
ORIGINAL_AT = datetime(2026, 8, 1, 10, tzinfo=UTC)


@pytest_asyncio.fixture
async def recovery_case(
    postgres_harness_database: PostgresHarnessDatabase,
) -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord]]:
    engine = create_async_engine(postgres_harness_database.async_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    lead = CanonicalLeadRecord(
        workspace_id=uuid4(), lead_id=uuid4(), crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="recovery-person", facts_derived_at=NOW, source_payload_version="test:v1",
        lead_stage="unchanged", last_agent_activity_at=NOW,
    )
    try:
        async with sessions() as session:
            await enable_postgres_service_access(session)
            session.add(WorkspaceModel(
                workspace_id=lead.workspace_id, name="Synthetic recovery workspace",
                status="active", default_timezone="UTC", created_at=NOW, updated_at=NOW,
            ))
            await session.flush()
            await PostgresLeadRepository(session).upsert(lead)
            await session.commit()
        yield sessions, lead
    finally:
        await engine.dispose()


def suppression_event(
    lead: CanonicalLeadRecord, *, event_id: str = "original-stop",
    provider: str = "follow_up_boss", kind: str = "sms_opt_out",
    occurred_at: datetime = ORIGINAL_AT,
) -> ExternalEventModel:
    return ExternalEventModel(
        external_event_id=uuid4(), workspace_id=lead.workspace_id,
        lead_id=lead.lead_id, crm_lead_id=lead.crm_lead_id, provider=provider,
        provider_event_id=event_id, event_type=f"contact_suppression.{kind}",
        received_at=occurred_at, processed_at=occurred_at, status="processed",
        payload_redacted={}, created_at=occurred_at, updated_at=occurred_at,
    )


async def read_lead(
    sessions: async_sessionmaker[AsyncSession], lead: CanonicalLeadRecord,
) -> CanonicalLeadRecord:
    async with sessions() as session:
        await enable_postgres_service_access(session)
        saved = await PostgresLeadRepository(session).get_by_id(lead.workspace_id, lead.lead_id)
        assert saved is not None
        return saved


async def test_recovery_dry_run_apply_and_repeat_restore_original_email_evidence(
    postgres_harness_database: PostgresHarnessDatabase,
) -> None:
    engine = create_async_engine(postgres_harness_database.async_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    lead = CanonicalLeadRecord(
        workspace_id=uuid4(), lead_id=uuid4(), crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="recovery-person", facts_derived_at=NOW, source_payload_version="test:v1",
        lead_stage="unchanged", last_agent_activity_at=NOW,
    )
    try:
        async with sessions() as setup:
            await enable_postgres_service_access(setup)
            setup.add(WorkspaceModel(
                workspace_id=lead.workspace_id, name="Synthetic recovery workspace",
                status="active", default_timezone="UTC", created_at=NOW, updated_at=NOW,
            ))
            await setup.flush()
            await PostgresLeadRepository(setup).upsert(lead)
            setup.add(ExternalEventModel(
                external_event_id=uuid4(), workspace_id=lead.workspace_id,
                lead_id=lead.lead_id, crm_lead_id=lead.crm_lead_id, provider="follow_up_boss",
                provider_event_id="email-unsubscribe-original:42",
                event_type="contact_suppression.email_unsubscribed", received_at=ORIGINAL_AT,
                processed_at=ORIGINAL_AT, status="processed", payload_redacted={},
                created_at=ORIGINAL_AT, updated_at=ORIGINAL_AT,
            ))
            await setup.commit()

        repository = PostgresOptOutRecoveryRepository(sessions)
        request = RecoverOptOutsRequest(workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,))
        preview = await recover_recorded_opt_outs(request=request, repository=repository)
        assert preview.would_change == 1
        assert preview.candidate == 1
        assert preview.changed == preview.failed == preview.unresolved == 0
        async with sessions() as verify:
            await enable_postgres_service_access(verify)
            assert await PostgresLeadRepository(verify).get_by_id(
                lead.workspace_id, lead.lead_id,
            ) == lead

        apply_request = RecoverOptOutsRequest(
            workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=True,
            reviewed_for_lifts=True,
        )
        applied = await recover_recorded_opt_outs(request=apply_request, repository=repository)
        assert applied.changed == applied.candidate == 1
        assert applied.failed == applied.unresolved == 0
        async with sessions() as verify:
            await enable_postgres_service_access(verify)
            saved = await PostgresLeadRepository(verify).get_by_id(lead.workspace_id, lead.lead_id)
            assert saved is not None
            assert saved.email_unsubscribed is True
            assert saved.sms_opted_out is False
            assert saved.do_not_contact is None
            assert saved.suppression_types == frozenset({SuppressionType.EMAIL_UNSUBSCRIBED})
            assert saved.permission_evidence == {
                "email_unsubscribed_source_provider": "follow_up_boss",
                "email_unsubscribed_source_event_id": "email-unsubscribe-original:42",
                "email_unsubscribed_occurred_at": "2026-08-01T10:00:00+00:00",
            }
            assert saved.lead_stage == "unchanged"
            assert saved.last_agent_activity_at == NOW

        repeated = await recover_recorded_opt_outs(request=apply_request, repository=repository)
        assert repeated.already_correct == 1
        assert repeated.changed == repeated.failed == repeated.unresolved == 0
    finally:
        await engine.dispose()


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("has_existing_provenance", [False, True])
async def test_recovery_keeps_valid_provenance_else_earliest_with_stable_ties(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    reverse: bool,
    has_existing_provenance: bool,
) -> None:
    sessions, lead = recovery_case
    if has_existing_provenance:
        lead = replace(lead, permission_evidence={
            "sms_opt_out_source_provider": "twilio",
            "sms_opt_out_source_event_id": "known-valid",
            "sms_opt_out_occurred_at": "2026-09-01T12:00:00+02:00",
        })
    events = [
        suppression_event(lead, event_id="a-original"),
        suppression_event(lead, event_id="z-later-tie"),
        suppression_event(lead, provider="twilio", event_id="a-provider-tie"),
        suppression_event(
            lead, provider="twilio", event_id="known-valid",
            occurred_at=datetime(2026, 9, 1, 10, tzinfo=UTC),
        ),
    ]
    if reverse:
        events.reverse()
    async with sessions() as session:
        await enable_postgres_service_access(session)
        await PostgresLeadRepository(session).upsert(lead)
        session.add_all(events)
        await session.commit()
    request = RecoverOptOutsRequest(
        workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=True,
        reviewed_for_lifts=True,
    )
    report = await recover_recorded_opt_outs(
        request=request, repository=PostgresOptOutRecoveryRepository(sessions),
    )
    assert report.changed == report.candidate == 1
    saved = await read_lead(sessions, lead)
    assert saved.sms_opted_out is True
    assert saved.suppression_types == frozenset({SuppressionType.SMS_OPT_OUT})
    if has_existing_provenance:
        assert saved.permission_evidence == {
            "sms_opt_out_source_provider": "twilio",
            "sms_opt_out_source_event_id": "known-valid",
            "sms_opt_out_occurred_at": "2026-09-01T12:00:00+02:00",
        }
    else:
        assert saved.permission_evidence == {
            "sms_opt_out_source_provider": "follow_up_boss",
            "sms_opt_out_source_event_id": "a-original",
            "sms_opt_out_occurred_at": "2026-08-01T10:00:00+00:00",
        }
    expected_references = {
        f"external_events:{event.external_event_id}" for event in events
    }
    if has_existing_provenance:
        expected_references.add(f"leads:{lead.lead_id}:sms_opt_out")
    assert report.leads[0].references == tuple(sorted(expected_references))


@pytest.mark.parametrize(
    ("evidence", "with_history", "reason"),
    [
        ({"sms_opt_out_source_provider": "twilio"}, True, "partial_platform_provenance"),
        ({"sms_opt_out_source_provider": ""}, True, "partial_platform_provenance"),
        ({
            "sms_opt_out_source_provider": "twilio", "sms_opt_out_source_event_id": "original-stop",
            "sms_opt_out_occurred_at": "not-a-time",
        }, True, "partial_platform_provenance"),
        ({
            "sms_opt_out_source_provider": "twilio", "sms_opt_out_source_event_id": "original-stop",
            "sms_opt_out_occurred_at": "2026-08-01T10:00:00",
        }, True, "partial_platform_provenance"),
        ({
            "sms_opt_out_source_provider": "follow_up_boss",
            "sms_opt_out_source_event_id": "original-stop",
            "sms_opt_out_occurred_at": "2026-08-02T10:00:00+00:00",
        }, True, "conflicting_platform_provenance"),
        ({}, False, "missing_evidence"),
        ({"sms_opted_out_source": "legacy-unknown"}, False, "missing_evidence"),
    ],
)
async def test_recovery_reports_ambiguous_provenance_without_modifying_lead(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    evidence: dict[str, str],
    with_history: bool,
    reason: str,
) -> None:
    sessions, lead = recovery_case
    lead = replace(lead, sms_opted_out=True, permission_evidence=evidence)
    async with sessions() as session:
        await enable_postgres_service_access(session)
        await PostgresLeadRepository(session).upsert(lead)
        if with_history:
            session.add(suppression_event(lead))
        await session.commit()
    report = await recover_recorded_opt_outs(
        request=RecoverOptOutsRequest(
            workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=True,
            reviewed_for_lifts=True,
        ),
        repository=PostgresOptOutRecoveryRepository(sessions),
    )
    assert report.unresolved == report.candidate == 1
    assert report.changed == report.failed == 0
    assert report.leads[0].status is RecoveryStatus.UNRESOLVED
    assert reason in report.leads[0].reasons
    assert await read_lead(sessions, lead) == lead


async def test_recovery_reports_lock_failure_continues_other_leads_and_retries_safely(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    postgres_harness_database: PostgresHarnessDatabase,
) -> None:
    sessions, lead = recovery_case
    other = replace(lead, lead_id=uuid4(), crm_lead_id="second-recovery-person")
    async with sessions() as setup:
        await enable_postgres_service_access(setup)
        await PostgresLeadRepository(setup).upsert(other)
        setup.add_all([
            suppression_event(lead), suppression_event(other, event_id="other-original-stop"),
        ])
        await setup.commit()
    engine = create_async_engine(
        postgres_harness_database.async_url, poolclass=NullPool,
        connect_args={"server_settings": {"lock_timeout": "100ms"}},
    )
    bounded_sessions = async_sessionmaker(engine, expire_on_commit=False)
    request = RecoverOptOutsRequest(
        workspace_id=lead.workspace_id, lead_ids=(lead.lead_id, other.lead_id), apply=True,
        reviewed_for_lifts=True,
    )
    repository = PostgresOptOutRecoveryRepository(bounded_sessions)
    try:
        async with sessions() as blocker:
            await enable_postgres_service_access(blocker)
            await PostgresLeadRepository(blocker).get_by_id_for_update(
                lead.workspace_id, lead.lead_id,
            )
            report = await recover_recorded_opt_outs(request=request, repository=repository)
            assert report.failed == report.changed == 1
            assert report.unresolved == 0
            assert report.leads[0].status is RecoveryStatus.FAILED
            assert report.leads[0].reasons == ("recovery_storage_failure",)
            assert await read_lead(sessions, lead) == lead
            await blocker.rollback()
        recovered_other = await read_lead(sessions, other)
        assert recovered_other.sms_opted_out is True
        retried = await recover_recorded_opt_outs(request=request, repository=repository)
        assert retried.changed == retried.already_correct == 1
        assert retried.failed == retried.unresolved == 0
        assert (await read_lead(sessions, lead)).sms_opted_out is True
        assert await read_lead(sessions, other) == recovered_other
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    ("variant", "expected_status", "reason"),
    [
        ("orphan-matches", RecoveryStatus.CHANGED, None),
        ("orphan-wrong-provider", RecoveryStatus.UNRESOLVED, "ambiguous_event_identity"),
        ("linked-crm-mismatch", RecoveryStatus.UNRESOLVED, "conflicting_event_identity"),
        ("linked-lead-mismatch", RecoveryStatus.UNRESOLVED, "conflicting_event_identity"),
        ("other-workspace", RecoveryStatus.CLEAN, None),
        ("pending", RecoveryStatus.UNRESOLVED, "unverified_suppression_event"),
        ("unknown-kind", RecoveryStatus.UNRESOLVED, "unknown_suppression_kind"),
        ("blank-source-id", RecoveryStatus.UNRESOLVED, "invalid_event_provenance"),
    ],
)
async def test_recovery_matches_orphan_identity_without_guessing_or_crossing_tenants(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    variant: str,
    expected_status: RecoveryStatus,
    reason: str | None,
) -> None:
    sessions, lead = recovery_case
    event = suppression_event(lead, kind="do_not_contact")
    if variant.startswith("orphan"):
        event.lead_id = None
        event.status = "ignored"
        event.failure_reason = "lead_not_found"
        if variant == "orphan-wrong-provider":
            event.provider = "twilio"
    elif variant == "linked-crm-mismatch":
        event.crm_lead_id = "different-person"
    elif variant == "pending":
        event.status = "pending"
    elif variant == "unknown-kind":
        event.event_type = "contact_suppression.unknown"
    elif variant == "blank-source-id":
        event.provider_event_id = " "
    async with sessions() as session:
        await enable_postgres_service_access(session)
        if variant in {"other-workspace", "linked-lead-mismatch"}:
            other = replace(lead, lead_id=uuid4(), crm_lead_id="different-person")
            if variant == "other-workspace":
                other = replace(other, workspace_id=uuid4(), crm_lead_id=lead.crm_lead_id)
                session.add(WorkspaceModel(
                    workspace_id=other.workspace_id, name="Other synthetic workspace",
                    status="active", default_timezone="UTC", created_at=NOW, updated_at=NOW,
                ))
                await session.flush()
                event.workspace_id = other.workspace_id
            await PostgresLeadRepository(session).upsert(other)
            event.lead_id = other.lead_id
        session.add(event)
        await session.commit()
    report = await recover_recorded_opt_outs(
        request=RecoverOptOutsRequest(
            workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=True,
            reviewed_for_lifts=True,
        ),
        repository=PostgresOptOutRecoveryRepository(sessions),
    )
    assert report.leads[0].status is expected_status
    if reason is not None:
        assert report.leads[0].reasons == (reason,)
    saved = await read_lead(sessions, lead)
    if expected_status is RecoveryStatus.CHANGED:
        assert saved == replace(lead, do_not_contact=True, permission_evidence={
            "do_not_contact_source_provider": "follow_up_boss",
            "do_not_contact_source_event_id": "original-stop",
            "do_not_contact_occurred_at": "2026-08-01T10:00:00+00:00",
        })
        async with sessions() as session:
            await enable_postgres_service_access(session)
            original = await session.get(ExternalEventModel, event.external_event_id)
            assert original is not None
            assert original.lead_id is None
            assert original.status == "ignored"
            assert original.failure_reason == "lead_not_found"
    else:
        assert saved == lead
    if variant in {"other-workspace", "linked-lead-mismatch"}:
        assert await read_lead(sessions, other) == other


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("held", [False, True])
async def test_recovery_excludes_review_holds_and_incomplete_history(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    apply: bool,
    held: bool,
) -> None:
    sessions, lead = recovery_case
    async with sessions() as session:
        await enable_postgres_service_access(session)
        session.add_all([
            suppression_event(lead),
            suppression_event(lead, event_id="later-stop", occurred_at=NOW),
        ])
        await session.commit()
    report = await recover_recorded_opt_outs(
        request=RecoverOptOutsRequest(
            workspace_id=lead.workspace_id, lead_ids=(lead.lead_id,), apply=apply,
            reviewed_for_lifts=True, max_events_per_lead=100 if held else 1,
            consent_review_hold_ids=(lead.lead_id,) if held else (),
        ),
        repository=PostgresOptOutRecoveryRepository(sessions),
    )
    assert report.unresolved == 1
    assert report.changed == report.would_change == report.failed == 0
    assert report.leads[0].reasons == (
        "operator_consent_review_hold" if held else "event_limit_exceeded",
    )
    assert await read_lead(sessions, lead) == lead