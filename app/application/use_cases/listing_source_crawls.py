from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from urllib.parse import urlparse
from uuid import UUID, uuid4

from app.application.ports.event_bus import EventBus
from app.application.ports.listing_search import (
    ListingSearchClient,
    ListingSearchQuery,
    ListingSearchType,
)
from app.application.ports.listing_sources import (
    ListingCrawlRunRepository,
    ListingSearchScopeRepository,
    ListingSnapshotRepository,
    ListingSourceRepository,
)
from app.domain.events import AggregateType, DomainEvent, DomainEventType
from app.domain.identity import AuthenticatedActor, PermissionCapability, evaluate_permission
from app.domain.listing_sources import (
    CanonicalListingSnapshot,
    ListingCrawlRun,
    ListingCrawlStatus,
    ListingSearchScope,
    ListingSource,
)

STREETEASY_HOST = "streeteasy.com"


class RequestListingSourceCrawlStatus(StrEnum):
    REQUESTED = "requested"
    ALREADY_ACTIVE = "already_active"
    REJECTED = "rejected"


class RequestListingSourceCrawlReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_DISABLED = "source_disabled"
    SOURCE_NOT_READY = "source_not_ready"
    SOURCE_UNSUPPORTED = "source_unsupported"
    NO_ENABLED_SCOPES = "no_enabled_scopes"


@dataclass(frozen=True)
class RequestListingSourceCrawlResult:
    status: RequestListingSourceCrawlStatus
    crawl_run: ListingCrawlRun | None
    reasons: tuple[RequestListingSourceCrawlReasonCode, ...] = ()


class ExecuteQueuedListingSourceCrawlStatus(StrEnum):
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    NOT_CLAIMED = "not_claimed"


@dataclass(frozen=True)
class ExecuteQueuedListingSourceCrawlResult:
    status: ExecuteQueuedListingSourceCrawlStatus
    crawl_run: ListingCrawlRun | None


@dataclass(frozen=True)
class EnqueueDueListingSourceCrawlsResult:
    scanned_count: int
    requested_count: int
    skipped_active_count: int
    skipped_not_due_count: int
    skipped_not_ready_count: int
    skipped_no_scopes_count: int
    skipped_unsupported_count: int


async def request_listing_source_crawl(
    *,
    workspace_id: UUID,
    source_id: UUID,
    source_repository: ListingSourceRepository,
    scope_repository: ListingSearchScopeRepository,
    crawl_run_repository: ListingCrawlRunRepository,
    event_bus: EventBus,
    now: datetime,
) -> RequestListingSourceCrawlResult:
    source = await source_repository.get_by_id(workspace_id, source_id)
    if source is None:
        return RequestListingSourceCrawlResult(
            status=RequestListingSourceCrawlStatus.REJECTED,
            crawl_run=None,
            reasons=(RequestListingSourceCrawlReasonCode.SOURCE_NOT_FOUND,),
        )
    if not source.enabled:
        return RequestListingSourceCrawlResult(
            status=RequestListingSourceCrawlStatus.REJECTED,
            crawl_run=None,
            reasons=(RequestListingSourceCrawlReasonCode.SOURCE_DISABLED,),
        )
    if not _source_ready_for_crawl(source):
        return RequestListingSourceCrawlResult(
            status=RequestListingSourceCrawlStatus.REJECTED,
            crawl_run=None,
            reasons=(RequestListingSourceCrawlReasonCode.SOURCE_NOT_READY,),
        )
    if not _source_supported_by_search_client(source):
        return RequestListingSourceCrawlResult(
            status=RequestListingSourceCrawlStatus.REJECTED,
            crawl_run=None,
            reasons=(RequestListingSourceCrawlReasonCode.SOURCE_UNSUPPORTED,),
        )

    enabled_scopes = await _enabled_scopes_for_source(
        scope_repository=scope_repository,
        workspace_id=workspace_id,
        source_id=source_id,
    )
    if not enabled_scopes:
        return RequestListingSourceCrawlResult(
            status=RequestListingSourceCrawlStatus.REJECTED,
            crawl_run=None,
            reasons=(RequestListingSourceCrawlReasonCode.NO_ENABLED_SCOPES,),
        )

    pending = ListingCrawlRun(
        crawl_run_id=uuid4(),
        workspace_id=workspace_id,
        source_id=source_id,
        status=ListingCrawlStatus.PENDING,
        started_at=now,
        created_at=now,
        updated_at=now,
    )
    inserted = await crawl_run_repository.insert_pending_if_no_active(pending)
    if inserted is None:
        active = await crawl_run_repository.get_active_for_source(workspace_id, source_id)
        return RequestListingSourceCrawlResult(
            status=RequestListingSourceCrawlStatus.ALREADY_ACTIVE,
            crawl_run=active,
        )

    await event_bus.publish(
        DomainEvent(
            workspace_id=workspace_id,
            aggregate_type=AggregateType.LISTING_SOURCE,
            aggregate_id=source_id,
            event_type=DomainEventType.LISTING_SOURCE_CRAWL_REQUESTED,
            payload={
                "source_id": str(source_id),
                "crawl_run_id": str(inserted.crawl_run_id),
                "requested_at": now.isoformat(),
            },
        )
    )
    return RequestListingSourceCrawlResult(
        status=RequestListingSourceCrawlStatus.REQUESTED,
        crawl_run=inserted,
    )


async def request_listing_source_crawl_by_actor(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    source_id: UUID,
    source_repository: ListingSourceRepository,
    scope_repository: ListingSearchScopeRepository,
    crawl_run_repository: ListingCrawlRunRepository,
    event_bus: EventBus,
    now: datetime,
) -> RequestListingSourceCrawlResult:
    permission = evaluate_permission(actor, PermissionCapability.MANAGE_LISTING_SOURCES)
    if not permission.allowed:
        return RequestListingSourceCrawlResult(
            status=RequestListingSourceCrawlStatus.REJECTED,
            crawl_run=None,
            reasons=(RequestListingSourceCrawlReasonCode.PERMISSION_DENIED,),
        )
    return await request_listing_source_crawl(
        workspace_id=workspace_id,
        source_id=source_id,
        source_repository=source_repository,
        scope_repository=scope_repository,
        crawl_run_repository=crawl_run_repository,
        event_bus=event_bus,
        now=now,
    )


def compute_listing_source_next_due_at(
    *,
    source: ListingSource,
    latest_crawl_run: ListingCrawlRun | None,
    active_crawl_run: ListingCrawlRun | None,
    has_enabled_scopes: bool,
    now: datetime,
) -> datetime | None:
    if (
        not source.enabled
        or not has_enabled_scopes
        or active_crawl_run is not None
        or not _source_ready_for_crawl(source)
        or not _source_supported_by_search_client(source)
    ):
        return None
    if latest_crawl_run is None:
        return now
    due_at = _latest_attempt_at(latest_crawl_run) + timedelta(
        minutes=source.crawl_frequency_minutes
    )
    return due_at if due_at > now else now


async def enqueue_due_listing_source_crawls(
    *,
    source_repository: ListingSourceRepository,
    scope_repository: ListingSearchScopeRepository,
    crawl_run_repository: ListingCrawlRunRepository,
    event_bus: EventBus,
    now: datetime,
    source_limit: int = 100,
) -> EnqueueDueListingSourceCrawlsResult:
    sources = await source_repository.list_enabled(limit=source_limit)
    requested_count = 0
    skipped_active_count = 0
    skipped_not_due_count = 0
    skipped_not_ready_count = 0
    skipped_no_scopes_count = 0
    skipped_unsupported_count = 0

    for source in sources:
        if not _source_ready_for_crawl(source):
            skipped_not_ready_count += 1
            continue
        if not _source_supported_by_search_client(source):
            skipped_unsupported_count += 1
            continue
        enabled_scopes = await _enabled_scopes_for_source(
            scope_repository=scope_repository,
            workspace_id=source.workspace_id,
            source_id=source.source_id,
        )
        if not enabled_scopes:
            skipped_no_scopes_count += 1
            continue
        active = await crawl_run_repository.get_active_for_source(
            source.workspace_id,
            source.source_id,
        )
        if active is not None:
            skipped_active_count += 1
            continue
        latest = await crawl_run_repository.get_latest_for_source(
            source.workspace_id,
            source.source_id,
        )
        if latest is not None and _latest_attempt_at(latest) > now - timedelta(
            minutes=source.crawl_frequency_minutes,
        ):
            skipped_not_due_count += 1
            continue
        request = await request_listing_source_crawl(
            workspace_id=source.workspace_id,
            source_id=source.source_id,
            source_repository=source_repository,
            scope_repository=scope_repository,
            crawl_run_repository=crawl_run_repository,
            event_bus=event_bus,
            now=now,
        )
        if request.status == RequestListingSourceCrawlStatus.REQUESTED:
            requested_count += 1

    return EnqueueDueListingSourceCrawlsResult(
        scanned_count=len(sources),
        requested_count=requested_count,
        skipped_active_count=skipped_active_count,
        skipped_not_due_count=skipped_not_due_count,
        skipped_not_ready_count=skipped_not_ready_count,
        skipped_no_scopes_count=skipped_no_scopes_count,
        skipped_unsupported_count=skipped_unsupported_count,
    )


async def execute_queued_listing_source_crawl(
    *,
    workspace_id: UUID,
    crawl_run_id: UUID,
    source_repository: ListingSourceRepository,
    scope_repository: ListingSearchScopeRepository,
    crawl_run_repository: ListingCrawlRunRepository,
    snapshot_repository: ListingSnapshotRepository,
    listing_search_client: ListingSearchClient,
    now: datetime,
    cache_ttl: timedelta,
    event_bus: EventBus | None = None,
) -> ExecuteQueuedListingSourceCrawlResult:
    claimed = await crawl_run_repository.claim_pending_by_id(
        workspace_id,
        crawl_run_id,
        now=now,
    )
    if claimed is None:
        return ExecuteQueuedListingSourceCrawlResult(
            status=ExecuteQueuedListingSourceCrawlStatus.NOT_CLAIMED,
            crawl_run=None,
        )

    source = await source_repository.get_by_id(workspace_id, claimed.source_id)
    enabled_scopes = await _enabled_scopes_for_source(
        scope_repository=scope_repository,
        workspace_id=workspace_id,
        source_id=claimed.source_id,
    )
    if (
        source is None
        or not source.enabled
        or not _source_ready_for_crawl(source)
        or not _source_supported_by_search_client(source)
        or not enabled_scopes
    ):
        failed = await crawl_run_repository.save(
            replace(
                claimed,
                status=ListingCrawlStatus.FAILED,
                finished_at=now,
                updated_at=now,
                error_summary=_execution_rejection_reason(
                    source=source,
                    enabled_scopes=enabled_scopes,
                ),
            )
        )
        return ExecuteQueuedListingSourceCrawlResult(
            status=ExecuteQueuedListingSourceCrawlStatus.FAILED,
            crawl_run=failed,
        )

    discovered_count = 0
    fetched_count = 0
    parsed_count = 0
    inserted_count = 0
    unchanged_count = 0
    failed_count = 0
    errors: list[str] = []

    for scope in enabled_scopes:
        try:
            results = await listing_search_client.search(
                source=source,
                query=_query_from_scope(scope),
            )
        except Exception as exc:
            failed_count += 1
            errors.append(f"scope {scope.scope_id}: {str(exc) or exc.__class__.__name__}")
            continue

        discovered_count += len(results)
        fetched_count += len(results)
        parsed_count += len(results)

        for snapshot in results:
            persisted, changed = await _persist_snapshot(
                snapshot=snapshot,
                crawl_run_id=claimed.crawl_run_id,
                source=source,
                snapshot_repository=snapshot_repository,
                now=now,
                cache_ttl=cache_ttl,
            )
            if changed:
                inserted_count += 1
                if event_bus is not None:
                    await _publish_snapshot_created_event(
                        event_bus=event_bus,
                        snapshot=persisted,
                        crawl_run_id=claimed.crawl_run_id,
                        now=now,
                    )
            else:
                unchanged_count += 1

    status = _final_status(parsed_count=parsed_count, inserted_count=inserted_count, errors=errors)
    completed = await crawl_run_repository.save(
        replace(
            claimed,
            status=status,
            finished_at=now,
            discovered_count=discovered_count,
            fetched_count=fetched_count,
            parsed_count=parsed_count,
            inserted_count=inserted_count,
            unchanged_count=unchanged_count,
            failed_count=failed_count,
            error_summary="; ".join(errors)[:1000] or None,
            updated_at=now,
        )
    )
    return ExecuteQueuedListingSourceCrawlResult(
        status=ExecuteQueuedListingSourceCrawlStatus(completed.status.value),
        crawl_run=completed,
    )


def _source_ready_for_crawl(source: ListingSource) -> bool:
    return source.terms_reviewed_at is not None and bool((source.data_use_policy or "").strip())


def _source_supported_by_search_client(source: ListingSource) -> bool:
    if source.requires_auth:
        return False
    hostname = urlparse(source.base_url).hostname or ""
    return hostname == STREETEASY_HOST or hostname.endswith(f".{STREETEASY_HOST}")


def _latest_attempt_at(crawl_run: ListingCrawlRun) -> datetime:
    return crawl_run.finished_at or crawl_run.updated_at or crawl_run.started_at


async def _enabled_scopes_for_source(
    *,
    scope_repository: ListingSearchScopeRepository,
    workspace_id: UUID,
    source_id: UUID,
) -> tuple[ListingSearchScope, ...]:
    scopes = await scope_repository.list_for_source(workspace_id, source_id)
    return tuple(scope for scope in scopes if scope.enabled)


def _query_from_scope(scope: ListingSearchScope) -> ListingSearchQuery:
    return ListingSearchQuery(
        search_type=ListingSearchType(scope.search_type.value),
        locations=scope.locations,
        addresses=scope.addresses,
        keywords=scope.keywords,
        min_price=scope.min_price,
        max_price=scope.max_price,
        min_beds=scope.min_beds,
        limit=scope.limit,
    )


async def _persist_snapshot(
    *,
    snapshot: CanonicalListingSnapshot,
    crawl_run_id: UUID,
    source: ListingSource,
    snapshot_repository: ListingSnapshotRepository,
    now: datetime,
    cache_ttl: timedelta,
) -> tuple[CanonicalListingSnapshot, bool]:
    current = await snapshot_repository.get_current_by_external_id(
        source.workspace_id,
        source.source_id,
        snapshot.external_listing_id,
    )
    changed = current is None or current.source_payload_hash != snapshot.source_payload_hash
    persisted = await snapshot_repository.save(
        replace(
            snapshot,
            snapshot_id=uuid4(),
            workspace_id=source.workspace_id,
            source_id=source.source_id,
            crawl_run_id=crawl_run_id,
            scraped_at=now,
            created_at=now,
            updated_at=now,
            valid_until=now + cache_ttl,
        )
    )
    if changed:
        await snapshot_repository.mark_other_versions_not_current(
            source.workspace_id,
            source.source_id,
            persisted.external_listing_id,
            persisted.snapshot_id,
        )
    return persisted, changed


async def _publish_snapshot_created_event(
    *,
    event_bus: EventBus,
    snapshot: CanonicalListingSnapshot,
    crawl_run_id: UUID,
    now: datetime,
) -> None:
    await event_bus.publish(
        DomainEvent(
            workspace_id=snapshot.workspace_id,
            aggregate_type=AggregateType.LISTING_SOURCE,
            aggregate_id=snapshot.source_id,
            event_type=DomainEventType.LISTING_SNAPSHOT_CREATED,
            payload={
                "crawl_run_id": str(crawl_run_id),
                "source_id": str(snapshot.source_id),
                "snapshot_id": str(snapshot.snapshot_id),
                "external_listing_id": snapshot.external_listing_id,
                "occurred_at": now.isoformat(),
            },
        )
    )


def _final_status(
    *,
    parsed_count: int,
    inserted_count: int,
    errors: list[str],
) -> ListingCrawlStatus:
    if errors and parsed_count == 0 and inserted_count == 0:
        return ListingCrawlStatus.FAILED
    if errors:
        return ListingCrawlStatus.COMPLETED_WITH_ERRORS
    return ListingCrawlStatus.COMPLETED


def _execution_rejection_reason(
    *,
    source: ListingSource | None,
    enabled_scopes: tuple[ListingSearchScope, ...],
) -> str:
    if source is None:
        return "source not found"
    if not source.enabled:
        return "source disabled before crawl execution"
    if not _source_ready_for_crawl(source):
        return "source review or data-use policy missing"
    if not _source_supported_by_search_client(source):
        return "source is not supported by the configured listing search client"
    if not enabled_scopes:
        return "no enabled search scopes configured"
    return "crawl rejected"
