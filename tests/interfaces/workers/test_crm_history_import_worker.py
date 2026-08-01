from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.domain.crm_history_imports import (
    CrmHistoryImportEventStatus,
    CrmHistoryImportJob,
    CrmHistoryImportJobStatus,
    StagedCrmHistoryImportEvent,
)
from app.interfaces.workers import crm_history_import_worker
from tests.application.use_cases._crm_history_import_fakes import (
    FakeAuthAuditLogRepository,
    FakeCrmConversationEventRepository,
    FakeCrmHistoryImportEventRepository,
    FakeCrmHistoryImportJobRepository,
)
from tests.application.use_cases.test_crm_history_imports import (
    ACTOR_ID,
    LEAD_ID,
    NOW,
    WORKSPACE_ID,
)


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb

    async def commit(self) -> None:
        self.committed = True


async def test_run_once_claims_promotes_and_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    jobs = FakeCrmHistoryImportJobRepository()
    staged = FakeCrmHistoryImportEventRepository()
    canonical = FakeCrmConversationEventRepository()
    audit = FakeAuthAuditLogRepository()
    job = _ready_job()
    jobs.jobs[(WORKSPACE_ID, job.import_job_id)] = job
    event = StagedCrmHistoryImportEvent(
        import_event_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        import_job_id=job.import_job_id,
        lead_id=LEAD_ID,
        fingerprint="worker-event",
        activity_type="Text",
        occurred_at=NOW,
        status=CrmHistoryImportEventStatus.RECEIVED,
        created_at=NOW,
    )
    await staged.insert_received((event,))

    async def fake_enable_service_access(_: object) -> None:
        return None

    monkeypatch.setattr(crm_history_import_worker, "async_session_factory", lambda: session)
    monkeypatch.setattr(
        crm_history_import_worker, "enable_postgres_service_access", fake_enable_service_access
    )
    monkeypatch.setattr(
        crm_history_import_worker, "PostgresCrmHistoryImportJobRepository", lambda _: jobs
    )
    monkeypatch.setattr(
        crm_history_import_worker, "PostgresCrmHistoryImportEventRepository", lambda _: staged
    )
    monkeypatch.setattr(
        crm_history_import_worker, "PostgresCrmConversationEventRepository", lambda _: canonical
    )
    monkeypatch.setattr(
        crm_history_import_worker, "PostgresAuthAuditLogRepository", lambda _: audit
    )

    processed = await crm_history_import_worker.run_once(limit=5)

    assert processed == 1
    assert session.committed is True
    assert len(canonical.events) == 1
    assert next(iter(jobs.jobs.values())).status is CrmHistoryImportJobStatus.COMPLETED


def _ready_job() -> CrmHistoryImportJob:
    return CrmHistoryImportJob(
        import_job_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_lead_id="fub-history-lead",
        requested_by_user_id=ACTOR_ID,
        status=CrmHistoryImportJobStatus.READY,
        upload_token_hash="0" * 64,
        token_expires_at=NOW + timedelta(days=1),
        upload_completed_at=NOW,
        created_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
        updated_at=NOW,
    )