from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.application.use_cases.crm_history_imports import (
    CrmHistoryImportMutationStatus,
    CrmHistoryImportReadStatus,
    CrmHistoryImportReasonCode,
    complete_crm_history_import_upload,
    create_crm_history_import,
    evaluate_crm_history_import_capability,
    ingest_crm_history_events,
    read_crm_history_import,
)
from app.domain.crm_history_imports import (
    CrmHistoryImportEventPayload,
    CrmHistoryImportJob,
)
from app.domain.identity import AuthenticatedActor
from app.domain.leads import CRMProvider
from app.infrastructure.crm.follow_up_boss.history_import_parser import (
    parse_fub_people_response,
)
from app.interfaces.api.dependencies.crm_history_imports import (
    CrmHistoryImportBundle,
    get_crm_history_import_bundle,
)
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


@router.post(
    "/{workspace_id}/crm-history-imports/export",
    response_model=CreateCrmHistoryImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def export_crm_history_from_extension_route(
    workspace_id: UUID,
    request: ExtensionExportCrmHistoryRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CrmHistoryImportBundle, Depends(get_crm_history_import_bundle)],
) -> CreateCrmHistoryImportResponse:
    lead = await bundle.lead_repository.get_by_crm_id(
        workspace_id,
        CRMProvider.FOLLOW_UP_BOSS,
        request.crm_lead_id,
    )
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=["lead_not_found"])
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
    _raise_if_rejected(created.status, created.reasons)
    assert created.job is not None and created.upload_token is not None
    payloads = _event_payloads(request.events, source_url=request.source_url)
    if request.source_payload is not None:
        payloads += parse_fub_people_response(
            request.source_payload, request.crm_lead_id, request.source_url
        )
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
    await bundle.session.commit()
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
