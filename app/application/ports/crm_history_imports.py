from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.crm_history_imports import (
    CrmHistoryImportJob,
    StagedCrmHistoryImportEvent,
)


class CrmHistoryImportJobRepository(Protocol):
    async def get_by_id(
        self, workspace_id: UUID, import_job_id: UUID
    ) -> CrmHistoryImportJob | None:
        raise NotImplementedError

    async def get_for_update(
        self, workspace_id: UUID, import_job_id: UUID
    ) -> CrmHistoryImportJob | None:
        raise NotImplementedError

    async def get_active_for_lead(
        self, workspace_id: UUID, lead_id: UUID
    ) -> CrmHistoryImportJob | None:
        raise NotImplementedError

    async def get_by_batch_fingerprint(
        self, workspace_id: UUID, lead_id: UUID, batch_fingerprint: str
    ) -> CrmHistoryImportJob | None:
        raise NotImplementedError

    async def create(self, job: CrmHistoryImportJob) -> CrmHistoryImportJob | None:
        """Create a job, returning None if the active-job guard conflicts."""
        raise NotImplementedError

    async def save(self, job: CrmHistoryImportJob) -> CrmHistoryImportJob:
        raise NotImplementedError

    async def claim_ready(self, *, now: datetime, limit: int) -> tuple[CrmHistoryImportJob, ...]:
        raise NotImplementedError


class CrmHistoryImportEventRepository(Protocol):
    async def insert_received(
        self, events: tuple[StagedCrmHistoryImportEvent, ...]
    ) -> tuple[StagedCrmHistoryImportEvent, ...]:
        """Insert non-conflicting events and return only inserted records."""
        raise NotImplementedError

    async def list_received(
        self, workspace_id: UUID, import_job_id: UUID
    ) -> tuple[StagedCrmHistoryImportEvent, ...]:
        raise NotImplementedError

    async def save(
        self, event: StagedCrmHistoryImportEvent
    ) -> StagedCrmHistoryImportEvent:
        raise NotImplementedError