from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.ports.reporting import ReportingRepository
from app.domain.campaigns.admin import CampaignAdminAuditAction
from app.domain.campaigns.paused_search_occurrences import RecurringOccurrenceStatus
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.crm_sync import CRMSyncJobStatus, ExternalEventStatus
from app.domain.events import OutboxEventStatus
from app.domain.reporting import (
    CampaignAuditLogEntry,
    CampaignOperationsSummary,
    EnrollmentStatusCounts,
    HandoffStatusCounts,
    MessageStatusCounts,
    PausedSearchOccurrenceHealth,
    WorkflowStateCounts,
    WorkspaceOperationsSummary,
)
from app.infrastructure.persistence.postgres.models import (
    CampaignAdminAuditLogModel,
    CampaignModel,
    CRMSyncJobModel,
    ExternalEventModel,
    HandoffModel,
    OutboundMessageModel,
    OutboxEventModel,
    RecurringOccurrenceModel,
)
from app.infrastructure.persistence.postgres.workflow_models import (
    CampaignEnrollmentModel,
    LeadWorkflowModel,
)

_WORKFLOW_STATES = tuple(field for field in WorkflowStateCounts.__dataclass_fields__)
_ENROLLMENT_STATES = tuple(field for field in EnrollmentStatusCounts.__dataclass_fields__)
_MESSAGE_STATES = tuple(field for field in MessageStatusCounts.__dataclass_fields__)
_HANDOFF_STATES = tuple(field for field in HandoffStatusCounts.__dataclass_fields__)
_DELIVERY_ISSUE_STATUSES = frozenset({"failed", "undelivered", "bounced", "dropped"})
type _FilterClause = ColumnElement[bool]


class PostgresReportingRepository(ReportingRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_workspace_operations_summary(
        self,
        workspace_id: UUID,
    ) -> WorkspaceOperationsSummary:
        campaign_counts = await self._counts_by_status(
            CampaignModel.status,
            (CampaignModel.workspace_id == workspace_id,),
        )
        workflow_counts = await self._workflow_counts(
            (LeadWorkflowModel.workspace_id == workspace_id,)
        )
        message_counts = await self._message_counts(
            (OutboundMessageModel.workspace_id == workspace_id,)
        )
        handoff_counts = await self._handoff_counts((HandoffModel.workspace_id == workspace_id,))
        occurrence_health = await self._paused_search_occurrence_health(workspace_id)
        last_successful_sync_at = await self._session.scalar(
            select(func.max(CRMSyncJobModel.finished_at)).where(
                CRMSyncJobModel.workspace_id == workspace_id,
                CRMSyncJobModel.status == CRMSyncJobStatus.COMPLETED.value,
            )
        )
        return WorkspaceOperationsSummary(
            workspace_id=workspace_id,
            active_campaigns=campaign_counts.get(CampaignStatus.ACTIVE.value, 0),
            paused_campaigns=campaign_counts.get(CampaignStatus.PAUSED.value, 0),
            last_successful_sync_at=last_successful_sync_at,
            workflow_counts=workflow_counts,
            message_counts=message_counts,
            handoff_counts=handoff_counts,
            paused_search_occurrence_health=occurrence_health,
            pending_external_events=await self._count_rows(
                ExternalEventModel,
                (
                    ExternalEventModel.workspace_id == workspace_id,
                    ExternalEventModel.status == ExternalEventStatus.PENDING.value,
                ),
            ),
            failed_external_events=await self._count_rows(
                ExternalEventModel,
                (
                    ExternalEventModel.workspace_id == workspace_id,
                    ExternalEventModel.status == ExternalEventStatus.FAILED.value,
                ),
            ),
            pending_outbox_events=await self._count_rows(
                OutboxEventModel,
                (
                    OutboxEventModel.workspace_id == workspace_id,
                    OutboxEventModel.status.in_(
                        (OutboxEventStatus.PENDING.value, OutboxEventStatus.PUBLISHING.value)
                    ),
                ),
            ),
            failed_outbox_events=await self._count_rows(
                OutboxEventModel,
                (
                    OutboxEventModel.workspace_id == workspace_id,
                    OutboxEventModel.status == OutboxEventStatus.FAILED.value,
                ),
            ),
        )

    async def get_campaign_operations_summary(
        self,
        workspace_id: UUID,
        campaign_id: UUID,
    ) -> CampaignOperationsSummary | None:
        campaign = await self._session.scalar(
            select(CampaignModel).where(
                CampaignModel.workspace_id == workspace_id,
                CampaignModel.campaign_id == campaign_id,
            )
        )
        if campaign is None:
            return None

        latest_audit_at = await self._session.scalar(
            select(func.max(CampaignAdminAuditLogModel.created_at)).where(
                CampaignAdminAuditLogModel.workspace_id == workspace_id,
                CampaignAdminAuditLogModel.campaign_id == campaign_id,
            )
        )
        return CampaignOperationsSummary(
            workspace_id=workspace_id,
            campaign_id=campaign.campaign_id,
            campaign_name=campaign.name,
            campaign_status=CampaignStatus(campaign.status),
            active_version_id=campaign.active_version_id,
            latest_audit_at=latest_audit_at,
            enrollment_counts=await self._enrollment_counts(
                (
                    CampaignEnrollmentModel.workspace_id == workspace_id,
                    CampaignEnrollmentModel.campaign_id == campaign_id,
                )
            ),
            workflow_counts=await self._workflow_counts(
                (
                    LeadWorkflowModel.workspace_id == workspace_id,
                    LeadWorkflowModel.campaign_id == campaign_id,
                )
            ),
            message_counts=await self._message_counts(
                (
                    OutboundMessageModel.workspace_id == workspace_id,
                    OutboundMessageModel.campaign_id == campaign_id,
                )
            ),
            handoff_counts=await self._handoff_counts(
                (
                    HandoffModel.workspace_id == workspace_id,
                    HandoffModel.campaign_id == campaign_id,
                )
            ),
        )

    async def list_campaign_audit_logs(
        self,
        workspace_id: UUID,
        campaign_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[CampaignAuditLogEntry, ...]:
        result = await self._session.execute(
            select(CampaignAdminAuditLogModel)
            .where(
                CampaignAdminAuditLogModel.workspace_id == workspace_id,
                CampaignAdminAuditLogModel.campaign_id == campaign_id,
            )
            .order_by(CampaignAdminAuditLogModel.created_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return tuple(
            CampaignAuditLogEntry(
                audit_log_id=row.audit_log_id,
                workspace_id=row.workspace_id,
                campaign_id=row.campaign_id,
                campaign_version_id=row.campaign_version_id,
                action=CampaignAdminAuditAction(row.action),
                actor_user_id=row.actor_user_id,
                details=dict(row.details),
                created_at=row.created_at,
            )
            for row in rows
        )

    async def _count_rows(self, model: Any, filters: Sequence[_FilterClause]) -> int:
        value = await self._session.scalar(
            select(func.count()).select_from(model).where(and_(*filters))
        )
        return int(value or 0)

    async def _counts_by_status(
        self,
        column: Any,
        filters: Sequence[_FilterClause],
    ) -> dict[str, int]:
        result = await self._session.execute(
            select(column, func.count()).where(and_(*filters)).group_by(column)
        )
        return {str(status): int(count) for status, count in result.all() if status is not None}

    async def _workflow_counts(self, filters: Sequence[_FilterClause]) -> WorkflowStateCounts:
        counts = await self._counts_by_status(LeadWorkflowModel.state, filters)
        return WorkflowStateCounts(**{state: counts.get(state, 0) for state in _WORKFLOW_STATES})

    async def _enrollment_counts(self, filters: Sequence[_FilterClause]) -> EnrollmentStatusCounts:
        counts = await self._counts_by_status(CampaignEnrollmentModel.status, filters)
        return EnrollmentStatusCounts(
            **{state: counts.get(state, 0) for state in _ENROLLMENT_STATES}
        )

    async def _handoff_counts(self, filters: Sequence[_FilterClause]) -> HandoffStatusCounts:
        counts = await self._counts_by_status(HandoffModel.status, filters)
        return HandoffStatusCounts(**{state: counts.get(state, 0) for state in _HANDOFF_STATES})

    async def _message_counts(self, filters: Sequence[_FilterClause]) -> MessageStatusCounts:
        status_counts = await self._counts_by_status(OutboundMessageModel.status, filters)
        delivery_counts = await self._counts_by_status(
            OutboundMessageModel.provider_delivery_status,
            filters,
        )
        base_counts = {
            state: status_counts.get(state, 0)
            for state in _MESSAGE_STATES
            if state not in {"delivered", "delivery_issues"}
        }
        return MessageStatusCounts(
            **base_counts,
            delivered=delivery_counts.get("delivered", 0),
            delivery_issues=sum(
                delivery_counts.get(status, 0) for status in _DELIVERY_ISSUE_STATUSES
            ),
        )

    async def _paused_search_occurrence_health(
        self,
        workspace_id: UUID,
    ) -> PausedSearchOccurrenceHealth:
        filters = (RecurringOccurrenceModel.workspace_id == workspace_id,)
        counts = await self._counts_by_status(RecurringOccurrenceModel.status, filters)
        return PausedSearchOccurrenceHealth(
            due=await self._count_rows(
                RecurringOccurrenceModel,
                filters
                + (
                    RecurringOccurrenceModel.status.in_(
                        (
                            RecurringOccurrenceStatus.PLANNED.value,
                            RecurringOccurrenceStatus.APPROVED.value,
                        )
                    ),
                    RecurringOccurrenceModel.due_at <= func.now(),
                ),
            ),
            held=counts.get(RecurringOccurrenceStatus.DEFERRED.value, 0),
            review_pending=counts.get(RecurringOccurrenceStatus.REVIEW_REQUESTED.value, 0),
            expired=counts.get(RecurringOccurrenceStatus.EXPIRED.value, 0),
            failed=counts.get(RecurringOccurrenceStatus.FAILED.value, 0),
            uncertain=counts.get(RecurringOccurrenceStatus.UNCERTAIN.value, 0),
            terminal=sum(
                counts.get(status.value, 0)
                for status in (
                    RecurringOccurrenceStatus.SENT,
                    RecurringOccurrenceStatus.SKIPPED,
                    RecurringOccurrenceStatus.CANCELLED,
                    RecurringOccurrenceStatus.MIGRATED_LEGACY,
                )
            ),
            fallback=await self._count_rows(
                RecurringOccurrenceModel,
                filters + (RecurringOccurrenceModel.fallback_used.is_(True),),
            ),
        )
