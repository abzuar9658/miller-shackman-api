from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.application.ports.reporting import ReportingRepository
from app.domain.identity import AuthenticatedActor
from app.domain.identity.permissions import (
    PermissionCapability,
    PermissionReasonCode,
    evaluate_permission,
)
from app.domain.reporting import (
    CampaignAuditLogEntry,
    CampaignOperationsSummary,
    WorkspaceOperationsSummary,
)


class ReportingReadStatus(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


class ReportingReadReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    CAMPAIGN_NOT_FOUND = "campaign_not_found"


@dataclass(frozen=True)
class WorkspaceOperationsReportResult:
    status: ReportingReadStatus
    report: WorkspaceOperationsSummary | None = None
    reasons: tuple[ReportingReadReasonCode, ...] = ()
    permission_reasons: tuple[PermissionReasonCode, ...] = ()


@dataclass(frozen=True)
class CampaignOperationsReportResult:
    status: ReportingReadStatus
    report: CampaignOperationsSummary | None = None
    reasons: tuple[ReportingReadReasonCode, ...] = ()
    permission_reasons: tuple[PermissionReasonCode, ...] = ()


@dataclass(frozen=True)
class CampaignAuditLogListResult:
    status: ReportingReadStatus
    entries: tuple[CampaignAuditLogEntry, ...] = ()
    reasons: tuple[ReportingReadReasonCode, ...] = ()
    permission_reasons: tuple[PermissionReasonCode, ...] = ()


async def get_workspace_operations_report(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    reporting_repository: ReportingRepository,
) -> WorkspaceOperationsReportResult:
    decision = evaluate_permission(actor, PermissionCapability.VIEW_WORKSPACE_REPORTING)
    if not decision.allowed:
        return WorkspaceOperationsReportResult(
            status=ReportingReadStatus.REJECTED,
            reasons=(ReportingReadReasonCode.PERMISSION_DENIED,),
            permission_reasons=decision.reasons,
        )

    return WorkspaceOperationsReportResult(
        status=ReportingReadStatus.OK,
        report=await reporting_repository.get_workspace_operations_summary(workspace_id),
    )


async def get_campaign_operations_report(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    campaign_id: UUID,
    reporting_repository: ReportingRepository,
) -> CampaignOperationsReportResult:
    decision = evaluate_permission(actor, PermissionCapability.VIEW_WORKSPACE_REPORTING)
    if not decision.allowed:
        return CampaignOperationsReportResult(
            status=ReportingReadStatus.REJECTED,
            reasons=(ReportingReadReasonCode.PERMISSION_DENIED,),
            permission_reasons=decision.reasons,
        )

    report = await reporting_repository.get_campaign_operations_summary(workspace_id, campaign_id)
    if report is None:
        return CampaignOperationsReportResult(
            status=ReportingReadStatus.NOT_FOUND,
            reasons=(ReportingReadReasonCode.CAMPAIGN_NOT_FOUND,),
        )

    return CampaignOperationsReportResult(status=ReportingReadStatus.OK, report=report)


async def list_campaign_audit_logs(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    campaign_id: UUID,
    reporting_repository: ReportingRepository,
    limit: int = 100,
) -> CampaignAuditLogListResult:
    decision = evaluate_permission(actor, PermissionCapability.VIEW_WORKSPACE_REPORTING)
    if not decision.allowed:
        return CampaignAuditLogListResult(
            status=ReportingReadStatus.REJECTED,
            reasons=(ReportingReadReasonCode.PERMISSION_DENIED,),
            permission_reasons=decision.reasons,
        )

    report = await reporting_repository.get_campaign_operations_summary(workspace_id, campaign_id)
    if report is None:
        return CampaignAuditLogListResult(
            status=ReportingReadStatus.NOT_FOUND,
            reasons=(ReportingReadReasonCode.CAMPAIGN_NOT_FOUND,),
        )

    return CampaignAuditLogListResult(
        status=ReportingReadStatus.OK,
        entries=await reporting_repository.list_campaign_audit_logs(
            workspace_id,
            campaign_id,
            limit=limit,
        ),
    )
