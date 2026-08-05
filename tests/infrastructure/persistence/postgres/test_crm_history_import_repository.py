from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.crm_history_imports import promote_crm_history_import
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.crm_history_imports import (
    CrmHistoryImportEventStatus,
    CrmHistoryImportJob,
    CrmHistoryImportJobStatus,
    StagedCrmHistoryImportEvent,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresCrmConversationEventRepository,
)
from app.infrastructure.persistence.postgres.crm_history_import_repository import (
    PostgresCrmHistoryImportEventRepository,
    PostgresCrmHistoryImportJobRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import UserModel, WorkspaceModel

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("b0000000-0000-0000-0000-000000000001")
OTHER_WORKSPACE_ID = UUID("b0000000-0000-0000-0000-000000000002")
USER_ID = UUID("b0000000-0000-0000-0000-000000000003")
LEAD_ID = UUID("b0000000-0000-0000-0000-000000000004")


async def test_staging_duplicate_claim_and_promotion_to_canonical_row(
    postgres_session: AsyncSession,
) -> None:
    await _seed(postgres_session)
    jobs = PostgresCrmHistoryImportJobRepository(postgres_session)
    staged = PostgresCrmHistoryImportEventRepository(postgres_session)
    canonical = PostgresCrmConversationEventRepository(postgres_session)
    job = _job()
    assert await jobs.create(job) == job
    event = _event(job)

    first = await staged.insert_received((event,))
    duplicate = await staged.insert_received((replace(event, import_event_id=uuid4()),))
    assert len(first) == 1
    assert duplicate == ()
    assert await jobs.get_by_id(OTHER_WORKSPACE_ID, job.import_job_id) is None

    ready = await jobs.save(
        replace(
            job,
            status=CrmHistoryImportJobStatus.READY,
            received_count=1,
            duplicate_count=1,
            upload_completed_at=NOW,
        )
    )
    claimed = await jobs.claim_ready(now=NOW, limit=10)
    assert len(claimed) == 1
    promoted = await promote_crm_history_import(
        job=claimed[0],
        job_repository=jobs,
        event_repository=staged,
        conversation_event_repository=canonical,
        now=NOW,
    )
    canonical_events = await canonical.list_for_lead(WORKSPACE_ID, LEAD_ID, limit=10)

    assert ready.status is CrmHistoryImportJobStatus.READY
    assert promoted.status is CrmHistoryImportJobStatus.COMPLETED
    assert promoted.promoted_count == 1
    assert canonical_events[0].crm_activity_id == "extension:activity-1"
    assert await staged.list_received(WORKSPACE_ID, job.import_job_id) == ()


async def test_extension_and_pulled_history_converge_in_both_arrival_orders(
    postgres_session: AsyncSession,
) -> None:
    await _seed(postgres_session)
    canonical = PostgresCrmConversationEventRepository(postgres_session)

    await canonical.save(_pulled_event("text_message:1", "First message", NOW))
    await canonical.save(_extension_event("extension-fingerprint:first", "First message", NOW))
    await canonical.save(
        _extension_event(
            "extension-fingerprint:second",
            "Second message",
            NOW + timedelta(minutes=1),
        )
    )
    await canonical.save(
        _pulled_event(
            "text_message:2",
            "Second message",
            NOW + timedelta(minutes=1),
        )
    )
    await canonical.save(
        _extension_event("extension-fingerprint:first-edit", "First message edited", NOW)
    )
    await canonical.save(_pulled_event("text_message:1", "First message edited", NOW))

    events = await canonical.list_for_lead(WORKSPACE_ID, LEAD_ID, limit=10)

    assert len(events) == 2
    assert {event.crm_activity_id for event in events} == {
        "text_message:1",
        "text_message:2",
    }
    assert all(event.source_payload_version == "follow_up_boss/v1" for event in events)
    assert {event.content for event in events} == {"First message edited", "Second message"}


async def _seed(session: AsyncSession) -> None:
    session.add_all(
        [
            WorkspaceModel(
                workspace_id=WORKSPACE_ID,
                name="History Import Workspace",
                status="active",
                default_timezone="UTC",
                created_at=NOW,
                updated_at=NOW,
            ),
            UserModel(
                user_id=USER_ID,
                email="history-import@example.com",
                email_normalized="history-import@example.com",
                full_name="History Import Manager",
                status="active",
                created_at=NOW,
                updated_at=NOW,
            ),
        ]
    )
    await session.flush()
    await PostgresLeadRepository(session).upsert(
        CanonicalLeadRecord(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            crm_lead_id="fub-history-lead",
            facts_derived_at=NOW,
            source_payload_version="test:v1",
        )
    )


def _job() -> CrmHistoryImportJob:
    return CrmHistoryImportJob(
        import_job_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_lead_id="fub-history-lead",
        requested_by_user_id=USER_ID,
        status=CrmHistoryImportJobStatus.RECEIVING,
        upload_token_hash="0" * 64,
        token_expires_at=NOW + timedelta(days=1),
        created_at=NOW,
        updated_at=NOW,
    )


def _event(job: CrmHistoryImportJob) -> StagedCrmHistoryImportEvent:
    return StagedCrmHistoryImportEvent(
        import_event_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        import_job_id=job.import_job_id,
        lead_id=LEAD_ID,
        external_activity_id="activity-1",
        fingerprint="fingerprint-1",
        activity_type="Text",
        occurred_at=NOW - timedelta(days=30),
        status=CrmHistoryImportEventStatus.RECEIVED,
        content="Historical message",
        created_at=NOW,
    )


def _pulled_event(activity_id: str, content: str, occurred_at: datetime) -> CrmConversationEvent:
    return CrmConversationEvent(
        crm_conversation_event_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        crm_activity_id=activity_id,
        activity_type="Text message",
        direction=CrmConversationEventDirection.INBOUND,
        occurred_at=occurred_at,
        content=content,
        source_payload_version="follow_up_boss/v1",
        created_at=NOW,
        updated_at=NOW,
    )


def _extension_event(
    activity_id: str, content: str, occurred_at: datetime
) -> CrmConversationEvent:
    return CrmConversationEvent(
        crm_conversation_event_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        crm_activity_id=activity_id,
        activity_type="text",
        direction=CrmConversationEventDirection.INBOUND,
        occurred_at=occurred_at,
        content=content,
        source_payload_version="extension/v1",
        created_at=NOW,
        updated_at=NOW,
    )