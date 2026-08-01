from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.use_cases.reporting import (
    ReportingReadStatus,
    get_campaign_operations_report,
    get_workspace_operations_report,
    list_campaign_audit_logs,
)
from app.domain.identity import AuthenticatedActor
from app.domain.reporting import (
    CampaignOperationsSummary,
    EnrollmentStatusCounts,
    HandoffStatusCounts,
    MessageStatusCounts,
    PausedSearchOccurrenceHealth,
    WorkflowStateCounts,
    WorkspaceOperationsSummary,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.dependencies.reporting import (
    ReportingServiceBundle,
    get_reporting_service_bundle,
)
from app.interfaces.api.schemas.reporting import (
    CampaignAuditLogEntryResponse,
    CampaignAuditLogListResponse,
    CampaignOperationsReportResponse,
    CampaignOperationsSummaryResponse,
    EnrollmentStatusCountsResponse,
    HandoffStatusCountsResponse,
    MessageStatusCountsResponse,
    PausedSearchOccurrenceHealthResponse,
    WorkflowStateCountsResponse,
    WorkspaceOperationsReportResponse,
    WorkspaceOperationsSummaryResponse,
)

router = APIRouter(tags=["reporting"])


@router.get(
    "/{workspace_id}/reporting/operations",
    response_model=WorkspaceOperationsReportResponse,
)
async def read_workspace_operations_report(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[ReportingServiceBundle, Depends(get_reporting_service_bundle)],
) -> WorkspaceOperationsReportResponse:
    result = await get_workspace_operations_report(
        actor=actor,
        workspace_id=workspace_id,
        reporting_repository=bundle.reporting_repository,
    )
    if result.status == ReportingReadStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in result.reasons],
        )
    assert result.report is not None
    return WorkspaceOperationsReportResponse(
        status=result.status.value, report=_workspace_report_response(result.report)
    )


@router.get(
    "/{workspace_id}/reporting/campaigns/{campaign_id}",
    response_model=CampaignOperationsReportResponse,
)
async def read_campaign_operations_report(
    workspace_id: UUID,
    campaign_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[ReportingServiceBundle, Depends(get_reporting_service_bundle)],
) -> CampaignOperationsReportResponse:
    result = await get_campaign_operations_report(
        actor=actor,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        reporting_repository=bundle.reporting_repository,
    )
    if result.status == ReportingReadStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in result.reasons],
        )
    if result.status == ReportingReadStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    assert result.report is not None
    return CampaignOperationsReportResponse(
        status=result.status.value, report=_campaign_report_response(result.report)
    )


@router.get(
    "/{workspace_id}/reporting/campaigns/{campaign_id}/audit-logs",
    response_model=CampaignAuditLogListResponse,
)
async def read_campaign_audit_logs(
    workspace_id: UUID,
    campaign_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[ReportingServiceBundle, Depends(get_reporting_service_bundle)],
    limit: int = Query(default=50, ge=1, le=200),
) -> CampaignAuditLogListResponse:
    result = await list_campaign_audit_logs(
        actor=actor,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        reporting_repository=bundle.reporting_repository,
        limit=limit,
    )
    if result.status == ReportingReadStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in result.reasons],
        )
    if result.status == ReportingReadStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    return CampaignAuditLogListResponse(
        status=result.status.value,
        entries=[
            CampaignAuditLogEntryResponse(
                audit_log_id=entry.audit_log_id,
                workspace_id=entry.workspace_id,
                campaign_id=entry.campaign_id,
                campaign_version_id=entry.campaign_version_id,
                action=entry.action.value,
                actor_user_id=entry.actor_user_id,
                details=entry.details,
                created_at=entry.created_at,
            )
            for entry in result.entries
        ],
    )


def _workflow_counts_response(counts: WorkflowStateCounts) -> WorkflowStateCountsResponse:
    return WorkflowStateCountsResponse.model_validate(counts.__dict__)


def _message_counts_response(counts: MessageStatusCounts) -> MessageStatusCountsResponse:
    return MessageStatusCountsResponse.model_validate(counts.__dict__)


def _handoff_counts_response(counts: HandoffStatusCounts) -> HandoffStatusCountsResponse:
    return HandoffStatusCountsResponse.model_validate(counts.__dict__)


def _paused_search_occurrence_health_response(
    health: PausedSearchOccurrenceHealth,
) -> PausedSearchOccurrenceHealthResponse:
    return PausedSearchOccurrenceHealthResponse.model_validate(health.__dict__)


def _enrollment_counts_response(counts: EnrollmentStatusCounts) -> EnrollmentStatusCountsResponse:
    return EnrollmentStatusCountsResponse.model_validate(counts.__dict__)


def _workspace_report_response(
    report: WorkspaceOperationsSummary,
) -> WorkspaceOperationsSummaryResponse:
    return WorkspaceOperationsSummaryResponse(
        workspace_id=report.workspace_id,
        active_campaigns=report.active_campaigns,
        paused_campaigns=report.paused_campaigns,
        last_successful_sync_at=report.last_successful_sync_at,
        workflow_counts=_workflow_counts_response(report.workflow_counts),
        message_counts=_message_counts_response(report.message_counts),
        handoff_counts=_handoff_counts_response(report.handoff_counts),
        paused_search_occurrence_health=_paused_search_occurrence_health_response(
            report.paused_search_occurrence_health
        ),
        pending_external_events=report.pending_external_events,
        failed_external_events=report.failed_external_events,
        pending_outbox_events=report.pending_outbox_events,
        failed_outbox_events=report.failed_outbox_events,
    )


def _campaign_report_response(
    report: CampaignOperationsSummary,
) -> CampaignOperationsSummaryResponse:
    return CampaignOperationsSummaryResponse(
        workspace_id=report.workspace_id,
        campaign_id=report.campaign_id,
        campaign_name=report.campaign_name,
        campaign_status=report.campaign_status.value,
        active_version_id=report.active_version_id,
        latest_audit_at=report.latest_audit_at,
        enrollment_counts=_enrollment_counts_response(report.enrollment_counts),
        workflow_counts=_workflow_counts_response(report.workflow_counts),
        message_counts=_message_counts_response(report.message_counts),
        handoff_counts=_handoff_counts_response(report.handoff_counts),
    )
