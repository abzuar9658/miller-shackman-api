from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.use_cases.listing_sources import (
    ListingSourceReasonCode,
    ListingSourceStatus,
    create_listing_source,
    get_listing_source,
    list_listing_sources,
    update_listing_source,
)
from app.domain.identity import AuthenticatedActor
from app.domain.listing_sources import ListingSource
from app.interfaces.api.dependencies.listing_sources import (
    ListingSourceBundle,
    get_listing_source_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.schemas.listing_sources import (
    ListingSourceListResponse,
    ListingSourceRequest,
    ListingSourceResponse,
    ListingSourceResultResponse,
    UpdateListingSourceRequest,
)

router = APIRouter(tags=["listing_sources"])


def _source_response(source: ListingSource) -> ListingSourceResponse:
    return ListingSourceResponse(
        source_id=source.source_id,
        workspace_id=source.workspace_id,
        name=source.name,
        source_type=source.source_type.value,
        base_url=source.base_url,
        allowed_url_patterns=list(source.allowed_url_patterns),
        disallowed_url_patterns=list(source.disallowed_url_patterns),
        crawl_frequency_minutes=source.crawl_frequency_minutes,
        enabled=source.enabled,
        requires_auth=source.requires_auth,
        terms_reviewed_at=source.terms_reviewed_at,
        terms_reviewed_by_user_id=source.terms_reviewed_by_user_id,
        data_use_policy=source.data_use_policy,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _raise_for_reasons(reasons: tuple[ListingSourceReasonCode, ...]) -> None:
    status_code = (
        status.HTTP_403_FORBIDDEN
        if ListingSourceReasonCode.PERMISSION_DENIED in reasons
        else status.HTTP_400_BAD_REQUEST
    )
    raise HTTPException(status_code=status_code, detail=[reason.value for reason in reasons])


@router.get("/{workspace_id}/listing-sources", response_model=ListingSourceListResponse)
async def list_listing_sources_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[ListingSourceBundle, Depends(get_listing_source_bundle)],
) -> ListingSourceListResponse:
    result = await list_listing_sources(
        actor=actor,
        workspace_id=workspace_id,
        source_repository=bundle.source_repository,
    )
    if result.status == ListingSourceStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return ListingSourceListResponse(
        status=result.status.value,
        sources=[_source_response(source) for source in result.sources],
    )


@router.get(
    "/{workspace_id}/listing-sources/{source_id}",
    response_model=ListingSourceResultResponse,
)
async def get_listing_source_route(
    workspace_id: UUID,
    source_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[ListingSourceBundle, Depends(get_listing_source_bundle)],
) -> ListingSourceResultResponse:
    result = await get_listing_source(
        actor=actor,
        workspace_id=workspace_id,
        source_id=source_id,
        source_repository=bundle.source_repository,
    )
    if result.status == ListingSourceStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    if result.status == ListingSourceStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    return ListingSourceResultResponse(
        status=result.status.value,
        source=_source_response(result.source) if result.source else None,
    )


@router.post(
    "/{workspace_id}/listing-sources",
    response_model=ListingSourceResultResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_listing_source_route(
    workspace_id: UUID,
    request: ListingSourceRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[ListingSourceBundle, Depends(get_listing_source_bundle)],
) -> ListingSourceResultResponse:
    result = await create_listing_source(
        actor=actor,
        workspace_id=workspace_id,
        name=request.name,
        source_type=request.source_type,
        base_url=str(request.base_url),
        allowed_url_patterns=tuple(request.allowed_url_patterns),
        disallowed_url_patterns=tuple(request.disallowed_url_patterns),
        crawl_frequency_minutes=request.crawl_frequency_minutes,
        enabled=request.enabled,
        requires_auth=request.requires_auth,
        terms_reviewed_at=request.terms_reviewed_at,
        terms_reviewed_by_user_id=request.terms_reviewed_by_user_id,
        data_use_policy=request.data_use_policy,
        source_repository=bundle.source_repository,
        now=datetime.now(UTC),
    )
    if result.status == ListingSourceStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    await bundle.session.commit()
    return ListingSourceResultResponse(
        status=result.status.value,
        source=_source_response(result.source) if result.source else None,
    )


@router.patch(
    "/{workspace_id}/listing-sources/{source_id}",
    response_model=ListingSourceResultResponse,
)
async def update_listing_source_route(
    workspace_id: UUID,
    source_id: UUID,
    request: UpdateListingSourceRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[ListingSourceBundle, Depends(get_listing_source_bundle)],
) -> ListingSourceResultResponse:
    result = await update_listing_source(
        actor=actor,
        workspace_id=workspace_id,
        source_id=source_id,
        source_repository=bundle.source_repository,
        now=datetime.now(UTC),
        name=request.name,
        source_type=request.source_type,
        base_url=str(request.base_url) if request.base_url is not None else None,
        allowed_url_patterns=(
            tuple(request.allowed_url_patterns)
            if request.allowed_url_patterns is not None
            else None
        ),
        disallowed_url_patterns=(
            tuple(request.disallowed_url_patterns)
            if request.disallowed_url_patterns is not None
            else None
        ),
        crawl_frequency_minutes=request.crawl_frequency_minutes,
        enabled=request.enabled,
        requires_auth=request.requires_auth,
        terms_reviewed_at=request.terms_reviewed_at,
        terms_reviewed_by_user_id=request.terms_reviewed_by_user_id,
        data_use_policy=request.data_use_policy,
    )
    if result.status == ListingSourceStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    if result.status == ListingSourceStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    await bundle.session.commit()
    return ListingSourceResultResponse(
        status=result.status.value,
        source=_source_response(result.source) if result.source else None,
    )