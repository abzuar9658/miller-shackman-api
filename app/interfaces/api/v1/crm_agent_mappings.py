from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.use_cases.crm_agent_mapping_admin import (
    CRMAgentDirectorySyncAdminResult,
    CRMAgentMappingAdminListResult,
    CRMAgentMappingAdminMutationResult,
    CRMAgentMappingAdminReasonCode,
    CRMAgentMappingAdminRow,
    CRMAgentMappingAdminStatus,
    CRMAgentMappingAdminSummary,
    list_crm_agent_mapping_admin_view,
    sync_crm_agent_directory_by_admin,
    unlink_crm_agent_mapping_by_admin,
    upsert_crm_agent_mapping_by_admin,
)
from app.application.use_cases.sync_crm_agents import SyncCRMAgentsResult
from app.domain.crm_agent_mapping import CRMAgent, WorkspaceAgentCRMMapping
from app.domain.identity import AuthenticatedActor, User
from app.interfaces.api.dependencies.crm_agent_mappings import (
    CRMAgentDirectorySyncBundle,
    CRMAgentMappingBundle,
    get_crm_agent_directory_sync_bundle,
    get_crm_agent_mapping_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.schemas.auth import UserResponse
from app.interfaces.api.schemas.crm_agent_mappings import (
    CRMAgentDirectorySyncResponse,
    CRMAgentDirectorySyncResultResponse,
    CRMAgentListResponse,
    CRMAgentMappingListResponse,
    CRMAgentMappingMutationResponse,
    CRMAgentMappingRowResponse,
    CRMAgentMappingSummaryResponse,
    CRMAgentResponse,
    PatchCRMAgentMappingRequest,
    UpsertCRMAgentMappingRequest,
    WorkspaceAgentCRMMappingResponse,
)

router = APIRouter(tags=["crm-agent-mappings"])


@router.get("/{workspace_id}/crm-agents", response_model=CRMAgentListResponse)
async def list_crm_agents_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CRMAgentMappingBundle, Depends(get_crm_agent_mapping_bundle)],
) -> CRMAgentListResponse:
    result = await list_crm_agent_mapping_admin_view(
        actor=actor,
        workspace_id=workspace_id,
        crm_agent_repository=bundle.crm_agent_repository,
        mapping_repository=bundle.mapping_repository,
        user_repository=bundle.user_repository,
    )
    _raise_if_rejected(result)
    return CRMAgentListResponse(
        status=result.status.value,
        agents=[_agent_response(row.agent) for row in result.rows],
        summary=_summary_response(result.summary),
    )


@router.get("/{workspace_id}/crm-agent-mappings", response_model=CRMAgentMappingListResponse)
async def list_crm_agent_mappings_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CRMAgentMappingBundle, Depends(get_crm_agent_mapping_bundle)],
) -> CRMAgentMappingListResponse:
    result = await list_crm_agent_mapping_admin_view(
        actor=actor,
        workspace_id=workspace_id,
        crm_agent_repository=bundle.crm_agent_repository,
        mapping_repository=bundle.mapping_repository,
        user_repository=bundle.user_repository,
    )
    _raise_if_rejected(result)
    summary = _summary_response(result.summary)
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Missing summary",
        )
    return CRMAgentMappingListResponse(
        status=result.status.value,
        rows=[_row_response(row) for row in result.rows],
        summary=summary,
    )


@router.post(
    "/{workspace_id}/crm-agent-mappings",
    response_model=CRMAgentMappingMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upsert_crm_agent_mapping_route(
    workspace_id: UUID,
    request: UpsertCRMAgentMappingRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CRMAgentMappingBundle, Depends(get_crm_agent_mapping_bundle)],
) -> CRMAgentMappingMutationResponse:
    result = await upsert_crm_agent_mapping_by_admin(
        actor=actor,
        workspace_id=workspace_id,
        crm_agent_record_id=request.crm_agent_record_id,
        app_user_id=request.app_user_id,
        crm_agent_repository=bundle.crm_agent_repository,
        mapping_repository=bundle.mapping_repository,
        user_repository=bundle.user_repository,
        membership_repository=bundle.membership_repository,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    _raise_if_rejected(result)
    return CRMAgentMappingMutationResponse(
        status=result.status.value,
        mapping=_mapping_response(result.mapping) if result.mapping is not None else None,
    )


@router.patch(
    "/{workspace_id}/crm-agent-mappings/{mapping_id}",
    response_model=CRMAgentMappingMutationResponse,
)
async def patch_crm_agent_mapping_route(
    workspace_id: UUID,
    mapping_id: UUID,
    request: PatchCRMAgentMappingRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CRMAgentMappingBundle, Depends(get_crm_agent_mapping_bundle)],
) -> CRMAgentMappingMutationResponse:
    existing = await bundle.mapping_repository.get_by_id(workspace_id, mapping_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[CRMAgentMappingAdminReasonCode.MAPPING_NOT_FOUND.value],
        )
    result = await upsert_crm_agent_mapping_by_admin(
        actor=actor,
        workspace_id=workspace_id,
        crm_agent_record_id=existing.crm_agent_record_id,
        app_user_id=request.app_user_id,
        crm_agent_repository=bundle.crm_agent_repository,
        mapping_repository=bundle.mapping_repository,
        user_repository=bundle.user_repository,
        membership_repository=bundle.membership_repository,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    _raise_if_rejected(result)
    return CRMAgentMappingMutationResponse(
        status=result.status.value,
        mapping=_mapping_response(result.mapping) if result.mapping is not None else None,
    )


@router.delete(
    "/{workspace_id}/crm-agent-mappings/{mapping_id}",
    response_model=CRMAgentMappingMutationResponse,
)
async def unlink_crm_agent_mapping_route(
    workspace_id: UUID,
    mapping_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CRMAgentMappingBundle, Depends(get_crm_agent_mapping_bundle)],
) -> CRMAgentMappingMutationResponse:
    result = await unlink_crm_agent_mapping_by_admin(
        actor=actor,
        workspace_id=workspace_id,
        mapping_id=mapping_id,
        mapping_repository=bundle.mapping_repository,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    _raise_if_rejected(result)
    return CRMAgentMappingMutationResponse(
        status=result.status.value,
        mapping=_mapping_response(result.mapping) if result.mapping is not None else None,
    )


@router.post(
    "/{workspace_id}/crm-agent-directory-sync",
    response_model=CRMAgentDirectorySyncResponse,
)
async def sync_crm_agent_directory_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        CRMAgentDirectorySyncBundle,
        Depends(get_crm_agent_directory_sync_bundle),
    ],
) -> CRMAgentDirectorySyncResponse:
    result = await sync_crm_agent_directory_by_admin(
        actor=actor,
        workspace_id=workspace_id,
        crm_agent_directory_source=bundle.crm_agent_directory_source,
        crm_agent_repository=bundle.crm_agent_repository,
        mapping_repository=bundle.mapping_repository,
        user_repository=bundle.user_repository,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    _raise_if_rejected(result)
    return CRMAgentDirectorySyncResponse(
        status=result.status.value,
        sync_result=_sync_result_response(result.sync_result),
        summary=_summary_response(result.summary),
    )


@router.get(
    "/{workspace_id}/crm-agent-directory-sync/status",
    response_model=CRMAgentDirectorySyncResponse,
)
async def get_crm_agent_directory_sync_status_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CRMAgentMappingBundle, Depends(get_crm_agent_mapping_bundle)],
) -> CRMAgentDirectorySyncResponse:
    result = await list_crm_agent_mapping_admin_view(
        actor=actor,
        workspace_id=workspace_id,
        crm_agent_repository=bundle.crm_agent_repository,
        mapping_repository=bundle.mapping_repository,
        user_repository=bundle.user_repository,
    )
    _raise_if_rejected(result)
    return CRMAgentDirectorySyncResponse(
        status=result.status.value,
        sync_result=None,
        summary=_summary_response(result.summary),
    )


def _raise_if_rejected(
    result: (
        CRMAgentMappingAdminListResult
        | CRMAgentMappingAdminMutationResult
        | CRMAgentDirectorySyncAdminResult
    ),
) -> None:
    if result.status not in {
        CRMAgentMappingAdminStatus.REJECTED,
        CRMAgentMappingAdminStatus.NOT_FOUND,
    }:
        return
    first_reason = result.reasons[0] if result.reasons else None
    raise HTTPException(
        status_code=_status_for_reason(first_reason),
        detail=[reason.value for reason in result.reasons],
    )


def _status_for_reason(reason: CRMAgentMappingAdminReasonCode | None) -> int:
    if reason == CRMAgentMappingAdminReasonCode.PERMISSION_DENIED:
        return status.HTTP_403_FORBIDDEN
    if reason in {
        CRMAgentMappingAdminReasonCode.CRM_AGENT_NOT_FOUND,
        CRMAgentMappingAdminReasonCode.MAPPING_NOT_FOUND,
        CRMAgentMappingAdminReasonCode.APP_USER_NOT_FOUND,
    }:
        return status.HTTP_404_NOT_FOUND
    return status.HTTP_400_BAD_REQUEST


def _agent_response(agent: CRMAgent) -> CRMAgentResponse:
    return CRMAgentResponse(
        agent_record_id=agent.agent_record_id,
        workspace_id=agent.workspace_id,
        crm_provider=agent.crm_provider.value,
        external_agent_id=agent.external_agent_id,
        name=agent.name,
        email=agent.email,
        phone=agent.phone,
        is_active=agent.is_active,
        last_seen_at=agent.last_seen_at,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def _mapping_response(
    mapping: WorkspaceAgentCRMMapping,
) -> WorkspaceAgentCRMMappingResponse:
    return WorkspaceAgentCRMMappingResponse(
        mapping_id=mapping.mapping_id,
        workspace_id=mapping.workspace_id,
        crm_agent_record_id=mapping.crm_agent_record_id,
        app_user_id=mapping.app_user_id,
        mapping_status=mapping.mapping_status.value,
        resolution_source=mapping.resolution_source.value,
        resolved_by_user_id=mapping.resolved_by_user_id,
        resolved_at=mapping.resolved_at,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
    )


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        user_id=user.user_id,
        email=user.email,
        full_name=user.full_name or user.email,
        status=user.status.value,
    )


def _row_response(row: CRMAgentMappingAdminRow) -> CRMAgentMappingRowResponse:
    agent = row.agent
    mapping = row.mapping
    app_user = row.app_user
    return CRMAgentMappingRowResponse(
        agent=_agent_response(agent),
        mapping=_mapping_response(mapping) if mapping is not None else None,
        app_user=_user_response(app_user) if app_user is not None else None,
    )


def _summary_response(
    summary: CRMAgentMappingAdminSummary | None,
) -> CRMAgentMappingSummaryResponse | None:
    if summary is None:
        return None
    return CRMAgentMappingSummaryResponse(
        total_agents=summary.total_agents,
        active_agents=summary.active_agents,
        inactive_agents=summary.inactive_agents,
        verified_count=summary.verified_count,
        suggested_count=summary.suggested_count,
        overridden_count=summary.overridden_count,
        disputed_count=summary.disputed_count,
        unmapped_count=summary.unmapped_count,
        last_agent_seen_at=summary.last_agent_seen_at,
    )


def _sync_result_response(
    result: SyncCRMAgentsResult | None,
) -> CRMAgentDirectorySyncResultResponse | None:
    if result is None:
        return None
    return CRMAgentDirectorySyncResultResponse(
        total_seen=result.total_seen,
        created_count=result.created_count,
        updated_count=result.updated_count,
        deactivated_count=result.deactivated_count,
        suggested_mapping_count=result.suggested_mapping_count,
        unmapped_mapping_count=result.unmapped_mapping_count,
    )
