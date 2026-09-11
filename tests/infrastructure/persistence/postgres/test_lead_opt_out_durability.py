import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.use_cases.process_contact_suppression_event import (
    apply_contact_suppression_to_lead,
)
from app.core.database import enable_postgres_service_access
from app.domain.compliance.contactability import (
    ContactPermissionStatus,
    ContactSuppressionKind,
    SuppressionType,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider, preserve_app_owned_lead_state
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import LeadModel, WorkspaceModel
from tests.infrastructure.persistence.postgres._harness import PostgresHarnessDatabase

NOW = datetime(2026, 9, 9, 14, tzinfo=UTC)
OPT_OUT_AT = datetime(2026, 9, 8, 12, tzinfo=UTC)


@pytest.mark.parametrize("refresh_commits_first", [False, True])
@pytest.mark.parametrize(
    ("kind", "expected_flags", "expected_types", "expected_evidence"),
    [
        (
            ContactSuppressionKind.SMS_OPT_OUT, (True, False, None),
            frozenset({SuppressionType.SMS_OPT_OUT}),
            {"sms_opt_out_source_provider": "twilio",
             "sms_opt_out_source_event_id": "committed-stop",
             "sms_opt_out_occurred_at": "2026-09-08T12:00:00+00:00"},
        ),
        (
            ContactSuppressionKind.EMAIL_UNSUBSCRIBED, (False, True, None),
            frozenset({SuppressionType.EMAIL_UNSUBSCRIBED}),
            {"email_unsubscribed_source_provider": "twilio",
             "email_unsubscribed_source_event_id": "committed-stop",
             "email_unsubscribed_occurred_at": "2026-09-08T12:00:00+00:00"},
        ),
        (
            ContactSuppressionKind.DO_NOT_CONTACT, (False, False, True), frozenset(),
            {"do_not_contact_source_provider": "twilio",
             "do_not_contact_source_event_id": "committed-stop",
             "do_not_contact_occurred_at": "2026-09-08T12:00:00+00:00"},
        ),
    ],
)
async def test_stale_refresh_cannot_erase_committed_opt_out(
    postgres_harness_database: PostgresHarnessDatabase,
    refresh_commits_first: bool,
    kind: ContactSuppressionKind,
    expected_flags: tuple[bool, bool, bool | None],
    expected_types: frozenset[SuppressionType],
    expected_evidence: dict[str, str],
) -> None:
    engine = create_async_engine(postgres_harness_database.async_url, poolclass=NullPool)
    lead = CanonicalLeadRecord(
        workspace_id=uuid4(), lead_id=uuid4(), crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="same-crm-person", facts_derived_at=NOW, source_payload_version="test:v1",
    )
    snapshot_read = asyncio.Event()
    suppression_read = asyncio.Event()
    suppression_committed = asyncio.Event()
    refresh_committed = asyncio.Event()
    try:
        async with AsyncSession(engine) as setup:
            await enable_postgres_service_access(setup)
            setup.add(WorkspaceModel(
                workspace_id=lead.workspace_id, name="Synthetic durability workspace",
                status="active", default_timezone="UTC", created_at=NOW, updated_at=NOW,
            ))
            await setup.flush()
            await PostgresLeadRepository(setup).upsert(lead)
            await setup.commit()

        async def stale_refresh() -> None:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                await enable_postgres_service_access(session)
                # Keep an ORM instance alive to exercise an already-populated identity map.
                cached = await session.get(LeadModel, lead.lead_id)
                assert cached is not None and cached.sms_opted_out is False
                repository = PostgresLeadRepository(session)
                existing = await repository.get_by_id(lead.workspace_id, lead.lead_id)
                assert existing is not None and existing.sms_opted_out is False
                stale = preserve_app_owned_lead_state(replace(lead, lead_stage="updated"), existing)
                snapshot_read.set()
                if refresh_commits_first:
                    await suppression_read.wait()
                else:
                    await suppression_committed.wait()
                await repository.upsert(stale)
                await session.commit()
                refresh_committed.set()

        async def record_opt_out() -> None:
            await snapshot_read.wait()
            async with AsyncSession(engine) as session:
                await enable_postgres_service_access(session)
                repository = PostgresLeadRepository(session)
                existing = await repository.get_by_id(lead.workspace_id, lead.lead_id)
                assert existing is not None
                suppression_read.set()
                if refresh_commits_first:
                    await refresh_committed.wait()
                await apply_contact_suppression_to_lead(
                    lead=replace(existing, last_agent_activity_at=NOW), suppression_kind=kind,
                    source_provider="twilio", source_event_id="committed-stop",
                    occurred_at=OPT_OUT_AT, lead_repository=repository,
                )
                await session.commit()
                suppression_committed.set()

        async with asyncio.timeout(10):
            async with asyncio.TaskGroup() as group:
                group.create_task(stale_refresh())
                group.create_task(record_opt_out())

        async with AsyncSession(engine) as verify:
            await enable_postgres_service_access(verify)
            saved = await PostgresLeadRepository(verify).get_by_id(lead.workspace_id, lead.lead_id)
            assert saved is not None
            assert (
                saved.sms_opted_out, saved.email_unsubscribed, saved.do_not_contact,
            ) == expected_flags
            assert saved.suppression_types == expected_types
            assert saved.permission_evidence == expected_evidence
            assert saved.last_agent_activity_at == NOW
            if not refresh_commits_first:
                assert saved.lead_stage == "updated"
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "opt_out_inserts_first", [True, False], ids=["opt-out-first", "refresh-first"],
)
async def test_concurrent_first_inserts_return_one_lead_with_durable_opt_out(
    postgres_harness_database: PostgresHarnessDatabase,
    opt_out_inserts_first: bool,
) -> None:
    engine = create_async_engine(postgres_harness_database.async_url, poolclass=NullPool)
    opt_out_lead = CanonicalLeadRecord(
        workspace_id=uuid4(), lead_id=uuid4(), crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="concurrent-first-insert", facts_derived_at=NOW,
        source_payload_version="test:v1", last_agent_activity_at=NOW,
    )
    refresh_lead = replace(opt_out_lead, lead_id=uuid4(), last_agent_activity_at=None)
    expected_evidence = {
        "sms_opt_out_source_provider": "twilio",
        "sms_opt_out_source_event_id": "first-insert-stop",
        "sms_opt_out_occurred_at": "2026-09-08T12:00:00+00:00",
    }
    both_read_missing = asyncio.Barrier(2)
    first_inserted = asyncio.Event()
    conflict_observed = asyncio.Event()
    backend_pids: dict[bool, int] = {}
    try:
        async with AsyncSession(engine) as setup:
            await enable_postgres_service_access(setup)
            await _seed_workspaces(setup, opt_out_lead.workspace_id)
            await setup.commit()

        async def insert_lead(*, records_opt_out: bool) -> CanonicalLeadRecord:
            candidate = opt_out_lead if records_opt_out else refresh_lead
            inserts_first = records_opt_out == opt_out_inserts_first
            async with AsyncSession(engine) as session:
                await enable_postgres_service_access(session)
                repository = PostgresLeadRepository(session)
                existing = await repository.get_by_crm_id(
                    candidate.workspace_id, candidate.crm_provider, candidate.crm_lead_id,
                )
                assert existing is None
                backend_pids[records_opt_out] = int(
                    (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
                )
                await both_read_missing.wait()
                if not inserts_first:
                    await first_inserted.wait()

                if records_opt_out:
                    saved = await apply_contact_suppression_to_lead(
                        lead=candidate, suppression_kind=ContactSuppressionKind.SMS_OPT_OUT,
                        source_provider="twilio", source_event_id="first-insert-stop",
                        occurred_at=OPT_OUT_AT, lead_repository=repository,
                    )
                else:
                    saved = await repository.upsert(
                        preserve_app_owned_lead_state(candidate, existing),
                    )
                if inserts_first:
                    first_inserted.set()
                    await conflict_observed.wait()
                await session.commit()
                return saved

        async def observe_insert_conflict() -> None:
            await first_inserted.wait()
            blocker_pid = backend_pids[opt_out_inserts_first]
            blocked_pid = backend_pids[not opt_out_inserts_first]
            assert blocker_pid != blocked_pid
            async with AsyncSession(engine) as observer:
                # A pre-upsert event alone cannot prove the INSERT reached Postgres.
                # Observe the real lock wait before allowing the winning commit.
                while True:
                    result = await observer.execute(
                        text("SELECT :blocker_pid = ANY(pg_blocking_pids(:blocked_pid))"),
                        {"blocker_pid": blocker_pid, "blocked_pid": blocked_pid},
                    )
                    if result.scalar_one():
                        conflict_observed.set()
                        return

        async with asyncio.timeout(10):
            async with asyncio.TaskGroup() as group:
                opt_out_task = group.create_task(insert_lead(records_opt_out=True))
                refresh_task = group.create_task(insert_lead(records_opt_out=False))
                group.create_task(observe_insert_conflict())

        opt_out_result = opt_out_task.result()
        refresh_result = refresh_task.result()
        winner_id = opt_out_lead.lead_id if opt_out_inserts_first else refresh_lead.lead_id
        loser_id = refresh_lead.lead_id if opt_out_inserts_first else opt_out_lead.lead_id
        async with AsyncSession(engine) as verify:
            await enable_postgres_service_access(verify)
            repository = PostgresLeadRepository(verify)
            saved = await repository.get_by_crm_id(
                opt_out_lead.workspace_id, opt_out_lead.crm_provider, opt_out_lead.crm_lead_id,
            )
            assert saved is not None
            assert opt_out_result.lead_id == refresh_result.lead_id == saved.lead_id == winner_id
            assert await repository.count_for_workspace(opt_out_lead.workspace_id) == 1
            assert await repository.get_by_id(opt_out_lead.workspace_id, winner_id) == saved
            assert await repository.get_by_id(opt_out_lead.workspace_id, loser_id) is None

            protected_records = [opt_out_result, saved]
            if opt_out_inserts_first:
                protected_records.append(refresh_result)
            for protected in protected_records:
                assert protected.sms_opted_out is True
                assert protected.email_unsubscribed is False
                assert protected.do_not_contact is None
                assert protected.suppression_types == frozenset({SuppressionType.SMS_OPT_OUT})
                assert protected.permission_evidence == expected_evidence
                assert protected.last_agent_activity_at == NOW
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "other_workspace_opted_out", [False, True], ids=["other-clean", "other-opted-out"],
)
async def test_refresh_preserves_opt_out_without_touching_same_crm_id_in_other_workspace(
    postgres_harness_database: PostgresHarnessDatabase,
    other_workspace_opted_out: bool,
) -> None:
    engine = create_async_engine(postgres_harness_database.async_url, poolclass=NullPool)
    lead = CanonicalLeadRecord(
        workspace_id=uuid4(), lead_id=uuid4(), crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="shared-across-workspaces", facts_derived_at=NOW,
        source_payload_version="test:v1", lead_stage="workspace-a-original",
        last_agent_activity_at=NOW,
    )
    other_lead = replace(
        lead, workspace_id=uuid4(), lead_id=uuid4(), lead_stage="workspace-b-original",
        last_agent_activity_at=OPT_OUT_AT,
    )
    try:
        async with AsyncSession(engine) as setup:
            await enable_postgres_service_access(setup)
            await _seed_workspaces(setup, lead.workspace_id, other_lead.workspace_id)
            repository = PostgresLeadRepository(setup)
            await apply_contact_suppression_to_lead(
                lead=lead, suppression_kind=ContactSuppressionKind.SMS_OPT_OUT,
                source_provider="twilio", source_event_id="workspace-a-stop",
                occurred_at=OPT_OUT_AT, lead_repository=repository,
            )
            if other_workspace_opted_out:
                await apply_contact_suppression_to_lead(
                    lead=other_lead, suppression_kind=ContactSuppressionKind.SMS_OPT_OUT,
                    source_provider="follow_up_boss", source_event_id="workspace-b-stop",
                    occurred_at=NOW, lead_repository=repository,
                )
            else:
                await repository.upsert(other_lead)
            await setup.commit()

        async with AsyncSession(engine) as baseline:
            await enable_postgres_service_access(baseline)
            other_before = await PostgresLeadRepository(baseline).get_by_crm_id(
                other_lead.workspace_id, other_lead.crm_provider, other_lead.crm_lead_id,
            )
            assert other_before is not None
            assert other_before.lead_id == other_lead.lead_id
            assert other_before.sms_opted_out is other_workspace_opted_out
            assert other_before.email_unsubscribed is False
            assert other_before.do_not_contact is None
            assert other_before.suppression_types == (
                frozenset({SuppressionType.SMS_OPT_OUT})
                if other_workspace_opted_out else frozenset()
            )
            assert other_before.permission_evidence == (
                {
                    "sms_opt_out_source_provider": "follow_up_boss",
                    "sms_opt_out_source_event_id": "workspace-b-stop",
                    "sms_opt_out_occurred_at": "2026-09-09T14:00:00+00:00",
                }
                if other_workspace_opted_out else {}
            )

        async with AsyncSession(engine) as refresh:
            await enable_postgres_service_access(refresh)
            repository = PostgresLeadRepository(refresh)
            existing = await repository.get_by_crm_id(
                lead.workspace_id, lead.crm_provider, lead.crm_lead_id,
            )
            assert existing is not None
            updated = await repository.upsert(preserve_app_owned_lead_state(
                replace(lead, lead_stage="workspace-a-refreshed", last_agent_activity_at=None),
                existing,
            ))
            assert updated.lead_id == lead.lead_id
            await refresh.commit()

        async with AsyncSession(engine) as verify:
            await enable_postgres_service_access(verify)
            repository = PostgresLeadRepository(verify)
            saved = await repository.get_by_crm_id(
                lead.workspace_id, lead.crm_provider, lead.crm_lead_id,
            )
            other_after = await repository.get_by_crm_id(
                other_lead.workspace_id, other_lead.crm_provider, other_lead.crm_lead_id,
            )
            assert saved is not None
            assert saved.lead_id == lead.lead_id
            assert saved.lead_stage == "workspace-a-refreshed"
            assert saved.sms_opted_out is True
            assert saved.email_unsubscribed is False
            assert saved.do_not_contact is None
            assert saved.suppression_types == frozenset({SuppressionType.SMS_OPT_OUT})
            assert saved.permission_evidence == {
                "sms_opt_out_source_provider": "twilio",
                "sms_opt_out_source_event_id": "workspace-a-stop",
                "sms_opt_out_occurred_at": "2026-09-08T12:00:00+00:00",
            }
            assert saved.last_agent_activity_at == NOW
            assert other_after == other_before
            assert await repository.get_by_id(lead.workspace_id, other_lead.lead_id) is None
            assert await repository.get_by_id(other_lead.workspace_id, lead.lead_id) is None
            for workspace_id in (lead.workspace_id, other_lead.workspace_id):
                assert await repository.count_for_workspace(workspace_id) == 1
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "crm_restriction",
    [ContactSuppressionKind.EMAIL_UNSUBSCRIBED, ContactSuppressionKind.DO_NOT_CONTACT],
    ids=["email", "dnc"],
)
async def test_crm_restrictions_preserve_platform_sms_evidence_at_write_boundary(
    postgres_harness_database: PostgresHarnessDatabase,
    crm_restriction: ContactSuppressionKind,
) -> None:
    engine = create_async_engine(postgres_harness_database.async_url, poolclass=NullPool)
    lead = CanonicalLeadRecord(
        workspace_id=uuid4(), lead_id=uuid4(), crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="ac04-shared-crm-person", facts_derived_at=OPT_OUT_AT,
        source_payload_version="test:v1", source_updated_at=OPT_OUT_AT,
        lead_stage="original", do_not_contact=False, last_agent_activity_at=NOW,
    )
    other_lead = replace(
        lead, workspace_id=uuid4(), lead_id=uuid4(), lead_stage="other-workspace",
        last_agent_activity_at=OPT_OUT_AT,
    )
    email_unsubscribed = crm_restriction == ContactSuppressionKind.EMAIL_UNSUBSCRIBED
    do_not_contact = crm_restriction == ContactSuppressionKind.DO_NOT_CONTACT
    crm_suppressions = (
        frozenset({SuppressionType.EMAIL_UNSUBSCRIBED}) if email_unsubscribed else frozenset()
    )
    crm_evidence = {
        "sms_permission_status_source": "follow_up_boss.customFields",
        f"{crm_restriction.value}_source": "follow_up_boss.customFields",
    }
    snapshot = replace(
        lead, facts_derived_at=NOW, source_updated_at=NOW, lead_stage="crm-refreshed",
        sms_permission_status=ContactPermissionStatus.CONFIRMED, sms_opted_out=False,
        email_unsubscribed=email_unsubscribed, do_not_contact=do_not_contact,
        suppression_types=crm_suppressions, last_agent_activity_at=OPT_OUT_AT,
        permission_evidence={
            **crm_evidence,
            "sms_opt_out_source_provider": "follow_up_boss",
            "sms_opt_out_source_event_id": "conflicting-crm-sms-evidence",
            "sms_opt_out_occurred_at": "2026-09-09T14:00:00+00:00",
        },
    )
    expected_evidence = {
        **crm_evidence,
        "sms_opt_out_source_provider": "twilio",
        "sms_opt_out_source_event_id": "platform-sms-stop-ac04",
        "sms_opt_out_occurred_at": "2026-09-08T12:00:00+00:00",
    }
    try:
        async with AsyncSession(engine) as setup:
            await enable_postgres_service_access(setup)
            await _seed_workspaces(setup, lead.workspace_id, other_lead.workspace_id)
            repository = PostgresLeadRepository(setup)
            await apply_contact_suppression_to_lead(
                lead=lead, suppression_kind=ContactSuppressionKind.SMS_OPT_OUT,
                source_provider="twilio", source_event_id="platform-sms-stop-ac04",
                occurred_at=OPT_OUT_AT, lead_repository=repository,
            )
            await repository.upsert(other_lead)
            await setup.commit()

        previous_saved: CanonicalLeadRecord | None = None
        for _ in range(2):
            async with AsyncSession(engine) as refresh:
                await enable_postgres_service_access(refresh)
                # No application pre-merge: the write boundary must protect the committed row.
                await PostgresLeadRepository(refresh).upsert(snapshot)
                await refresh.commit()

            async with AsyncSession(engine) as verify:
                await enable_postgres_service_access(verify)
                repository = PostgresLeadRepository(verify)
                saved = await repository.get_by_crm_id(
                    lead.workspace_id, lead.crm_provider, lead.crm_lead_id,
                )
                other_after = await repository.get_by_crm_id(
                    other_lead.workspace_id, other_lead.crm_provider, other_lead.crm_lead_id,
                )
                assert saved is not None
                assert saved.lead_id == lead.lead_id
                assert saved.sms_opted_out is True
                assert saved.sms_permission_status is ContactPermissionStatus.CONFIRMED
                assert saved.email_unsubscribed is email_unsubscribed
                assert saved.do_not_contact is do_not_contact
                assert saved.suppression_types == (
                    frozenset({SuppressionType.SMS_OPT_OUT}) | crm_suppressions
                )
                assert saved.permission_evidence == expected_evidence
                assert saved.lead_stage == "crm-refreshed"
                assert saved.source_updated_at == NOW
                assert saved.facts_derived_at == NOW
                assert saved.last_agent_activity_at == NOW
                assert other_after == other_lead
                if previous_saved is not None:
                    assert saved == previous_saved
                previous_saved = saved
    finally:
        await engine.dispose()


async def _seed_workspaces(session: AsyncSession, *workspace_ids: UUID) -> None:
    session.add_all([
        WorkspaceModel(
            workspace_id=workspace_id, name="Synthetic durability workspace",
            status="active", default_timezone="UTC", created_at=NOW, updated_at=NOW,
        )
        for workspace_id in workspace_ids
    ])
    await session.flush()