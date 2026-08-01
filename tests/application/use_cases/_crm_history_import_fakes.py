from dataclasses import replace
from datetime import datetime
from uuid import UUID

from app.domain.conversations import CrmConversationEvent
from app.domain.crm_history_imports import (
    CrmHistoryImportEventStatus,
    CrmHistoryImportJob,
    CrmHistoryImportJobStatus,
    StagedCrmHistoryImportEvent,
)
from app.domain.identity import AuthAuditLog
from app.domain.leads import CanonicalLeadRecord, CRMProvider


class FakeCrmHistoryImportJobRepository:
    def __init__(self) -> None:
        self.jobs: dict[tuple[UUID, UUID], CrmHistoryImportJob] = {}

    async def get_by_id(
        self, workspace_id: UUID, import_job_id: UUID
    ) -> CrmHistoryImportJob | None:
        return self.jobs.get((workspace_id, import_job_id))

    async def get_for_update(
        self, workspace_id: UUID, import_job_id: UUID
    ) -> CrmHistoryImportJob | None:
        return await self.get_by_id(workspace_id, import_job_id)

    async def get_active_for_lead(
        self, workspace_id: UUID, lead_id: UUID
    ) -> CrmHistoryImportJob | None:
        active = {
            CrmHistoryImportJobStatus.PENDING,
            CrmHistoryImportJobStatus.RECEIVING,
            CrmHistoryImportJobStatus.READY,
            CrmHistoryImportJobStatus.RUNNING,
        }
        return next(
            (
                job
                for job in self.jobs.values()
                if job.workspace_id == workspace_id
                and job.lead_id == lead_id
                and job.status in active
            ),
            None,
        )

    async def create(self, job: CrmHistoryImportJob) -> CrmHistoryImportJob | None:
        if await self.get_active_for_lead(job.workspace_id, job.lead_id) is not None:
            return None
        self.jobs[(job.workspace_id, job.import_job_id)] = job
        return job

    async def save(self, job: CrmHistoryImportJob) -> CrmHistoryImportJob:
        self.jobs[(job.workspace_id, job.import_job_id)] = job
        return job

    async def claim_ready(
        self, *, now: datetime, limit: int
    ) -> tuple[CrmHistoryImportJob, ...]:
        ready = sorted(
            (job for job in self.jobs.values() if job.status is CrmHistoryImportJobStatus.READY),
            key=lambda job: job.created_at,
        )[:limit]
        claimed = tuple(
            replace(
                job,
                status=CrmHistoryImportJobStatus.RUNNING,
                started_at=now,
                updated_at=now,
            )
            for job in ready
        )
        for job in claimed:
            self.jobs[(job.workspace_id, job.import_job_id)] = job
        return claimed


class FakeCrmHistoryImportEventRepository:
    def __init__(self) -> None:
        self.events: dict[tuple[UUID, UUID, str], StagedCrmHistoryImportEvent] = {}

    async def insert_received(
        self, events: tuple[StagedCrmHistoryImportEvent, ...]
    ) -> tuple[StagedCrmHistoryImportEvent, ...]:
        inserted: list[StagedCrmHistoryImportEvent] = []
        for event in events:
            key = (event.workspace_id, event.import_job_id, event.fingerprint)
            if key in self.events:
                continue
            self.events[key] = event
            inserted.append(event)
        return tuple(inserted)

    async def list_received(
        self, workspace_id: UUID, import_job_id: UUID
    ) -> tuple[StagedCrmHistoryImportEvent, ...]:
        return tuple(
            event
            for event in self.events.values()
            if event.workspace_id == workspace_id
            and event.import_job_id == import_job_id
            and event.status is CrmHistoryImportEventStatus.RECEIVED
        )

    async def save(
        self, event: StagedCrmHistoryImportEvent
    ) -> StagedCrmHistoryImportEvent:
        self.events[(event.workspace_id, event.import_job_id, event.fingerprint)] = event
        return event


class FakeLeadRepository:
    def __init__(self, leads: tuple[CanonicalLeadRecord, ...]) -> None:
        self.leads = {(lead.workspace_id, lead.lead_id): lead for lead in leads}

    async def get_by_id(
        self, workspace_id: UUID, lead_id: UUID
    ) -> CanonicalLeadRecord | None:
        return self.leads.get((workspace_id, lead_id))

    async def get_by_crm_id(
        self, workspace_id: UUID, crm_provider: CRMProvider, crm_lead_id: str
    ) -> CanonicalLeadRecord | None:
        return next(
            (
                lead
                for lead in self.leads.values()
                if lead.workspace_id == workspace_id
                and lead.crm_provider is crm_provider
                and lead.crm_lead_id == crm_lead_id
            ),
            None,
        )


class FakeCrmConversationEventRepository:
    def __init__(self) -> None:
        self.events: dict[tuple[UUID, str, str], CrmConversationEvent] = {}

    async def save(self, event: CrmConversationEvent) -> CrmConversationEvent:
        self.events[(event.workspace_id, event.crm_provider, event.crm_activity_id)] = event
        return event


class FakeAuthAuditLogRepository:
    def __init__(self) -> None:
        self.logs: list[AuthAuditLog] = []

    async def append(self, audit_log: AuthAuditLog) -> AuthAuditLog:
        self.logs.append(audit_log)
        return audit_log