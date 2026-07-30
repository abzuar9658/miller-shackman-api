from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.domain.common.ids import WorkspaceId
from app.domain.crm_sync import (
    CRMSyncJob,
    CRMSyncJobStatus,
    CRMSyncLeadSort,
    CRMSyncType,
    CRMSyncWindowState,
    ExternalEvent,
    ExternalEventStatus,
)
from app.infrastructure.persistence.postgres.models import (
    CRMSyncJobModel,
    CRMSyncWindowStateModel,
    ExternalEventModel,
)
from app.infrastructure.persistence.postgres.partial_index_predicates import (
    PENDING_RUNNING_STATUS_INDEX_WHERE_SQL,
)


class PostgresCRMSyncJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        sync_job_id: UUID,
    ) -> CRMSyncJob | None:
        statement = (
            select(CRMSyncJobModel)
            .where(CRMSyncJobModel.workspace_id == workspace_id)
            .where(CRMSyncJobModel.sync_job_id == sync_job_id)
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        return _model_to_sync_job(model) if model is not None else None

    async def list_recent(
        self,
        workspace_id: WorkspaceId,
        limit: int = 100,
    ) -> tuple[CRMSyncJob, ...]:
        statement = (
            select(CRMSyncJobModel)
            .where(CRMSyncJobModel.workspace_id == workspace_id)
            .order_by(CRMSyncJobModel.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        models = result.scalars().all()
        return tuple(_model_to_sync_job(model) for model in models)

    async def get_latest_for_workspace_provider(
        self,
        workspace_id: WorkspaceId,
        crm_provider: str,
    ) -> CRMSyncJob | None:
        statement = _workspace_provider_jobs_statement(workspace_id, crm_provider).limit(1)
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        return _model_to_sync_job(model) if model is not None else None

    async def get_latest_completed_for_workspace_provider(
        self,
        workspace_id: WorkspaceId,
        crm_provider: str,
    ) -> CRMSyncJob | None:
        statement = (
            _workspace_provider_jobs_statement(workspace_id, crm_provider)
            .where(CRMSyncJobModel.status == CRMSyncJobStatus.COMPLETED.value)
            .limit(1)
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        return _model_to_sync_job(model) if model is not None else None

    async def get_active_for_workspace_provider(
        self,
        workspace_id: WorkspaceId,
        crm_provider: str,
    ) -> CRMSyncJob | None:
        statement = (
            _workspace_provider_jobs_statement(workspace_id, crm_provider)
            .where(CRMSyncJobModel.status.in_(_ACTIVE_SYNC_JOB_STATUSES))
            .limit(1)
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        return _model_to_sync_job(model) if model is not None else None

    async def insert_pending_if_no_active(self, job: CRMSyncJob) -> CRMSyncJob | None:
        statement = (
            insert(CRMSyncJobModel)
            .values(**_sync_job_to_values(job))
            .on_conflict_do_nothing(
                index_elements=["workspace_id", "crm_provider"],
                index_where=text(PENDING_RUNNING_STATUS_INDEX_WHERE_SQL),
            )
            .returning(CRMSyncJobModel)
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        return _model_to_sync_job(model) if model is not None else None

    async def claim_pending_by_id(
        self,
        workspace_id: WorkspaceId,
        sync_job_id: UUID,
        *,
        now: datetime,
    ) -> CRMSyncJob | None:
        statement = (
            update(CRMSyncJobModel)
            .where(CRMSyncJobModel.workspace_id == workspace_id)
            .where(CRMSyncJobModel.sync_job_id == sync_job_id)
            .where(CRMSyncJobModel.status == CRMSyncJobStatus.PENDING.value)
            .values(
                status=CRMSyncJobStatus.RUNNING.value,
                started_at=now,
                last_heartbeat_at=now,
                updated_at=now,
                failure_reason=None,
            )
            .returning(CRMSyncJobModel)
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        return _model_to_sync_job(model) if model is not None else None

    async def fail_stale_active_jobs(
        self,
        *,
        now: datetime,
        pending_timeout_seconds: int,
        running_timeout_seconds: int,
    ) -> int:
        pending_cutoff = now - timedelta(seconds=pending_timeout_seconds)
        running_cutoff = now - timedelta(seconds=running_timeout_seconds)
        statement = (
            update(CRMSyncJobModel)
            .where(
                (
                    (CRMSyncJobModel.status == CRMSyncJobStatus.PENDING.value)
                    & (CRMSyncJobModel.created_at < pending_cutoff)
                )
                | (
                    (CRMSyncJobModel.status == CRMSyncJobStatus.RUNNING.value)
                    & (func.coalesce(
                        CRMSyncJobModel.last_heartbeat_at,
                        CRMSyncJobModel.started_at,
                    ) < running_cutoff)
                )
            )
            .values(
                status=CRMSyncJobStatus.FAILED.value,
                finished_at=now,
                failure_reason="stale active CRM sync job recovered automatically",
                updated_at=now,
            )
        )
        result = cast(CursorResult[tuple[object]], await self._session.execute(statement))
        return result.rowcount or 0

    async def touch_running_heartbeat(
        self,
        workspace_id: WorkspaceId,
        sync_job_id: UUID,
        *,
        now: datetime,
    ) -> CRMSyncJob | None:
        statement = (
            update(CRMSyncJobModel)
            .where(CRMSyncJobModel.workspace_id == workspace_id)
            .where(CRMSyncJobModel.sync_job_id == sync_job_id)
            .where(CRMSyncJobModel.status == CRMSyncJobStatus.RUNNING.value)
            .values(last_heartbeat_at=now, updated_at=now)
            .returning(CRMSyncJobModel)
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        return _model_to_sync_job(model) if model is not None else None

    async def save_if_running(self, job: CRMSyncJob) -> CRMSyncJob | None:
        values = {
            key: value
            for key, value in _sync_job_to_values(job).items()
            if key != "sync_job_id"
        }
        statement = (
            update(CRMSyncJobModel)
            .where(CRMSyncJobModel.workspace_id == job.workspace_id)
            .where(CRMSyncJobModel.sync_job_id == job.sync_job_id)
            .where(CRMSyncJobModel.status == CRMSyncJobStatus.RUNNING.value)
            .values(**values)
            .returning(CRMSyncJobModel)
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        return _model_to_sync_job(model) if model is not None else None

    async def save(self, job: CRMSyncJob) -> CRMSyncJob:
        values = _sync_job_to_values(job)
        update_values = {key: value for key, value in values.items() if key != "sync_job_id"}
        statement = (
            insert(CRMSyncJobModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["sync_job_id"],
                set_=update_values,
            )
            .returning(CRMSyncJobModel)
        )
        result = await self._session.execute(statement)
        return _model_to_sync_job(result.scalar_one())


class PostgresExternalEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_provider_event_id(
        self,
        workspace_id: WorkspaceId,
        provider: str,
        provider_event_id: str,
    ) -> ExternalEvent | None:
        statement = (
            select(ExternalEventModel)
            .where(ExternalEventModel.workspace_id == workspace_id)
            .where(ExternalEventModel.provider == provider)
            .where(ExternalEventModel.provider_event_id == provider_event_id)
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        return _model_to_external_event(model) if model is not None else None

    async def save(self, event: ExternalEvent) -> ExternalEvent:
        values = _external_event_to_values(event)
        update_values = {
            key: value
            for key, value in values.items()
            if key not in ("external_event_id", "workspace_id", "provider", "provider_event_id")
        }
        statement = (
            insert(ExternalEventModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["workspace_id", "provider", "provider_event_id"],
                set_=update_values,
            )
            .returning(ExternalEventModel)
        )
        result = await self._session.execute(statement)
        return _model_to_external_event(result.scalar_one())


class PostgresCRMSyncWindowStateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_workspace_provider(
        self,
        workspace_id: WorkspaceId,
        crm_provider: str,
    ) -> CRMSyncWindowState | None:
        statement = (
            select(CRMSyncWindowStateModel)
            .where(CRMSyncWindowStateModel.workspace_id == workspace_id)
            .where(CRMSyncWindowStateModel.crm_provider == crm_provider)
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        return _model_to_window_state(model) if model is not None else None

    async def save(self, state: CRMSyncWindowState) -> CRMSyncWindowState:
        values = _window_state_to_values(state)
        update_values = {
            key: value
            for key, value in values.items()
            if key not in ("workspace_id", "crm_provider", "created_at")
        }
        statement = (
            insert(CRMSyncWindowStateModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["workspace_id", "crm_provider"],
                set_=update_values,
            )
            .returning(CRMSyncWindowStateModel)
        )
        result = await self._session.execute(statement)
        return _model_to_window_state(result.scalar_one())

    async def delete(self, workspace_id: WorkspaceId, crm_provider: str) -> None:
        statement = delete(CRMSyncWindowStateModel).where(
            CRMSyncWindowStateModel.workspace_id == workspace_id,
            CRMSyncWindowStateModel.crm_provider == crm_provider,
        )
        await self._session.execute(statement)


def _sync_job_to_values(job: CRMSyncJob) -> dict[str, object]:
    return {
        "sync_job_id": job.sync_job_id,
        "workspace_id": job.workspace_id,
        "crm_provider": job.crm_provider,
        "sync_type": job.sync_type.value,
        "status": job.status.value,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "cursor_started_at": job.cursor_started_at,
        "cursor_finished_at": job.cursor_finished_at,
        "total_seen": job.total_seen,
        "total_upserted": job.total_upserted,
        "total_failed": job.total_failed,
        "failure_reason": job.failure_reason,
        "last_heartbeat_at": job.last_heartbeat_at,
        "created_by_user_id": job.created_by_user_id,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


_ACTIVE_SYNC_JOB_STATUSES = (
    CRMSyncJobStatus.PENDING.value,
    CRMSyncJobStatus.RUNNING.value,
)


def _workspace_provider_jobs_statement(
    workspace_id: WorkspaceId,
    crm_provider: str,
) -> Select[tuple[CRMSyncJobModel]]:
    return (
        select(CRMSyncJobModel)
        .where(CRMSyncJobModel.workspace_id == workspace_id)
        .where(CRMSyncJobModel.crm_provider == crm_provider)
        .order_by(CRMSyncJobModel.created_at.desc())
    )


def _model_to_sync_job(model: CRMSyncJobModel) -> CRMSyncJob:
    return CRMSyncJob(
        sync_job_id=model.sync_job_id,
        workspace_id=model.workspace_id,
        crm_provider=model.crm_provider,
        sync_type=CRMSyncType(model.sync_type),
        status=CRMSyncJobStatus(model.status),
        started_at=model.started_at,
        finished_at=model.finished_at,
        cursor_started_at=model.cursor_started_at,
        cursor_finished_at=model.cursor_finished_at,
        total_seen=model.total_seen,
        total_upserted=model.total_upserted,
        total_failed=model.total_failed,
        failure_reason=model.failure_reason,
        last_heartbeat_at=model.last_heartbeat_at,
        created_by_user_id=model.created_by_user_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _window_state_to_values(state: CRMSyncWindowState) -> dict[str, object]:
    return {
        "workspace_id": state.workspace_id,
        "crm_provider": state.crm_provider,
        "sync_type": state.sync_type.value,
        "updated_after": state.updated_after,
        "updated_before": state.updated_before,
        "next_cursor": state.next_cursor,
        "sort_by": state.sort_by.value if state.sort_by is not None else None,
        "created_at": state.created_at,
        "updated_at": state.updated_at,
    }


def _model_to_window_state(model: CRMSyncWindowStateModel) -> CRMSyncWindowState:
    return CRMSyncWindowState(
        workspace_id=model.workspace_id,
        crm_provider=model.crm_provider,
        sync_type=CRMSyncType(model.sync_type),
        updated_after=model.updated_after,
        updated_before=model.updated_before,
        next_cursor=model.next_cursor,
        sort_by=CRMSyncLeadSort(model.sort_by) if model.sort_by is not None else None,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _external_event_to_values(event: ExternalEvent) -> dict[str, object]:
    return {
        "external_event_id": event.external_event_id,
        "workspace_id": event.workspace_id,
        "provider": event.provider,
        "event_type": event.event_type,
        "provider_event_id": event.provider_event_id,
        "crm_lead_id": event.crm_lead_id,
        "lead_id": event.lead_id,
        "received_at": event.received_at,
        "processed_at": event.processed_at,
        "status": event.status.value,
        "payload_redacted": event.payload_redacted,
        "failure_reason": event.failure_reason,
        "created_at": event.created_at,
        "updated_at": event.updated_at,
    }


def _model_to_external_event(model: ExternalEventModel) -> ExternalEvent:
    return ExternalEvent(
        external_event_id=model.external_event_id,
        workspace_id=model.workspace_id,
        provider=model.provider,
        event_type=model.event_type,
        provider_event_id=model.provider_event_id,
        crm_lead_id=model.crm_lead_id,
        lead_id=model.lead_id,
        received_at=model.received_at,
        processed_at=model.processed_at,
        status=ExternalEventStatus(model.status),
        payload_redacted=model.payload_redacted,
        failure_reason=model.failure_reason,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
