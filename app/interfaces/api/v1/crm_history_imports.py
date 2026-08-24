from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.application.services.crm_lead_refresh import (
    CrmLeadRefreshStatus,
    refresh_lead_from_crm,
)
from app.application.use_cases.crm_history_imports import (
    CrmHistoryImportMutationStatus,
    CrmHistoryImportReadStatus,
    CrmHistoryImportReasonCode,
    complete_crm_history_import_upload,
    create_crm_history_import,
    create_extension_crm_history_import,
    crm_history_export_batch_fingerprint,
    evaluate_crm_history_import_capability,
    ingest_crm_history_events,
    read_crm_history_import,
)
from app.domain.crm_history_imports import (
    CrmHistoryImportEventPayload,
    CrmHistoryImportJob,
)
from app.domain.identity import AuthenticatedActor, AuthenticatedExtensionDevice
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.infrastructure.crm.follow_up_boss.history_import_parser import (
    parse_fub_people_response,
)
from app.interfaces.api.dependencies.crm_history_imports import (
    CrmHistoryImportBundle,
    get_crm_history_import_bundle,
)
from app.interfaces.api.dependencies.extension_devices import get_extension_device_actor
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.schemas.crm_history_imports import (
    CreateCrmHistoryImportRequest,
    CreateCrmHistoryImportResponse,
    CrmHistoryImportCapabilityResponse,
    CrmHistoryImportEventRequest,
    CrmHistoryImportJobResponse,
    CrmHistoryImportReadResponse,
    ExtensionExportCrmHistoryRequest,
    IngestCrmHistoryEventsRequest,
    IngestCrmHistoryEventsResponse,
)

router = APIRouter(tags=["crm-history-imports"])
_TOKEN_HEADER = Header(alias="X-CRM-History-Import-Token", min_length=1)
logger = structlog.get_logger(__name__)


@router.post(
    "/{workspace_id}/crm-history-imports/export",
    response_model=CreateCrmHistoryImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def export_crm_history_route(
    workspace_id: UUID,
    request: ExtensionExportCrmHistoryRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CrmHistoryImportBundle, Depends(get_crm_history_import_bundle)],
) -> CreateCrmHistoryImportResponse:
    response = await _export_crm_history(
        workspace_id=workspace_id,
        request=request,
        actor=actor,
        bundle=bundle,
        extension_device=None,
    )
    await bundle.session.commit()
    return response


@router.post(
    "/{workspace_id}/crm-history-imports/extension-export",
    response_model=CreateCrmHistoryImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def extension_device_export_crm_history_route(
    workspace_id: UUID,
    request: ExtensionExportCrmHistoryRequest,
    extension_device: Annotated[
        AuthenticatedExtensionDevice, Depends(get_extension_device_actor)
    ],
    bundle: Annotated[CrmHistoryImportBundle, Depends(get_crm_history_import_bundle)],
) -> CreateCrmHistoryImportResponse:
    response = await _export_crm_history(
        workspace_id=workspace_id,
        request=request,
        actor=extension_device.actor,
        bundle=bundle,
        extension_device=extension_device,
    )
    await bundle.session.commit()
    return response


async def _export_crm_history(
    *,
    workspace_id: UUID,
    request: ExtensionExportCrmHistoryRequest,
    actor: AuthenticatedActor,
    bundle: CrmHistoryImportBundle,
    extension_device: AuthenticatedExtensionDevice | None,
) -> CreateCrmHistoryImportResponse:
    lead = await _refreshed_or_local_lead(
        workspace_id=workspace_id,
        crm_lead_id=request.crm_lead_id,
        bundle=bundle,
    )
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=["lead_not_found"])
    payloads = _event_payloads(request.events, source_url=request.source_url)
    if request.source_payload is not None:
        payloads += parse_fub_people_response(
            request.source_payload, request.crm_lead_id, request.source_url
        )
    if extension_device is None:
        created = await create_crm_history_import(
            actor=actor,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            enabled=bundle.settings.fub_history_import_enabled,
            lead_repository=bundle.lead_repository,
            job_repository=bundle.job_repository,
            audit_log_repository=bundle.audit_log_repository,
            now=datetime.now(UTC),
        )
    else:
        created = await create_extension_crm_history_import(
            extension_device=extension_device,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            enabled=bundle.settings.fub_history_import_enabled,
            lead_repository=bundle.lead_repository,
            job_repository=bundle.job_repository,
            audit_log_repository=bundle.audit_log_repository,
            now=datetime.now(UTC),
            batch_fingerprint=crm_history_export_batch_fingerprint(payloads),
        )
    _raise_if_rejected(created.status, created.reasons)
    assert created.job is not None
    if created.status is CrmHistoryImportMutationStatus.DUPLICATE:
        return CreateCrmHistoryImportResponse(
            status=created.status.value,
            job=_job_response(created.job),
            upload_token=None,
        )
    assert created.upload_token is not None
    await ingest_crm_history_events(
        workspace_id=workspace_id,
        import_job_id=created.job.import_job_id,
        upload_token=created.upload_token,
        payloads=payloads,
        job_repository=bundle.job_repository,
        event_repository=bundle.event_repository,
        now=datetime.now(UTC),
    )
    completed = await complete_crm_history_import_upload(
        workspace_id=workspace_id,
        import_job_id=created.job.import_job_id,
        upload_token=created.upload_token,
        job_repository=bundle.job_repository,
        audit_log_repository=bundle.audit_log_repository,
        now=datetime.now(UTC),
    )
    _raise_if_rejected(completed.status, completed.reasons)
    assert completed.job is not None
    return CreateCrmHistoryImportResponse(
        status=completed.status.value,
        job=_job_response(completed.job),
        upload_token=created.upload_token,
    )


@router.get(
    "/{workspace_id}/crm-history-imports/capability",
    response_model=CrmHistoryImportCapabilityResponse,
)
async def get_crm_history_import_capability_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CrmHistoryImportBundle, Depends(get_crm_history_import_bundle)],
) -> CrmHistoryImportCapabilityResponse:
    del workspace_id
    result = evaluate_crm_history_import_capability(
        actor=actor, enabled=bundle.settings.fub_history_import_enabled
    )
    return CrmHistoryImportCapabilityResponse(
        enabled=result.enabled,
        allowed=result.allowed,
        reasons=list(result.reasons),
    )


@router.post(
    "/{workspace_id}/crm-history-imports",
    response_model=CreateCrmHistoryImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_crm_history_import_route(
    workspace_id: UUID,
    request: CreateCrmHistoryImportRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CrmHistoryImportBundle, Depends(get_crm_history_import_bundle)],
) -> CreateCrmHistoryImportResponse:
    result = await create_crm_history_import(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=request.lead_id,
        enabled=bundle.settings.fub_history_import_enabled,
        lead_repository=bundle.lead_repository,
        job_repository=bundle.job_repository,
        audit_log_repository=bundle.audit_log_repository,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    _raise_if_rejected(result.status, result.reasons)
    assert result.job is not None
    assert result.upload_token is not None
    return CreateCrmHistoryImportResponse(
        status=result.status.value,
        job=_job_response(result.job),
        upload_token=result.upload_token,
    )


@router.get(
    "/{workspace_id}/crm-history-imports/{job_id}",
    response_model=CrmHistoryImportReadResponse,
)
async def read_crm_history_import_route(
    workspace_id: UUID,
    job_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CrmHistoryImportBundle, Depends(get_crm_history_import_bundle)],
) -> CrmHistoryImportReadResponse:
    result = await read_crm_history_import(
        actor=actor,
        workspace_id=workspace_id,
        import_job_id=job_id,
        job_repository=bundle.job_repository,
    )
    _raise_if_rejected(result.status, result.reasons)
    assert result.job is not None
    return CrmHistoryImportReadResponse(
        status=result.status.value,
        job=_job_response(result.job),
    )


@router.post(
    "/{workspace_id}/crm-history-imports/{job_id}/events",
    response_model=IngestCrmHistoryEventsResponse,
)
async def ingest_crm_history_events_route(
    workspace_id: UUID,
    job_id: UUID,
    request: IngestCrmHistoryEventsRequest,
    upload_token: Annotated[str, _TOKEN_HEADER],
    bundle: Annotated[CrmHistoryImportBundle, Depends(get_crm_history_import_bundle)],
) -> IngestCrmHistoryEventsResponse:
    payloads = _event_payloads(request.events)
    result = await ingest_crm_history_events(
        workspace_id=workspace_id,
        import_job_id=job_id,
        upload_token=upload_token,
        payloads=payloads,
        job_repository=bundle.job_repository,
        event_repository=bundle.event_repository,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    _raise_if_rejected(result.status, result.reasons)
    assert result.job is not None
    return IngestCrmHistoryEventsResponse(
        status=result.status.value,
        accepted_count=result.accepted_count,
        duplicate_count=result.duplicate_count,
        rejected_count=result.rejected_count,
        job=_job_response(result.job),
    )


@router.post(
    "/{workspace_id}/crm-history-imports/{job_id}/complete",
    response_model=CrmHistoryImportReadResponse,
)
async def complete_crm_history_import_upload_route(
    workspace_id: UUID,
    job_id: UUID,
    upload_token: Annotated[str, _TOKEN_HEADER],
    bundle: Annotated[CrmHistoryImportBundle, Depends(get_crm_history_import_bundle)],
) -> CrmHistoryImportReadResponse:
    result = await complete_crm_history_import_upload(
        workspace_id=workspace_id,
        import_job_id=job_id,
        upload_token=upload_token,
        job_repository=bundle.job_repository,
        audit_log_repository=bundle.audit_log_repository,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    _raise_if_rejected(result.status, result.reasons)
    assert result.job is not None
    return CrmHistoryImportReadResponse(
        status=result.status.value,
        job=_job_response(result.job),
    )


async def _refreshed_or_local_lead(
    *,
    workspace_id: UUID,
    crm_lead_id: str,
    bundle: CrmHistoryImportBundle,
) -> CanonicalLeadRecord | None:
    """Resolve the lead for an export, refreshing it from the CRM best-effort.

    When the CRM refresh source is available, the latest FUB snapshot is
    upserted (creating the lead if it is unknown locally) and tag enrollment is
    re-evaluated. Any CRM failure falls back to the locally stored lead so the
    history export never breaks on a CRM outage.
    """
    if bundle.lead_refresh_source is None:
        return await bundle.lead_repository.get_by_crm_id(
            workspace_id,
            CRMProvider.FOLLOW_UP_BOSS,
            crm_lead_id,
        )
    result = await refresh_lead_from_crm(
        workspace_id=workspace_id,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id=crm_lead_id,
        lead_refresh_source=bundle.lead_refresh_source,
        lead_repository=bundle.lead_repository,
        now=datetime.now(UTC),
        enrollment_deps=bundle.enrollment_dependencies,
    )
    if result.status is CrmLeadRefreshStatus.FAILED:
        logger.warning(
            "crm_history_export_lead_refresh_failed",
            workspace_id=str(workspace_id),
            crm_lead_id=crm_lead_id,
            reason=result.failure_reason,
        )
    return result.lead


def _job_response(job: CrmHistoryImportJob) -> CrmHistoryImportJobResponse:
    return CrmHistoryImportJobResponse(
        job_id=job.import_job_id,
        workspace_id=job.workspace_id,
        lead_id=job.lead_id,
        crm_lead_id=job.crm_lead_id,
        status=job.status.value,
        received_count=job.received_count,
        promoted_count=job.promoted_count,
        duplicate_count=job.duplicate_count,
        rejected_count=job.rejected_count,
        failure_reason=job.failure_reason,
        expires_at=job.token_expires_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _event_payloads(
    events: Sequence[CrmHistoryImportEventRequest],
    *,
    source_url: str | None = None,
) -> tuple[CrmHistoryImportEventPayload, ...]:
    payloads: list[CrmHistoryImportEventPayload] = []
    for event in events:
        details = dict(event.details)
        if source_url is not None:
            details.setdefault("source_url", source_url)
        payloads.append(
            CrmHistoryImportEventPayload(
                external_activity_id=event.external_activity_id,
                fingerprint=event.fingerprint,
                activity_type=event.activity_type,
                direction=event.direction,
                content=event.content,
                occurred_at=event.occurred_at,
                actor_agent_id=event.actor_agent_id,
                actor_name=event.actor_name,
                details=details,
            )
        )
    return tuple(payloads)


def _raise_if_rejected(
    operation_status: CrmHistoryImportMutationStatus | CrmHistoryImportReadStatus,
    reasons: tuple[str, ...],
) -> None:
    if operation_status not in {
        CrmHistoryImportMutationStatus.REJECTED,
        CrmHistoryImportReadStatus.REJECTED,
    }:
        return
    missing_resource = {
        CrmHistoryImportReasonCode.JOB_NOT_FOUND.value,
        CrmHistoryImportReasonCode.LEAD_NOT_FOUND.value,
    }
    if missing_resource.intersection(reasons):
        status_code = status.HTTP_404_NOT_FOUND
    elif CrmHistoryImportReasonCode.ACTIVE_JOB_EXISTS.value in reasons:
        status_code = status.HTTP_409_CONFLICT
    elif any(
        reason
        in {
            CrmHistoryImportReasonCode.TOKEN_INVALID.value,
            CrmHistoryImportReasonCode.TOKEN_EXPIRED.value,
        }
        for reason in reasons
    ):
        status_code = status.HTTP_401_UNAUTHORIZED
    elif CrmHistoryImportReasonCode.JOB_NOT_RECEIVING.value in reasons:
        status_code = status.HTTP_409_CONFLICT
    else:
        status_code = status.HTTP_403_FORBIDDEN
    raise HTTPException(status_code=status_code, detail=list(reasons))
