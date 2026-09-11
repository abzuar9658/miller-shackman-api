import asyncio
import json
import stat
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.use_cases.recover_recorded_opt_outs import (
    LeadOptOutRecoveryResult,
    OptOutRecoveryRepository,
    RecoverOptOutsRequest,
)
from app.core.database import enable_postgres_service_access
from app.domain.compliance import SuppressionType
from app.domain.leads import CanonicalLeadRecord
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import LeadModel
from app.infrastructure.persistence.postgres.opt_out_recovery import (
    PostgresOptOutRecoveryRepository,
)
from scripts.recover_recorded_opt_outs import main
from tests.infrastructure.persistence.postgres._harness import PostgresHarnessDatabase
from tests.infrastructure.persistence.postgres.test_opt_out_lead_detail import _lifecycle_snapshot
from tests.infrastructure.persistence.postgres.test_opt_out_recovery import (
    read_lead,
    suppression_event,
)
from tests.infrastructure.persistence.postgres.test_opt_out_recovery import (
    recovery_case as recovery_case,
)


class InterruptAfterCommitRepository(OptOutRecoveryRepository):
    def __init__(self, repository: OptOutRecoveryRepository, lead_id: UUID) -> None:
        self._repository = repository
        self._lead_id = lead_id

    async def recover_lead(
        self, *, request: RecoverOptOutsRequest, lead_id: UUID,
    ) -> LeadOptOutRecoveryResult:
        result = await self._repository.recover_lead(request=request, lead_id=lead_id)
        if lead_id == self._lead_id:
            # SQL and COMMIT are real; interrupt before the CLI can record this result.
            raise asyncio.CancelledError
        return result


async def _lead_update_times(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID,
) -> dict[UUID, datetime]:
    async with sessions() as session:
        await enable_postgres_service_access(session)
        rows = await session.execute(select(LeadModel.lead_id, LeadModel.updated_at).where(
            LeadModel.workspace_id == workspace_id,
        ))
        return {row.lead_id: row.updated_at for row in rows}


@pytest.mark.parametrize("interruption", ["before-commit", "after-commit-before-report"])
async def test_cli_interruption_preserves_committed_prefix_and_retries_from_real_postgres(
    recovery_case: tuple[async_sessionmaker[AsyncSession], CanonicalLeadRecord],
    postgres_harness_database: PostgresHarnessDatabase,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    interruption: str,
) -> None:
    sessions, first = recovery_case
    second = replace(first, lead_id=uuid4(), crm_lead_id="interrupted-repair")
    third = replace(first, lead_id=uuid4(), crm_lead_id="unvisited-repair")
    clean = replace(first, lead_id=uuid4(), crm_lead_id="unrelated-clean-control")
    async with sessions() as setup:
        await enable_postgres_service_access(setup)
        for lead in (second, third, clean):
            await PostgresLeadRepository(setup).upsert(lead)
        setup.add_all((
            suppression_event(first, event_id="prefix-stop"),
            suppression_event(
                second, kind="email_unsubscribed", event_id="interrupted-unsubscribe",
            ),
            suppression_event(third, kind="do_not_contact", event_id="remaining-dnc"),
        ))
        await setup.commit()
    original_history = await _lifecycle_snapshot(sessions, first.workspace_id)
    original_times = await _lead_update_times(sessions, first.workspace_id)
    first_repaired = replace(
        first, sms_opted_out=True, suppression_types=frozenset({SuppressionType.SMS_OPT_OUT}),
        permission_evidence={
            "sms_opt_out_source_provider": "follow_up_boss",
            "sms_opt_out_source_event_id": "prefix-stop",
            "sms_opt_out_occurred_at": "2026-08-01T10:00:00+00:00",
        },
    )
    second_repaired = replace(
        second, email_unsubscribed=True,
        suppression_types=frozenset({SuppressionType.EMAIL_UNSUBSCRIBED}),
        permission_evidence={
            "email_unsubscribed_source_provider": "follow_up_boss",
            "email_unsubscribed_source_event_id": "interrupted-unsubscribe",
            "email_unsubscribed_occurred_at": "2026-08-01T10:00:00+00:00",
        },
    )
    third_repaired = replace(third, do_not_contact=True, permission_evidence={
        "do_not_contact_source_provider": "follow_up_boss",
        "do_not_contact_source_event_id": "remaining-dnc",
        "do_not_contact_occurred_at": "2026-08-01T10:00:00+00:00",
    })
    interrupted_updates: list[UUID] = []

    class InterruptBeforeCommitSession(AsyncSession):
        async def commit(self) -> None:
            updated = await self.scalar(select(LeadModel.email_unsubscribed).where(
                LeadModel.workspace_id == second.workspace_id,
                LeadModel.lead_id == second.lead_id,
            ))
            if updated is True:
                # Observe the actual uncommitted UPDATE, not a simulated repository result.
                interrupted_updates.append(second.lead_id)
                raise asyncio.CancelledError
            await super().commit()

    engine = create_async_engine(
        postgres_harness_database.async_url, poolclass=NullPool,
        connect_args={"server_settings": {"lock_timeout": "1000ms"}},
    )
    fresh_sessions = async_sessionmaker(engine, expire_on_commit=False)
    real_repository = PostgresOptOutRecoveryRepository(fresh_sessions)
    if interruption == "before-commit":
        interrupting_sessions = async_sessionmaker[AsyncSession](
            engine, class_=InterruptBeforeCommitSession, expire_on_commit=False,
        )
        repository: OptOutRecoveryRepository = PostgresOptOutRecoveryRepository(
            interrupting_sessions,
        )
    else:
        repository = InterruptAfterCommitRepository(real_repository, second.lead_id)
    scope = ["--workspace-id", str(first.workspace_id), "--apply", "--reviewed-for-lifts"]
    for lead in (first, second, third):
        scope.extend(("--lead-id", str(lead.lead_id)))
    report_path = tmp_path / "interrupted.jsonl"
    retry_path = tmp_path / "retry.jsonl"
    try:
        exit_code = await asyncio.to_thread(
            main, [*scope, "--report", str(report_path)], repository=repository,
        )
        assert exit_code == 130
        assert "Recovery interrupted" in capsys.readouterr().err
        records = [json.loads(line) for line in report_path.read_text().splitlines()]
        assert [row["type"] for row in records] == ["header", "lead"]
        assert records[1]["lead_id"] == str(first.lead_id)
        assert records[1]["status"] == "changed"
        assert stat.S_IMODE(report_path.stat().st_mode) == 0o600
        assert await read_lead(fresh_sessions, first) == first_repaired
        assert await read_lead(fresh_sessions, second) == (
            second if interruption == "before-commit" else second_repaired
        )
        assert await read_lead(fresh_sessions, third) == third
        assert await read_lead(fresh_sessions, clean) == clean
        after_interruption_times = await _lead_update_times(fresh_sessions, first.workspace_id)
        if interruption == "before-commit":
            assert interrupted_updates == [second.lead_id]
            assert after_interruption_times[second.lead_id] == original_times[second.lead_id]
        assert await _lifecycle_snapshot(fresh_sessions, first.workspace_id) == original_history

        # An independent connection must immediately acquire the cancelled lead's lock.
        async with fresh_sessions() as observer:
            await enable_postgres_service_access(observer)
            locked = await PostgresLeadRepository(observer).get_by_id_for_update(
                second.workspace_id, second.lead_id,
            )
            assert locked is not None
            await observer.rollback()

        retry_exit = await asyncio.to_thread(
            main, [*scope, "--report", str(retry_path)], repository=real_repository,
        )
        assert retry_exit == 0
        retry_records = [json.loads(line) for line in retry_path.read_text().splitlines()]
        assert [row["status"] for row in retry_records[1:-1]] == [
            "already_correct",
            "changed" if interruption == "before-commit" else "already_correct",
            "changed",
        ]
        assert retry_records[-1] == {
            "type": "completed",
            "totals": {
                "scoped": 3, "processed": 3, "candidate": 3, "clean": 0,
                "already_correct": 1 if interruption == "before-commit" else 2,
                "changed": 2 if interruption == "before-commit" else 1,
                "would_change": 0, "unresolved": 0, "failed": 0,
            },
        }
        for lead, expected in (
            (first, first_repaired), (second, second_repaired),
            (third, third_repaired), (clean, clean),
        ):
            assert await read_lead(fresh_sessions, lead) == expected
        final_times = await _lead_update_times(fresh_sessions, first.workspace_id)
        assert final_times[first.lead_id] == after_interruption_times[first.lead_id]
        assert final_times[clean.lead_id] == original_times[clean.lead_id]
        if interruption != "before-commit":
            assert final_times[second.lead_id] == after_interruption_times[second.lead_id]
        assert await _lifecycle_snapshot(fresh_sessions, first.workspace_id) == original_history
        assert [json.loads(line) for line in report_path.read_text().splitlines()] == records
    finally:
        await engine.dispose()