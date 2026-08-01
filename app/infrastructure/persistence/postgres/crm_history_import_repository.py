from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.crm_history_imports import (
    CrmHistoryImportDirection,
    CrmHistoryImportEventStatus,
    CrmHistoryImportJob,
    CrmHistoryImportJobStatus,
    StagedCrmHistoryImportEvent,
)
from app.infrastructure.persistence.postgres.models import (
    CrmHistoryImportEventModel,
    CrmHistoryImportJobModel,
)

_ACTIVE_JOB_STATUSES = tuple(
    status.value
    for status in (
        CrmHistoryImportJobStatus.PENDING,
        CrmHistoryImportJobStatus.RECEIVING,
        CrmHistoryImportJobStatus.READY,
        CrmHistoryImportJobStatus.RUNNING,
    )
)


class PostgresCrmHistoryImportJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self, workspace_id: UUID, import_job_id: UUID
    ) -> CrmHistoryImportJob | None:
        result = await self._session.execute(
            select(CrmHistoryImportJobModel).where(
                CrmHistoryImportJobModel.workspace_id == workspace_id,
                CrmHistoryImportJobModel.import_job_id == import_job_id,
            )
        )
        model = result.scalar_one_or_none()
        return _job_from_model(model) if model is not None else None

    async def get_for_update(
        self, workspace_id: UUID, import_job_id: UUID
    ) -> CrmHistoryImportJob | None:
        result = await self._session.execute(
            select(CrmHistoryImportJobModel)
            .where(
                CrmHistoryImportJobModel.workspace_id == workspace_id,
                CrmHistoryImportJobModel.import_job_id == import_job_id,
            )
            .with_for_update()
        )
        model = result.scalar_one_or_none()
        return _job_from_model(model) if model is not None else None

    async def get_active_for_lead(
        self, workspace_id: UUID, lead_id: UUID
    ) -> CrmHistoryImportJob | None:
        result = await self._session.execute(
            select(CrmHistoryImportJobModel)
            .where(
                CrmHistoryImportJobModel.workspace_id == workspace_id,
                CrmHistoryImportJobModel.lead_id == lead_id,
                CrmHistoryImportJobModel.status.in_(_ACTIVE_JOB_STATUSES),
            )
            .order_by(CrmHistoryImportJobModel.created_at.desc())
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return _job_from_model(model) if model is not None else None

    async def create(self, job: CrmHistoryImportJob) -> CrmHistoryImportJob | None:
        result = await self._session.execute(
            insert(CrmHistoryImportJobModel)
            .values(**_job_values(job))
            .on_conflict_do_nothing()
            .returning(CrmHistoryImportJobModel)
        )
        model = result.scalar_one_or_none()
        return _job_from_model(model) if model is not None else None

    async def save(self, job: CrmHistoryImportJob) -> CrmHistoryImportJob:
        values = _job_values(job)
        values.pop("import_job_id")
        values.pop("workspace_id")
        result = await self._session.execute(
            update(CrmHistoryImportJobModel)
            .where(
                CrmHistoryImportJobModel.workspace_id == job.workspace_id,
                CrmHistoryImportJobModel.import_job_id == job.import_job_id,
            )
            .values(**values)
            .returning(CrmHistoryImportJobModel)
        )
        return _job_from_model(result.scalar_one())

    async def claim_ready(
        self, *, now: datetime, limit: int
    ) -> tuple[CrmHistoryImportJob, ...]:
        claimable_ids = (
            select(CrmHistoryImportJobModel.import_job_id)
            .where(CrmHistoryImportJobModel.status == CrmHistoryImportJobStatus.READY.value)
            .order_by(
                CrmHistoryImportJobModel.upload_completed_at.asc().nulls_last(),
                CrmHistoryImportJobModel.created_at.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(
            update(CrmHistoryImportJobModel)
            .where(CrmHistoryImportJobModel.import_job_id.in_(claimable_ids))
            .values(
                status=CrmHistoryImportJobStatus.RUNNING.value,
                started_at=now,
                updated_at=now,
                failure_reason=None,
            )
            .returning(CrmHistoryImportJobModel)
        )
        return tuple(_job_from_model(model) for model in result.scalars().all())


class PostgresCrmHistoryImportEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_received(
        self, events: tuple[StagedCrmHistoryImportEvent, ...]
    ) -> tuple[StagedCrmHistoryImportEvent, ...]:
        if not events:
            return ()
        result = await self._session.execute(
            insert(CrmHistoryImportEventModel)
            .values([_event_values(event) for event in events])
            .on_conflict_do_nothing(
                index_elements=["workspace_id", "import_job_id", "fingerprint"]
            )
            .returning(CrmHistoryImportEventModel)
        )
        return tuple(_event_from_model(model) for model in result.scalars().all())

    async def list_received(
        self, workspace_id: UUID, import_job_id: UUID
    ) -> tuple[StagedCrmHistoryImportEvent, ...]:
        result = await self._session.execute(
            select(CrmHistoryImportEventModel)
            .where(
                CrmHistoryImportEventModel.workspace_id == workspace_id,
                CrmHistoryImportEventModel.import_job_id == import_job_id,
                CrmHistoryImportEventModel.status
                == CrmHistoryImportEventStatus.RECEIVED.value,
            )
            .order_by(
                CrmHistoryImportEventModel.occurred_at.asc(),
                CrmHistoryImportEventModel.created_at.asc(),
            )
        )
        return tuple(_event_from_model(model) for model in result.scalars().all())

    async def save(
        self, event: StagedCrmHistoryImportEvent
    ) -> StagedCrmHistoryImportEvent:
        values = _event_values(event)
        for immutable_key in ("import_event_id", "workspace_id", "import_job_id"):
            values.pop(immutable_key)
        result = await self._session.execute(
            update(CrmHistoryImportEventModel)
            .where(
                CrmHistoryImportEventModel.workspace_id == event.workspace_id,
                CrmHistoryImportEventModel.import_job_id == event.import_job_id,
                CrmHistoryImportEventModel.import_event_id == event.import_event_id,
            )
            .values(**values)
            .returning(CrmHistoryImportEventModel)
        )
        return _event_from_model(result.scalar_one())


def _job_values(job: CrmHistoryImportJob) -> dict[str, object]:
    return {
        "import_job_id": job.import_job_id,
        "workspace_id": job.workspace_id,
        "lead_id": job.lead_id,
        "crm_lead_id": job.crm_lead_id,
        "requested_by_user_id": job.requested_by_user_id,
        "status": job.status.value,
        "upload_token_hash": job.upload_token_hash,
        "token_expires_at": job.token_expires_at,
        "received_count": job.received_count,
        "promoted_count": job.promoted_count,
        "duplicate_count": job.duplicate_count,
        "rejected_count": job.rejected_count,
        "failure_count": job.failure_count,
        "upload_completed_at": job.upload_completed_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "failure_reason": job.failure_reason,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _job_from_model(model: CrmHistoryImportJobModel) -> CrmHistoryImportJob:
    return CrmHistoryImportJob(
        import_job_id=model.import_job_id,
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        crm_lead_id=model.crm_lead_id,
        requested_by_user_id=model.requested_by_user_id,
        status=CrmHistoryImportJobStatus(model.status),
        upload_token_hash=model.upload_token_hash,
        token_expires_at=model.token_expires_at,
        received_count=model.received_count,
        promoted_count=model.promoted_count,
        duplicate_count=model.duplicate_count,
        rejected_count=model.rejected_count,
        failure_count=model.failure_count,
        upload_completed_at=model.upload_completed_at,
        started_at=model.started_at,
        completed_at=model.completed_at,
        failure_reason=model.failure_reason,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _event_values(event: StagedCrmHistoryImportEvent) -> dict[str, object]:
    return {
        "import_event_id": event.import_event_id,
        "workspace_id": event.workspace_id,
        "import_job_id": event.import_job_id,
        "lead_id": event.lead_id,
        "external_activity_id": event.external_activity_id,
        "fingerprint": event.fingerprint,
        "activity_type": event.activity_type,
        "direction": event.direction.value if event.direction is not None else None,
        "content": event.content,
        "occurred_at": event.occurred_at,
        "actor_agent_id": event.actor_agent_id,
        "actor_name": event.actor_name,
        "details": dict(event.details),
        "status": event.status.value,
        "promoted_at": event.promoted_at,
        "failure_reason": event.failure_reason,
        "created_at": event.created_at,
    }


def _event_from_model(model: CrmHistoryImportEventModel) -> StagedCrmHistoryImportEvent:
    return StagedCrmHistoryImportEvent(
        import_event_id=model.import_event_id,
        workspace_id=model.workspace_id,
        import_job_id=model.import_job_id,
        lead_id=model.lead_id,
        external_activity_id=model.external_activity_id,
        fingerprint=model.fingerprint,
        activity_type=model.activity_type,
        direction=(
            CrmHistoryImportDirection(model.direction) if model.direction is not None else None
        ),
        content=model.content,
        occurred_at=model.occurred_at,
        actor_agent_id=model.actor_agent_id,
        actor_name=model.actor_name,
        details=model.details or {},
        status=CrmHistoryImportEventStatus(model.status),
        promoted_at=model.promoted_at,
        failure_reason=model.failure_reason,
        created_at=model.created_at,
    )