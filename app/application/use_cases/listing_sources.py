from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.listing_sources import ListingSourceRepository
from app.domain.identity import AuthenticatedActor, PermissionCapability, evaluate_permission
from app.domain.listing_sources import ListingSource, ListingSourceType


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