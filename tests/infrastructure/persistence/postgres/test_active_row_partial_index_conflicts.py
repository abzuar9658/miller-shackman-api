import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, time
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.services.campaign_enrollment_starter import (
    start_single_campaign_enrollment,
)
from app.application.use_cases.campaign_enrollment_types import LeadStartResult, LeadStartStatus
from app.core.database import enable_postgres_service_access
from app.domain.campaigns.enrollment import CampaignEnrollmentSource
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance import ContactChannel
from app.domain.crm_sync import CRMSyncJob, CRMSyncJobStatus, CRMSyncType
from app.domain.leads import CRMProvider
from app.domain.listing_sources import ListingCrawlRun, ListingCrawlStatus
from app.domain.workflows import LeadWorkflow
from app.infrastructure.persistence.postgres.campaign_enrollment_repository import (
    PostgresCampaignEnrollmentRepository,
)
from app.infrastructure.persistence.postgres.crm_sync_repository import PostgresCRMSyncJobRepository
from app.infrastructure.persistence.postgres.listing_source_repository import (
    PostgresListingCrawlRunRepository,
)
from app.infrastructure.persistence.postgres.models import (
    CampaignModel,
    CampaignVersionModel,
    LeadModel,
    OutboundMessageModel,
    UserModel,
    WorkspaceModel,
)
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.workflow_models import (
    CampaignEnrollmentModel,
    LeadWorkflowModel,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import FakeTemporalWorkflowStarter
from tests.infrastructure.persistence.postgres._harness import PostgresHarnessDatabase

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
WORKSPACE_ID = WorkspaceId("f2222222-2222-2222-2222-222222222222")
SOURCE_ID = UUID("22222222-2222-2222-2222-222222222223")
USER_ID = UUID("22222222-2222-2222-2222-222222222224")
LEAD_ID = UUID("22222222-2222-2222-2222-222222222225")
CAMPAIGN_ID = UUID("22222222-2222-2222-2222-222222222226")
CAMPAIGN_VERSION_ID = UUID("22222222-2222-2222-2222-222222222227")
ENROLLMENT_ID = UUID("22222222-2222-2222-2222-222222222228")
WORKFLOW_ID = UUID("22222222-2222-2222-2222-222222222229")
OTHER_WORKFLOW_ID = UUID("22222222-2222-2222-2222-22222222222a")
OTHER_CAMPAIGN_ID = UUID("22222222-2222-2222-2222-22222222222b")
OTHER_CAMPAIGN_VERSION_ID = UUID("22222222-2222-2222-2222-22222222222c")


class _FakeResult:
    def scalar_one_or_none(self) -> None:
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _FakeResult:
        self.statements.append(statement)
        return _FakeResult()


def test_crm_sync_insert_pending_uses_literal_partial_index_predicate() -> None:
    session = _FakeSession()

    _run(
        PostgresCRMSyncJobRepository(cast(AsyncSession, session)).insert_pending_if_no_active(
            _pending_sync_job(),
        )
    )

    statement = cast(Any, session.statements[0])
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    compiled = str(statement.compile(dialect=dialect))
    assert "ON CONFLICT (workspace_id, crm_provider)" in compiled
    assert "WHERE status IN ('pending', 'running')" in compiled
    assert "POSTCOMPILE" not in compiled


def test_listing_crawl_insert_pending_uses_literal_partial_index_predicate() -> None:
    session = _FakeSession()

    _run(
        PostgresListingCrawlRunRepository(cast(AsyncSession, session)).insert_pending_if_no_active(
            _pending_crawl_run(),
        )
    )

    statement = cast(Any, session.statements[0])
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    compiled = str(statement.compile(dialect=dialect))
    assert "ON CONFLICT (workspace_id, source_id)" in compiled
    assert "WHERE status IN ('pending', 'running')" in compiled
    assert "POSTCOMPILE" not in compiled


@pytest.mark.asyncio
async def test_crm_sync_insert_pending_enforces_single_active_job(
    postgres_session: AsyncSession,
) -> None:
    await _seed_workspace(postgres_session)
    repository = PostgresCRMSyncJobRepository(postgres_session)

    first = await repository.insert_pending_if_no_active(_pending_sync_job())
    duplicate = await repository.insert_pending_if_no_active(_pending_sync_job(sync_job_id=uuid4()))
    active = await repository.get_active_for_workspace_provider(
        WORKSPACE_ID,
        CRMProvider.FOLLOW_UP_BOSS.value,
    )

    assert first is not None
    assert duplicate is None
    assert active == first


@pytest.mark.asyncio
async def test_lead_workflows_reject_second_non_terminal_workflow_for_same_lead(
    postgres_session: AsyncSession,
) -> None:
    await _seed_workflow_graph(postgres_session)

    postgres_session.add(_lead_workflow_model(WORKFLOW_ID, "active_nurture"))
    await postgres_session.flush()

    postgres_session.add(_lead_workflow_model(OTHER_WORKFLOW_ID, "queued"))
    with pytest.raises(IntegrityError):
        await postgres_session.flush()


@pytest.mark.asyncio
async def test_lead_workflows_allow_new_workflow_after_terminal_state(
    postgres_session: AsyncSession,
) -> None:
    await _seed_workflow_graph(postgres_session)

    postgres_session.add(_lead_workflow_model(WORKFLOW_ID, "completed"))
    await postgres_session.flush()

    postgres_session.add(_lead_workflow_model(OTHER_WORKFLOW_ID, "queued"))
    await postgres_session.flush()


class _TwoPartyGate:
    def __init__(self) -> None:
        self._arrivals = 0
        self._lock = asyncio.Lock()
        self._ready = asyncio.Event()

    async def wait(self) -> None:
        async with self._lock:
            self._arrivals += 1
            if self._arrivals == 2:
                self._ready.set()
        await self._ready.wait()


class _BarrierLeadWorkflowRepository(PostgresLeadWorkflowRepository):
    def __init__(self, session: AsyncSession, gate: _TwoPartyGate) -> None:
        super().__init__(session)
        self._gate = gate

    async def get_latest_for_lead_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> LeadWorkflow | None:
        latest = await super().get_latest_for_lead_for_update(workspace_id, lead_id)
        await self._gate.wait()
        return latest


@pytest.mark.asyncio
async def test_concurrent_enrollment_starters_create_one_active_workflow(
    postgres_harness_database: PostgresHarnessDatabase,
) -> None:
    engine = create_async_engine(
        postgres_harness_database.async_url,
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as seed_session:
        await enable_postgres_service_access(seed_session)
        await _seed_lead_campaign_graph(seed_session)
        other_campaign = CampaignModel(
            campaign_id=OTHER_CAMPAIGN_ID,
            workspace_id=WORKSPACE_ID,
            name="Other campaign",
            status="active",
            active_version_id=None,
            created_by_user_id=USER_ID,
            created_at=NOW,
            updated_at=NOW,
        )
        seed_session.add(other_campaign)
        await seed_session.flush()
        seed_session.add(
            CampaignVersionModel(
                campaign_version_id=OTHER_CAMPAIGN_VERSION_ID,
                workspace_id=WORKSPACE_ID,
                campaign_id=OTHER_CAMPAIGN_ID,
                version_number=1,
                status="published",
                enabled_channels=["email"],
                daily_start_cap=50,
                dormant_threshold_days=60,
                quiet_hours_start=time(10, 0),
                quiet_hours_end=time(17, 0),
                timezone="UTC",
                preflight_digest_enabled=False,
                prompt_version="v1",
                approved_model="test-model",
                created_by_user_id=USER_ID,
                created_at=NOW,
            )
        )
        await seed_session.flush()
        other_campaign.active_version_id = OTHER_CAMPAIGN_VERSION_ID
        await seed_session.commit()

    gate = _TwoPartyGate()
    temporal_starter = FakeTemporalWorkflowStarter()

    async def attempt(campaign_id: UUID, version_id: UUID) -> LeadStartResult:
        async with session_factory() as attempt_session:
            await enable_postgres_service_access(attempt_session)
            return await start_single_campaign_enrollment(
                workspace_id=WORKSPACE_ID,
                campaign_id=campaign_id,
                campaign_version_id=version_id,
                lead_id=LEAD_ID,
                source=CampaignEnrollmentSource.DORMANT_SELECTOR,
                reason_codes=(),
                actor_user_id=None,
                campaign_enrollment_repository=PostgresCampaignEnrollmentRepository(
                    attempt_session
                ),
                lead_workflow_repository=_BarrierLeadWorkflowRepository(
                    attempt_session,
                    gate,
                ),
                workflow_transition_repository=PostgresWorkflowTransitionRepository(
                    attempt_session
                ),
                temporal_workflow_starter=temporal_starter,
                now=NOW,
                commit=attempt_session.commit,
                rollback=attempt_session.rollback,
            )

    results = await asyncio.gather(
        attempt(CAMPAIGN_ID, CAMPAIGN_VERSION_ID),
        attempt(OTHER_CAMPAIGN_ID, OTHER_CAMPAIGN_VERSION_ID),
    )

    assert sorted(result.status for result in results) == [
        LeadStartStatus.ALREADY_ACTIVE_ELSEWHERE,
        LeadStartStatus.STARTED,
    ]
    assert len(temporal_starter.calls) == 1
    async with session_factory() as verification_session:
        await enable_postgres_service_access(verification_session)
        workflow_count = await verification_session.scalar(
            select(func.count())
            .select_from(LeadWorkflowModel)
            .where(LeadWorkflowModel.lead_id == LEAD_ID)
        )
        enrollment_count = await verification_session.scalar(
            select(func.count())
            .select_from(CampaignEnrollmentModel)
            .where(CampaignEnrollmentModel.lead_id == LEAD_ID)
        )
    assert workflow_count == 1
    assert enrollment_count == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_outbound_history_queries_return_latest_sent_timestamp_by_scope(
    postgres_session: AsyncSession,
) -> None:
    other_workspace_id = WorkspaceId("f3333333-3333-3333-3333-333333333333")
    campaign_a = UUID("f3333333-3333-3333-3333-333333333334")
    campaign_b = UUID("f3333333-3333-3333-3333-333333333335")
    lead_id = UUID("f3333333-3333-3333-3333-333333333336")

    def message(
        *,
        workspace_id: WorkspaceId,
        campaign_id: UUID,
        channel: str,
        status: str,
        sent_at: datetime | None,
        suffix: str,
    ) -> OutboundMessageModel:
        return OutboundMessageModel(
            message_id=uuid4(),
            workspace_id=workspace_id,
            lead_id=lead_id,
            campaign_id=campaign_id,
            cadence_step_id=f"step-{suffix}",
            channel=channel,
            status=status,
            idempotency_key=f"history-{suffix}",
            body="history",
            sent_at=sent_at,
            provider_send_status="not_attempted",
            created_at=NOW,
            updated_at=NOW,
        )

    postgres_session.add_all(
        [
            message(
                workspace_id=WORKSPACE_ID,
                campaign_id=campaign_a,
                channel="sms",
                status="sent",
                sent_at=NOW.replace(hour=10),
                suffix="a-sms",
            ),
            message(
                workspace_id=WORKSPACE_ID,
                campaign_id=campaign_a,
                channel="email",
                status="sent",
                sent_at=NOW.replace(hour=11),
                suffix="a-email",
            ),
            message(
                workspace_id=WORKSPACE_ID,
                campaign_id=campaign_b,
                channel="sms",
                status="sent",
                sent_at=NOW.replace(hour=12),
                suffix="b-sms",
            ),
            message(
                workspace_id=WORKSPACE_ID,
                campaign_id=campaign_a,
                channel="sms",
                status="pending",
                sent_at=None,
                suffix="pending",
            ),
            message(
                workspace_id=other_workspace_id,
                campaign_id=campaign_b,
                channel="sms",
                status="sent",
                sent_at=NOW.replace(hour=23),
                suffix="other-workspace",
            ),
        ]
    )
    await postgres_session.commit()

    repository = PostgresOutboundMessageRepository(postgres_session)

    assert await repository.get_latest_sent_at_for_lead(WORKSPACE_ID, lead_id) == NOW.replace(
        hour=12
    )
    assert await repository.get_latest_sent_at_for_lead(
        WORKSPACE_ID,
        lead_id,
        campaign_id=campaign_a,
    ) == NOW.replace(hour=11)
    assert await repository.get_latest_sent_at_for_lead(
        WORKSPACE_ID,
        lead_id,
        campaign_id=campaign_a,
        channel=ContactChannel.SMS,
    ) == NOW.replace(hour=10)
    assert await repository.get_latest_sent_at_for_lead(
        WORKSPACE_ID,
        lead_id,
        channel=ContactChannel.EMAIL,
    ) == NOW.replace(hour=11)


def _lead_workflow_model(workflow_id: UUID, state: str) -> LeadWorkflowModel:
    return LeadWorkflowModel(
        workflow_id=workflow_id,
        temporal_workflow_id=f"lead-nurture:{workflow_id}",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=state,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


async def _seed_workflow_graph(session: AsyncSession) -> None:
    await _seed_lead_campaign_graph(session)
    session.add(
        CampaignEnrollmentModel(
            campaign_enrollment_id=ENROLLMENT_ID,
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
            lead_id=LEAD_ID,
            source="manual_admin",
            status="active",
            reason_codes=[],
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()


async def _seed_lead_campaign_graph(session: AsyncSession) -> None:
    await _seed_workspace(session)
    session.add(
        UserModel(
            user_id=USER_ID,
            email="active-row-owner@example.com",
            email_normalized="active-row-owner@example.com",
            status="active",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.add(
        LeadModel(
            lead_id=LEAD_ID,
            workspace_id=WORKSPACE_ID,
            crm_provider="follow_up_boss",
            crm_lead_id="crm-1",
            has_accountable_owner=True,
            lead_type="buyer",
            classification_reason="crm_type_buyer",
            activity_reliability="reliable",
            sms_permission_status="unknown",
            email_permission_status="unknown",
            source_payload_version="test:v1",
            facts_derived_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()

    session.add(
        CampaignModel(
            campaign_id=CAMPAIGN_ID,
            workspace_id=WORKSPACE_ID,
            name="Dormant Reengagement",
            status="active",
            active_version_id=None,
            created_by_user_id=USER_ID,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()

    session.add(
        CampaignVersionModel(
            campaign_version_id=CAMPAIGN_VERSION_ID,
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            version_number=1,
            status="published",
            enabled_channels=["email"],
            daily_start_cap=50,
            dormant_threshold_days=60,
            quiet_hours_start=time(10, 0),
            quiet_hours_end=time(17, 0),
            timezone="UTC",
            preflight_digest_enabled=False,
            prompt_version="v1",
            approved_model="openai/gpt-4o-mini",
            created_by_user_id=USER_ID,
            created_at=NOW,
        )
    )
    await session.flush()

async def _seed_workspace(session: AsyncSession) -> None:
    session.add(
        WorkspaceModel(
            workspace_id=WORKSPACE_ID,
            name="Test Workspace",
            status="active",
            default_timezone="America/Chicago",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()


def _pending_sync_job(*, sync_job_id: UUID | None = None) -> CRMSyncJob:
    return CRMSyncJob(
        sync_job_id=sync_job_id or uuid4(),
        workspace_id=WORKSPACE_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        sync_type=CRMSyncType.INCREMENTAL,
        status=CRMSyncJobStatus.PENDING,
        started_at=None,
        finished_at=None,
        cursor_started_at=None,
        cursor_finished_at=None,
        total_seen=0,
        total_upserted=0,
        total_failed=0,
        failure_reason=None,
        last_heartbeat_at=None,
        created_by_user_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _pending_crawl_run() -> ListingCrawlRun:
    return ListingCrawlRun(
        crawl_run_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        source_id=SOURCE_ID,
        status=ListingCrawlStatus.PENDING,
        started_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)
