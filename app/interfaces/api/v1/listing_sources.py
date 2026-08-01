from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.use_cases.listing_source_crawls import (
    RequestListingSourceCrawlReasonCode,
    RequestListingSourceCrawlStatus,
    compute_listing_source_next_due_at,
    request_listing_source_crawl_by_actor,
)
from app.application.use_cases.listing_sources import (
    ListingSearchScopeReasonCode,
    ListingSearchScopeStatus,
    ListingSourceReasonCode,
    ListingSourceStatus,
    create_listing_search_scope,
    create_listing_source,
    get_listing_source,
    list_listing_search_scopes,
    list_listing_sources,
    update_listing_search_scope,
    update_listing_source,
)
from app.domain.identity import AuthenticatedActor
from app.domain.listing_sources import ListingCrawlRun, ListingSearchScope, ListingSource
from app.interfaces.api.dependencies.listing_sources import (
    ListingSourceBundle,
    get_listing_source_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.schemas.listing_sources import (
    ListingCrawlRunResponse,
    ListingSearchScopeListResponse,
    ListingSearchScopeRequest,
    ListingSearchScopeResponse,
    ListingSearchScopeResultResponse,
    ListingSourceCrawlRequestResponse,
    ListingSourceListResponse,
    ListingSourceRequest,
    ListingSourceResponse,
    ListingSourceResultResponse,
    UpdateListingSearchScopeRequest,
    UpdateListingSourceRequest,
)

router = APIRouter(tags=["listing_sources"])


def _crawl_run_response(crawl_run: ListingCrawlRun) -> ListingCrawlRunResponse:
    return ListingCrawlRunResponse(
        crawl_run_id=crawl_run.crawl_run_id,
        status=crawl_run.status.value,
        started_at=crawl_run.started_at,
        finished_at=crawl_run.finished_at,
        inserted_count=crawl_run.inserted_count,
        unchanged_count=crawl_run.unchanged_count,
        failed_count=crawl_run.failed_count,
        error_summary=crawl_run.error_summary,
    )


def _scope_response(scope: ListingSearchScope) -> ListingSearchScopeResponse:
    return ListingSearchScopeResponse(
        scope_id=scope.scope_id,
        workspace_id=scope.workspace_id,
        source_id=scope.source_id,
        search_type=scope.search_type.value,
        locations=list(scope.locations),
        addresses=list(scope.addresses),
        keywords=list(scope.keywords),
        min_price=scope.min_price,
        max_price=scope.max_price,
        min_beds=scope.min_beds,
        limit=scope.limit,
        enabled=scope.enabled,
        created_at=scope.created_at,
        updated_at=scope.updated_at,
    )


async def _source_response(
    source: ListingSource,
    bundle: ListingSourceBundle,
    *,
    now: datetime,
) -> ListingSourceResponse:
    scopes = await bundle.scope_repository.list_for_source(source.workspace_id, source.source_id)
    recent_crawl_runs = await bundle.crawl_run_repository.list_for_source(
        source.workspace_id,
        source.source_id,
        limit=5,
    )
    latest_crawl_run = recent_crawl_runs[0] if recent_crawl_runs else None
    active_crawl_run = await bundle.crawl_run_repository.get_active_for_source(
        source.workspace_id,
        source.source_id,
    )
    has_enabled_scopes = any(scope.enabled for scope in scopes)
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
        scopes=[_scope_response(scope) for scope in scopes],
        latest_crawl_run=(
            _crawl_run_response(latest_crawl_run) if latest_crawl_run is not None else None
        ),
        recent_crawl_runs=[_crawl_run_response(crawl_run) for crawl_run in recent_crawl_runs],
        next_due_at=compute_listing_source_next_due_at(
            source=source,
            latest_crawl_run=latest_crawl_run,
            active_crawl_run=active_crawl_run,
            has_enabled_scopes=has_enabled_scopes,
            now=now,
        ),
    )


def _raise_for_reasons(reasons: tuple[ListingSourceReasonCode, ...]) -> None:
    status_code = (
        status.HTTP_403_FORBIDDEN
        if ListingSourceReasonCode.PERMISSION_DENIED in reasons
        else status.HTTP_400_BAD_REQUEST
    )
    raise HTTPException(status_code=status_code, detail=[reason.value for reason in reasons])


def _raise_for_scope_reasons(reasons: tuple[ListingSearchScopeReasonCode, ...]) -> None:
    status_code = (
        status.HTTP_403_FORBIDDEN
        if ListingSearchScopeReasonCode.PERMISSION_DENIED in reasons
        else status.HTTP_400_BAD_REQUEST
    )
    raise HTTPException(status_code=status_code, detail=[reason.value for reason in reasons])


def _raise_for_crawl_request_reasons(
    reasons: tuple[RequestListingSourceCrawlReasonCode, ...],
) -> None:
    if RequestListingSourceCrawlReasonCode.PERMISSION_DENIED in reasons:
        status_code = status.HTTP_403_FORBIDDEN
    elif RequestListingSourceCrawlReasonCode.SOURCE_NOT_FOUND in reasons:
        status_code = status.HTTP_404_NOT_FOUND
    else:
        status_code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=status_code, detail=[reason.value for reason in reasons])


@router.get("/{workspace_id}/listing-sources", response_model=ListingSourceListResponse)
async def list_listing_sources_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[ListingSourceBundle, Depends(get_listing_source_bundle)],
) -> ListingSourceListResponse:
    now = datetime.now(UTC)
    result = await list_listing_sources(
        actor=actor,
        workspace_id=workspace_id,
        source_repository=bundle.source_repository,
    )
    if result.status == ListingSourceStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    sources: list[ListingSourceResponse] = []
    for source in result.sources:
        sources.append(await _source_response(source, bundle, now=now))
    return ListingSourceListResponse(
        status=result.status.value,
        sources=sources,
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
    now = datetime.now(UTC)
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
        source=await _source_response(result.source, bundle, now=now) if result.source else None,
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
    now = datetime.now(UTC)
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
        now=now,
    )
    if result.status == ListingSourceStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    await bundle.session.commit()
    return ListingSourceResultResponse(
        status=result.status.value,
        source=await _source_response(result.source, bundle, now=now) if result.source else None,
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
    now = datetime.now(UTC)
    result = await update_listing_source(
        actor=actor,
        workspace_id=workspace_id,
        source_id=source_id,
        source_repository=bundle.source_repository,
        now=now,
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
        source=await _source_response(result.source, bundle, now=now) if result.source else None,
    )


@router.post(
    "/{workspace_id}/listing-sources/{source_id}/request-crawl",
    response_model=ListingSourceCrawlRequestResponse,
)
async def request_listing_source_crawl_route(
    workspace_id: UUID,
    source_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[ListingSourceBundle, Depends(get_listing_source_bundle)],
) -> ListingSourceCrawlRequestResponse:
    result = await request_listing_source_crawl_by_actor(
        actor=actor,
        workspace_id=workspace_id,
        source_id=source_id,
        source_repository=bundle.source_repository,
        scope_repository=bundle.scope_repository,
        crawl_run_repository=bundle.crawl_run_repository,
        event_bus=bundle.event_bus,
        now=datetime.now(UTC),
    )
    if result.status == RequestListingSourceCrawlStatus.REJECTED:
        _raise_for_crawl_request_reasons(result.reasons)
    if result.status == RequestListingSourceCrawlStatus.REQUESTED:
        await bundle.session.commit()
    return ListingSourceCrawlRequestResponse(
        status=result.status.value,
        crawl_run=_crawl_run_response(result.crawl_run) if result.crawl_run is not None else None,
    )


@router.get(
    "/{workspace_id}/listing-sources/{source_id}/scopes",
    response_model=ListingSearchScopeListResponse,
)
async def list_listing_search_scopes_route(
    workspace_id: UUID,
    source_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[ListingSourceBundle, Depends(get_listing_source_bundle)],
) -> ListingSearchScopeListResponse:
    result = await list_listing_search_scopes(
        actor=actor,
        workspace_id=workspace_id,
        source_id=source_id,
        source_repository=bundle.source_repository,
        scope_repository=bundle.scope_repository,
    )
    if result.status == ListingSearchScopeStatus.REJECTED:
        _raise_for_scope_reasons(result.reasons)
    if result.status == ListingSearchScopeStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    return ListingSearchScopeListResponse(
        status=result.status.value,
        scopes=[_scope_response(scope) for scope in result.scopes],
    )


@router.post(
    "/{workspace_id}/listing-sources/{source_id}/scopes",
    response_model=ListingSearchScopeResultResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_listing_search_scope_route(
    workspace_id: UUID,
    source_id: UUID,
    request: ListingSearchScopeRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[ListingSourceBundle, Depends(get_listing_source_bundle)],
) -> ListingSearchScopeResultResponse:
    result = await create_listing_search_scope(
        actor=actor,
        workspace_id=workspace_id,
        source_id=source_id,
        search_type=request.search_type,
        locations=tuple(request.locations),
        addresses=tuple(request.addresses),
        keywords=tuple(request.keywords),
        min_price=request.min_price,
        max_price=request.max_price,
        min_beds=request.min_beds,
        limit=request.limit,
        enabled=request.enabled,
        source_repository=bundle.source_repository,
        scope_repository=bundle.scope_repository,
        now=datetime.now(UTC),
    )
    if result.status == ListingSearchScopeStatus.REJECTED:
        _raise_for_scope_reasons(result.reasons)
    if result.status == ListingSearchScopeStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    await bundle.session.commit()
    return ListingSearchScopeResultResponse(
        status=result.status.value,
        scope=_scope_response(result.scope) if result.scope else None,
    )


@router.patch(
    "/{workspace_id}/listing-sources/{source_id}/scopes/{scope_id}",
    response_model=ListingSearchScopeResultResponse,
)
async def update_listing_search_scope_route(
    workspace_id: UUID,
    source_id: UUID,
    scope_id: UUID,
    request: UpdateListingSearchScopeRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[ListingSourceBundle, Depends(get_listing_source_bundle)],
) -> ListingSearchScopeResultResponse:
    result = await update_listing_search_scope(
        actor=actor,
        workspace_id=workspace_id,
        source_id=source_id,
        scope_id=scope_id,
        source_repository=bundle.source_repository,
        scope_repository=bundle.scope_repository,
        now=datetime.now(UTC),
        search_type=request.search_type,
        locations=tuple(request.locations) if request.locations is not None else None,
        addresses=tuple(request.addresses) if request.addresses is not None else None,
        keywords=tuple(request.keywords) if request.keywords is not None else None,
        min_price=request.min_price,
        max_price=request.max_price,
        min_beds=request.min_beds,
        limit=request.limit,
        enabled=request.enabled,
    )
    if result.status == ListingSearchScopeStatus.REJECTED:
        _raise_for_scope_reasons(result.reasons)
    if result.status == ListingSearchScopeStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    await bundle.session.commit()
    return ListingSearchScopeResultResponse(
        status=result.status.value,
        scope=_scope_response(result.scope) if result.scope else None,
    )
