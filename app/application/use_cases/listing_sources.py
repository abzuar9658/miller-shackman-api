from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.listing_sources import (
    ListingSearchScopeRepository,
    ListingSourceRepository,
)
from app.domain.identity import AuthenticatedActor, PermissionCapability, evaluate_permission
from app.domain.listing_sources import (
    ListingSearchScope,
    ListingSearchScopeType,
    ListingSource,
    ListingSourceType,
)


class ListingSourceStatus(StrEnum):
    OK = "ok"
    CREATED = "created"
    UPDATED = "updated"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


class ListingSourceReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_NAME_TAKEN = "source_name_taken"
    REVIEW_REQUIRED_TO_ENABLE = "review_required_to_enable"
    DATA_USE_POLICY_REQUIRED = "data_use_policy_required"
    INVALID_URL_PATTERN = "invalid_url_pattern"


@dataclass(frozen=True)
class ListingSourceResult:
    status: ListingSourceStatus
    source: ListingSource | None = None
    reasons: tuple[ListingSourceReasonCode, ...] = ()


@dataclass(frozen=True)
class ListingSourceListResult:
    status: ListingSourceStatus
    sources: tuple[ListingSource, ...] = ()
    reasons: tuple[ListingSourceReasonCode, ...] = ()


class ListingSearchScopeStatus(StrEnum):
    OK = "ok"
    CREATED = "created"
    UPDATED = "updated"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


class ListingSearchScopeReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    SOURCE_NOT_FOUND = "source_not_found"
    SCOPE_NOT_FOUND = "scope_not_found"
    SEARCH_CRITERIA_REQUIRED = "search_criteria_required"
    INVALID_PRICE_RANGE = "invalid_price_range"


@dataclass(frozen=True)
class ListingSearchScopeResult:
    status: ListingSearchScopeStatus
    scope: ListingSearchScope | None = None
    reasons: tuple[ListingSearchScopeReasonCode, ...] = ()


@dataclass(frozen=True)
class ListingSearchScopeListResult:
    status: ListingSearchScopeStatus
    scopes: tuple[ListingSearchScope, ...] = ()
    reasons: tuple[ListingSearchScopeReasonCode, ...] = ()


async def list_listing_sources(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    source_repository: ListingSourceRepository,
) -> ListingSourceListResult:
    permission = evaluate_permission(actor, PermissionCapability.MANAGE_LISTING_SOURCES)
    if not permission.allowed:
        return ListingSourceListResult(
            status=ListingSourceStatus.REJECTED,
            reasons=(ListingSourceReasonCode.PERMISSION_DENIED,),
        )
    return ListingSourceListResult(
        status=ListingSourceStatus.OK,
        sources=await source_repository.list_for_workspace(workspace_id),
    )


async def get_listing_source(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    source_id: UUID,
    source_repository: ListingSourceRepository,
) -> ListingSourceResult:
    permission = evaluate_permission(actor, PermissionCapability.MANAGE_LISTING_SOURCES)
    if not permission.allowed:
        return ListingSourceResult(
            status=ListingSourceStatus.REJECTED,
            reasons=(ListingSourceReasonCode.PERMISSION_DENIED,),
        )
    source = await source_repository.get_by_id(workspace_id, source_id)
    if source is None:
        return ListingSourceResult(
            status=ListingSourceStatus.NOT_FOUND,
            reasons=(ListingSourceReasonCode.SOURCE_NOT_FOUND,),
        )
    return ListingSourceResult(status=ListingSourceStatus.OK, source=source)


async def create_listing_source(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    name: str,
    source_type: ListingSourceType,
    base_url: str,
    allowed_url_patterns: tuple[str, ...],
    disallowed_url_patterns: tuple[str, ...],
    crawl_frequency_minutes: int,
    enabled: bool,
    requires_auth: bool,
    terms_reviewed_at: datetime | None,
    terms_reviewed_by_user_id: UUID | None,
    data_use_policy: str | None,
    source_repository: ListingSourceRepository,
    now: datetime,
) -> ListingSourceResult:
    permission = evaluate_permission(actor, PermissionCapability.MANAGE_LISTING_SOURCES)
    if not permission.allowed:
        return ListingSourceResult(
            status=ListingSourceStatus.REJECTED,
            reasons=(ListingSourceReasonCode.PERMISSION_DENIED,),
        )
    normalized_name = name.strip()
    existing = await source_repository.get_by_name(workspace_id, normalized_name)
    if existing is not None:
        return ListingSourceResult(
            status=ListingSourceStatus.REJECTED,
            reasons=(ListingSourceReasonCode.SOURCE_NAME_TAKEN,),
        )
    reasons = _source_validation_reasons(
        enabled=enabled,
        allowed_url_patterns=allowed_url_patterns,
        disallowed_url_patterns=disallowed_url_patterns,
        terms_reviewed_at=terms_reviewed_at,
        data_use_policy=data_use_policy,
    )
    if reasons:
        return ListingSourceResult(status=ListingSourceStatus.REJECTED, reasons=reasons)
    source = ListingSource(
        source_id=uuid4(),
        workspace_id=workspace_id,
        name=normalized_name,
        source_type=source_type,
        base_url=base_url.strip(),
        allowed_url_patterns=allowed_url_patterns,
        disallowed_url_patterns=disallowed_url_patterns,
        crawl_frequency_minutes=crawl_frequency_minutes,
        enabled=enabled,
        requires_auth=requires_auth,
        terms_reviewed_at=terms_reviewed_at,
        terms_reviewed_by_user_id=terms_reviewed_by_user_id,
        data_use_policy=_normalize_optional_text(data_use_policy),
        created_at=now,
        updated_at=now,
    )
    return ListingSourceResult(
        status=ListingSourceStatus.CREATED,
        source=await source_repository.save(source),
    )


async def update_listing_source(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    source_id: UUID,
    source_repository: ListingSourceRepository,
    now: datetime,
    name: str | None = None,
    source_type: ListingSourceType | None = None,
    base_url: str | None = None,
    allowed_url_patterns: tuple[str, ...] | None = None,
    disallowed_url_patterns: tuple[str, ...] | None = None,
    crawl_frequency_minutes: int | None = None,
    enabled: bool | None = None,
    requires_auth: bool | None = None,
    terms_reviewed_at: datetime | None = None,
    terms_reviewed_by_user_id: UUID | None = None,
    data_use_policy: str | None = None,
) -> ListingSourceResult:
    permission = evaluate_permission(actor, PermissionCapability.MANAGE_LISTING_SOURCES)
    if not permission.allowed:
        return ListingSourceResult(
            status=ListingSourceStatus.REJECTED,
            reasons=(ListingSourceReasonCode.PERMISSION_DENIED,),
        )
    current = await source_repository.get_by_id(workspace_id, source_id)
    if current is None:
        return ListingSourceResult(
            status=ListingSourceStatus.NOT_FOUND,
            reasons=(ListingSourceReasonCode.SOURCE_NOT_FOUND,),
        )
    normalized_name = name.strip() if name is not None else current.name
    if normalized_name != current.name:
        existing = await source_repository.get_by_name(workspace_id, normalized_name)
        if existing is not None and existing.source_id != source_id:
            return ListingSourceResult(
                status=ListingSourceStatus.REJECTED,
                reasons=(ListingSourceReasonCode.SOURCE_NAME_TAKEN,),
            )
    updated = replace(
        current,
        name=normalized_name,
        source_type=source_type or current.source_type,
        base_url=base_url.strip() if base_url is not None else current.base_url,
        allowed_url_patterns=(
            allowed_url_patterns
            if allowed_url_patterns is not None
            else current.allowed_url_patterns
        ),
        disallowed_url_patterns=(
            disallowed_url_patterns
            if disallowed_url_patterns is not None
            else current.disallowed_url_patterns
        ),
        crawl_frequency_minutes=(
            crawl_frequency_minutes
            if crawl_frequency_minutes is not None
            else current.crawl_frequency_minutes
        ),
        enabled=enabled if enabled is not None else current.enabled,
        requires_auth=requires_auth if requires_auth is not None else current.requires_auth,
        terms_reviewed_at=(
            terms_reviewed_at if terms_reviewed_at is not None else current.terms_reviewed_at
        ),
        terms_reviewed_by_user_id=(
            terms_reviewed_by_user_id
            if terms_reviewed_by_user_id is not None
            else current.terms_reviewed_by_user_id
        ),
        data_use_policy=(
            _normalize_optional_text(data_use_policy)
            if data_use_policy is not None
            else current.data_use_policy
        ),
        updated_at=now,
    )
    reasons = _source_validation_reasons(
        enabled=updated.enabled,
        allowed_url_patterns=updated.allowed_url_patterns,
        disallowed_url_patterns=updated.disallowed_url_patterns,
        terms_reviewed_at=updated.terms_reviewed_at,
        data_use_policy=updated.data_use_policy,
    )
    if reasons:
        return ListingSourceResult(status=ListingSourceStatus.REJECTED, reasons=reasons)
    return ListingSourceResult(
        status=ListingSourceStatus.UPDATED,
        source=await source_repository.save(updated),
    )


def _source_validation_reasons(
    *,
    enabled: bool,
    allowed_url_patterns: tuple[str, ...],
    disallowed_url_patterns: tuple[str, ...],
    terms_reviewed_at: datetime | None,
    data_use_policy: str | None,
) -> tuple[ListingSourceReasonCode, ...]:
    reasons: list[ListingSourceReasonCode] = []
    if any(not pattern.strip() for pattern in (*allowed_url_patterns, *disallowed_url_patterns)):
        reasons.append(ListingSourceReasonCode.INVALID_URL_PATTERN)
    if enabled and terms_reviewed_at is None:
        reasons.append(ListingSourceReasonCode.REVIEW_REQUIRED_TO_ENABLE)
    if enabled and not _normalize_optional_text(data_use_policy):
        reasons.append(ListingSourceReasonCode.DATA_USE_POLICY_REQUIRED)
    return tuple(reasons)


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


async def list_listing_search_scopes(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    source_id: UUID,
    source_repository: ListingSourceRepository,
    scope_repository: ListingSearchScopeRepository,
) -> ListingSearchScopeListResult:
    permission = evaluate_permission(actor, PermissionCapability.MANAGE_LISTING_SOURCES)
    if not permission.allowed:
        return ListingSearchScopeListResult(
            status=ListingSearchScopeStatus.REJECTED,
            reasons=(ListingSearchScopeReasonCode.PERMISSION_DENIED,),
        )
    source = await source_repository.get_by_id(workspace_id, source_id)
    if source is None:
        return ListingSearchScopeListResult(
            status=ListingSearchScopeStatus.NOT_FOUND,
            reasons=(ListingSearchScopeReasonCode.SOURCE_NOT_FOUND,),
        )
    return ListingSearchScopeListResult(
        status=ListingSearchScopeStatus.OK,
        scopes=await scope_repository.list_for_source(workspace_id, source_id),
    )


async def create_listing_search_scope(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    source_id: UUID,
    search_type: ListingSearchScopeType,
    locations: tuple[str, ...],
    addresses: tuple[str, ...],
    keywords: tuple[str, ...],
    min_price: Decimal | None,
    max_price: Decimal | None,
    min_beds: Decimal | None,
    limit: int,
    enabled: bool,
    source_repository: ListingSourceRepository,
    scope_repository: ListingSearchScopeRepository,
    now: datetime,
) -> ListingSearchScopeResult:
    permission = evaluate_permission(actor, PermissionCapability.MANAGE_LISTING_SOURCES)
    if not permission.allowed:
        return ListingSearchScopeResult(
            status=ListingSearchScopeStatus.REJECTED,
            reasons=(ListingSearchScopeReasonCode.PERMISSION_DENIED,),
        )
    source = await source_repository.get_by_id(workspace_id, source_id)
    if source is None:
        return ListingSearchScopeResult(
            status=ListingSearchScopeStatus.NOT_FOUND,
            reasons=(ListingSearchScopeReasonCode.SOURCE_NOT_FOUND,),
        )
    normalized_locations = _normalized_terms(locations)
    normalized_addresses = _normalized_terms(addresses)
    normalized_keywords = _normalized_terms(keywords)
    reasons = _scope_validation_reasons(
        locations=normalized_locations,
        addresses=normalized_addresses,
        keywords=normalized_keywords,
        min_price=min_price,
        max_price=max_price,
    )
    if reasons:
        return ListingSearchScopeResult(status=ListingSearchScopeStatus.REJECTED, reasons=reasons)
    scope = ListingSearchScope(
        scope_id=uuid4(),
        workspace_id=workspace_id,
        source_id=source_id,
        search_type=search_type,
        locations=normalized_locations,
        addresses=normalized_addresses,
        keywords=normalized_keywords,
        min_price=min_price,
        max_price=max_price,
        min_beds=min_beds,
        limit=limit,
        enabled=enabled,
        created_at=now,
        updated_at=now,
    )
    return ListingSearchScopeResult(
        status=ListingSearchScopeStatus.CREATED,
        scope=await scope_repository.save(scope),
    )


async def update_listing_search_scope(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    source_id: UUID,
    scope_id: UUID,
    source_repository: ListingSourceRepository,
    scope_repository: ListingSearchScopeRepository,
    now: datetime,
    search_type: ListingSearchScopeType | None = None,
    locations: tuple[str, ...] | None = None,
    addresses: tuple[str, ...] | None = None,
    keywords: tuple[str, ...] | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    min_beds: Decimal | None = None,
    limit: int | None = None,
    enabled: bool | None = None,
) -> ListingSearchScopeResult:
    permission = evaluate_permission(actor, PermissionCapability.MANAGE_LISTING_SOURCES)
    if not permission.allowed:
        return ListingSearchScopeResult(
            status=ListingSearchScopeStatus.REJECTED,
            reasons=(ListingSearchScopeReasonCode.PERMISSION_DENIED,),
        )
    source = await source_repository.get_by_id(workspace_id, source_id)
    if source is None:
        return ListingSearchScopeResult(
            status=ListingSearchScopeStatus.NOT_FOUND,
            reasons=(ListingSearchScopeReasonCode.SOURCE_NOT_FOUND,),
        )
    current = await scope_repository.get_by_id(workspace_id, scope_id)
    if current is None or current.source_id != source_id:
        return ListingSearchScopeResult(
            status=ListingSearchScopeStatus.NOT_FOUND,
            reasons=(ListingSearchScopeReasonCode.SCOPE_NOT_FOUND,),
        )
    normalized_locations = (
        _normalized_terms(locations) if locations is not None else current.locations
    )
    normalized_addresses = (
        _normalized_terms(addresses) if addresses is not None else current.addresses
    )
    normalized_keywords = _normalized_terms(keywords) if keywords is not None else current.keywords
    updated = replace(
        current,
        search_type=search_type or current.search_type,
        locations=normalized_locations,
        addresses=normalized_addresses,
        keywords=normalized_keywords,
        min_price=min_price if min_price is not None else current.min_price,
        max_price=max_price if max_price is not None else current.max_price,
        min_beds=min_beds if min_beds is not None else current.min_beds,
        limit=limit if limit is not None else current.limit,
        enabled=enabled if enabled is not None else current.enabled,
        updated_at=now,
    )
    reasons = _scope_validation_reasons(
        locations=updated.locations,
        addresses=updated.addresses,
        keywords=updated.keywords,
        min_price=updated.min_price,
        max_price=updated.max_price,
    )
    if reasons:
        return ListingSearchScopeResult(status=ListingSearchScopeStatus.REJECTED, reasons=reasons)
    return ListingSearchScopeResult(
        status=ListingSearchScopeStatus.UPDATED,
        scope=await scope_repository.save(updated),
    )


def _normalized_terms(values: tuple[str, ...] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    return tuple(value.strip() for value in values if value.strip())


def _scope_validation_reasons(
    *,
    locations: tuple[str, ...],
    addresses: tuple[str, ...],
    keywords: tuple[str, ...],
    min_price: Decimal | None,
    max_price: Decimal | None,
) -> tuple[ListingSearchScopeReasonCode, ...]:
    reasons: list[ListingSearchScopeReasonCode] = []
    if not locations and not addresses and not keywords:
        reasons.append(ListingSearchScopeReasonCode.SEARCH_CRITERIA_REQUIRED)
    if min_price is not None and max_price is not None and min_price > max_price:
        reasons.append(ListingSearchScopeReasonCode.INVALID_PRICE_RANGE)
    return tuple(reasons)
