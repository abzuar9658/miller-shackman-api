from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common.ids import (
    ListingCrawlRunId,
    ListingSearchScopeId,
    ListingSnapshotId,
    ListingSourceId,
    WorkspaceId,
)
from app.domain.listing_sources import (
    CanonicalListingSnapshot,
    ListingCrawlRun,
    ListingCrawlStatus,
    ListingSearchScope,
    ListingSearchScopeType,
    ListingSnapshotStatus,
    ListingSource,
    ListingSourceType,
)
from app.infrastructure.persistence.postgres.models import (
    ListingCrawlRunModel,
    ListingSearchScopeModel,
    ListingSnapshotModel,
    ListingSourceModel,
)

_ACTIVE_CRAWL_RUN_STATUSES = (
    ListingCrawlStatus.PENDING.value,
    ListingCrawlStatus.RUNNING.value,
)


class PostgresListingSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        source_id: ListingSourceId,
    ) -> ListingSource | None:
        result = await self._session.execute(
            select(ListingSourceModel)
            .where(ListingSourceModel.workspace_id == workspace_id)
            .where(ListingSourceModel.source_id == source_id)
        )
        model = result.scalar_one_or_none()
        return _source_from_model(model) if model is not None else None

    async def get_by_name(self, workspace_id: WorkspaceId, name: str) -> ListingSource | None:
        result = await self._session.execute(
            select(ListingSourceModel)
            .where(ListingSourceModel.workspace_id == workspace_id)
            .where(ListingSourceModel.name == name)
        )
        model = result.scalar_one_or_none()
        return _source_from_model(model) if model is not None else None

    async def list_for_workspace(self, workspace_id: WorkspaceId) -> tuple[ListingSource, ...]:
        result = await self._session.execute(
            select(ListingSourceModel)
            .where(ListingSourceModel.workspace_id == workspace_id)
            .order_by(ListingSourceModel.created_at.desc(), ListingSourceModel.name.asc())
        )
        return tuple(_source_from_model(model) for model in result.scalars().all())

    async def list_enabled(self, *, limit: int = 100) -> tuple[ListingSource, ...]:
        result = await self._session.execute(
            select(ListingSourceModel)
            .where(ListingSourceModel.enabled.is_(True))
            .order_by(ListingSourceModel.updated_at.asc(), ListingSourceModel.source_id.asc())
            .limit(limit)
        )
        return tuple(_source_from_model(model) for model in result.scalars().all())

    async def save(self, source: ListingSource) -> ListingSource:
        values = _source_to_values(source)
        update_values = {key: value for key, value in values.items() if key != "source_id"}
        result = await self._session.execute(
            insert(ListingSourceModel)
            .values(**values)
            .on_conflict_do_update(index_elements=["source_id"], set_=update_values)
            .returning(ListingSourceModel)
        )
        return _source_from_model(result.scalar_one())


class PostgresListingSearchScopeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        scope_id: ListingSearchScopeId,
    ) -> ListingSearchScope | None:
        result = await self._session.execute(
            select(ListingSearchScopeModel)
            .where(ListingSearchScopeModel.workspace_id == workspace_id)
            .where(ListingSearchScopeModel.scope_id == scope_id)
        )
        model = result.scalar_one_or_none()
        return _scope_from_model(model) if model is not None else None

    async def list_for_source(
        self,
        workspace_id: WorkspaceId,
        source_id: ListingSourceId,
    ) -> tuple[ListingSearchScope, ...]:
        result = await self._session.execute(
            select(ListingSearchScopeModel)
            .where(ListingSearchScopeModel.workspace_id == workspace_id)
            .where(ListingSearchScopeModel.source_id == source_id)
            .order_by(
                ListingSearchScopeModel.created_at.asc(),
                ListingSearchScopeModel.scope_id.asc(),
            )
        )
        return tuple(_scope_from_model(model) for model in result.scalars().all())

    async def save(self, scope: ListingSearchScope) -> ListingSearchScope:
        values = _scope_to_values(scope)
        update_values = {key: value for key, value in values.items() if key != "scope_id"}
        result = await self._session.execute(
            insert(ListingSearchScopeModel)
            .values(**values)
            .on_conflict_do_update(index_elements=["scope_id"], set_=update_values)
            .returning(ListingSearchScopeModel)
        )
        return _scope_from_model(result.scalar_one())


class PostgresListingCrawlRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        crawl_run_id: ListingCrawlRunId,
    ) -> ListingCrawlRun | None:
        result = await self._session.execute(
            select(ListingCrawlRunModel)
            .where(ListingCrawlRunModel.workspace_id == workspace_id)
            .where(ListingCrawlRunModel.crawl_run_id == crawl_run_id)
        )
        model = result.scalar_one_or_none()
        return _crawl_run_from_model(model) if model is not None else None

    async def list_for_source(
        self,
        workspace_id: WorkspaceId,
        source_id: ListingSourceId,
        *,
        limit: int = 100,
    ) -> tuple[ListingCrawlRun, ...]:
        result = await self._session.execute(
            select(ListingCrawlRunModel)
            .where(ListingCrawlRunModel.workspace_id == workspace_id)
            .where(ListingCrawlRunModel.source_id == source_id)
            .order_by(ListingCrawlRunModel.started_at.desc())
            .limit(limit)
        )
        return tuple(_crawl_run_from_model(model) for model in result.scalars().all())

    async def get_latest_for_source(
        self,
        workspace_id: WorkspaceId,
        source_id: ListingSourceId,
    ) -> ListingCrawlRun | None:
        result = await self._session.execute(
            select(ListingCrawlRunModel)
            .where(ListingCrawlRunModel.workspace_id == workspace_id)
            .where(ListingCrawlRunModel.source_id == source_id)
            .order_by(
                ListingCrawlRunModel.started_at.desc(),
                ListingCrawlRunModel.crawl_run_id.desc(),
            )
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return _crawl_run_from_model(model) if model is not None else None

    async def get_active_for_source(
        self,
        workspace_id: WorkspaceId,
        source_id: ListingSourceId,
    ) -> ListingCrawlRun | None:
        result = await self._session.execute(
            select(ListingCrawlRunModel)
            .where(ListingCrawlRunModel.workspace_id == workspace_id)
            .where(ListingCrawlRunModel.source_id == source_id)
            .where(ListingCrawlRunModel.status.in_(_ACTIVE_CRAWL_RUN_STATUSES))
            .order_by(
                ListingCrawlRunModel.started_at.desc(),
                ListingCrawlRunModel.crawl_run_id.desc(),
            )
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return _crawl_run_from_model(model) if model is not None else None

    async def insert_pending_if_no_active(
        self,
        crawl_run: ListingCrawlRun,
    ) -> ListingCrawlRun | None:
        result = await self._session.execute(
            insert(ListingCrawlRunModel)
            .values(**_crawl_run_to_values(crawl_run))
            .on_conflict_do_nothing(
                index_elements=["workspace_id", "source_id"],
                index_where=ListingCrawlRunModel.status.in_(_ACTIVE_CRAWL_RUN_STATUSES),
            )
            .returning(ListingCrawlRunModel)
        )
        model = result.scalar_one_or_none()
        return _crawl_run_from_model(model) if model is not None else None

    async def claim_pending_by_id(
        self,
        workspace_id: WorkspaceId,
        crawl_run_id: ListingCrawlRunId,
        *,
        now: datetime,
    ) -> ListingCrawlRun | None:
        result = await self._session.execute(
            update(ListingCrawlRunModel)
            .where(ListingCrawlRunModel.workspace_id == workspace_id)
            .where(ListingCrawlRunModel.crawl_run_id == crawl_run_id)
            .where(ListingCrawlRunModel.status == ListingCrawlStatus.PENDING.value)
            .values(
                status=ListingCrawlStatus.RUNNING.value,
                started_at=now,
                updated_at=now,
                error_summary=None,
            )
            .returning(ListingCrawlRunModel)
        )
        model = result.scalar_one_or_none()
        return _crawl_run_from_model(model) if model is not None else None

    async def save(self, crawl_run: ListingCrawlRun) -> ListingCrawlRun:
        values = _crawl_run_to_values(crawl_run)
        update_values = {key: value for key, value in values.items() if key != "crawl_run_id"}
        result = await self._session.execute(
            insert(ListingCrawlRunModel)
            .values(**values)
            .on_conflict_do_update(index_elements=["crawl_run_id"], set_=update_values)
            .returning(ListingCrawlRunModel)
        )
        return _crawl_run_from_model(result.scalar_one())


class PostgresListingSnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        snapshot_id: ListingSnapshotId,
    ) -> CanonicalListingSnapshot | None:
        result = await self._session.execute(
            select(ListingSnapshotModel)
            .where(ListingSnapshotModel.workspace_id == workspace_id)
            .where(ListingSnapshotModel.snapshot_id == snapshot_id)
        )
        model = result.scalar_one_or_none()
        return _snapshot_from_model(model) if model is not None else None

    async def get_current_by_external_id(
        self,
        workspace_id: WorkspaceId,
        source_id: ListingSourceId,
        external_listing_id: str,
    ) -> CanonicalListingSnapshot | None:
        result = await self._session.execute(
            select(ListingSnapshotModel)
            .where(ListingSnapshotModel.workspace_id == workspace_id)
            .where(ListingSnapshotModel.source_id == source_id)
            .where(ListingSnapshotModel.external_listing_id == external_listing_id)
            .where(ListingSnapshotModel.is_current.is_(True))
            .order_by(ListingSnapshotModel.scraped_at.desc())
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return _snapshot_from_model(model) if model is not None else None

    async def list_current_for_source(
        self,
        workspace_id: WorkspaceId,
        source_id: ListingSourceId,
        *,
        limit: int = 100,
    ) -> tuple[CanonicalListingSnapshot, ...]:
        result = await self._session.execute(
            select(ListingSnapshotModel)
            .where(ListingSnapshotModel.workspace_id == workspace_id)
            .where(ListingSnapshotModel.source_id == source_id)
            .where(ListingSnapshotModel.is_current.is_(True))
            .order_by(
                ListingSnapshotModel.scraped_at.desc(),
                ListingSnapshotModel.snapshot_id.desc(),
            )
            .limit(limit)
        )
        return tuple(_snapshot_from_model(model) for model in result.scalars().all())

    async def save(self, snapshot: CanonicalListingSnapshot) -> CanonicalListingSnapshot:
        values = _snapshot_to_values(snapshot)
        update_values = {key: value for key, value in values.items() if key != "snapshot_id"}
        result = await self._session.execute(
            insert(ListingSnapshotModel)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_listing_snapshots_workspace_source_external_payload",
                set_=update_values,
            )
            .returning(ListingSnapshotModel)
        )
        return _snapshot_from_model(result.scalar_one())

    async def mark_other_versions_not_current(
        self,
        workspace_id: WorkspaceId,
        source_id: ListingSourceId,
        external_listing_id: str,
        except_snapshot_id: ListingSnapshotId,
    ) -> None:
        await self._session.execute(
            update(ListingSnapshotModel)
            .where(ListingSnapshotModel.workspace_id == workspace_id)
            .where(ListingSnapshotModel.source_id == source_id)
            .where(ListingSnapshotModel.external_listing_id == external_listing_id)
            .where(ListingSnapshotModel.snapshot_id != except_snapshot_id)
            .values(is_current=False)
        )


def _source_from_model(model: ListingSourceModel) -> ListingSource:
    return ListingSource(
        source_id=model.source_id,
        workspace_id=model.workspace_id,
        name=model.name,
        source_type=ListingSourceType(model.source_type),
        base_url=model.base_url,
        allowed_url_patterns=tuple(model.allowed_url_patterns),
        disallowed_url_patterns=tuple(model.disallowed_url_patterns),
        crawl_frequency_minutes=model.crawl_frequency_minutes,
        enabled=model.enabled,
        requires_auth=model.requires_auth,
        terms_reviewed_at=model.terms_reviewed_at,
        terms_reviewed_by_user_id=model.terms_reviewed_by_user_id,
        data_use_policy=model.data_use_policy,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _source_to_values(source: ListingSource) -> dict[str, object]:
    return {
        "source_id": source.source_id,
        "workspace_id": source.workspace_id,
        "name": source.name,
        "source_type": source.source_type.value,
        "base_url": source.base_url,
        "allowed_url_patterns": list(source.allowed_url_patterns),
        "disallowed_url_patterns": list(source.disallowed_url_patterns),
        "crawl_frequency_minutes": source.crawl_frequency_minutes,
        "enabled": source.enabled,
        "requires_auth": source.requires_auth,
        "terms_reviewed_at": source.terms_reviewed_at,
        "terms_reviewed_by_user_id": source.terms_reviewed_by_user_id,
        "data_use_policy": source.data_use_policy,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
    }


def _scope_from_model(model: ListingSearchScopeModel) -> ListingSearchScope:
    return ListingSearchScope(
        scope_id=model.scope_id,
        workspace_id=model.workspace_id,
        source_id=model.source_id,
        search_type=ListingSearchScopeType(model.search_type),
        locations=tuple(model.locations),
        addresses=tuple(model.addresses),
        keywords=tuple(model.keywords),
        min_price=model.min_price,
        max_price=model.max_price,
        min_beds=model.min_beds,
        limit=model.limit,
        enabled=model.enabled,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _scope_to_values(scope: ListingSearchScope) -> dict[str, object]:
    return {
        "scope_id": scope.scope_id,
        "workspace_id": scope.workspace_id,
        "source_id": scope.source_id,
        "search_type": scope.search_type.value,
        "locations": list(scope.locations),
        "addresses": list(scope.addresses),
        "keywords": list(scope.keywords),
        "min_price": scope.min_price,
        "max_price": scope.max_price,
        "min_beds": scope.min_beds,
        "limit": scope.limit,
        "enabled": scope.enabled,
        "created_at": scope.created_at,
        "updated_at": scope.updated_at,
    }


def _crawl_run_from_model(model: ListingCrawlRunModel) -> ListingCrawlRun:
    return ListingCrawlRun(
        crawl_run_id=model.crawl_run_id,
        workspace_id=model.workspace_id,
        source_id=model.source_id,
        status=ListingCrawlStatus(model.status),
        dry_run=model.dry_run,
        started_at=model.started_at,
        finished_at=model.finished_at,
        discovered_count=model.discovered_count,
        fetched_count=model.fetched_count,
        parsed_count=model.parsed_count,
        inserted_count=model.inserted_count,
        unchanged_count=model.unchanged_count,
        failed_count=model.failed_count,
        error_summary=model.error_summary,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _crawl_run_to_values(crawl_run: ListingCrawlRun) -> dict[str, object]:
    return {
        "crawl_run_id": crawl_run.crawl_run_id,
        "workspace_id": crawl_run.workspace_id,
        "source_id": crawl_run.source_id,
        "status": crawl_run.status.value,
        "dry_run": crawl_run.dry_run,
        "started_at": crawl_run.started_at,
        "finished_at": crawl_run.finished_at,
        "discovered_count": crawl_run.discovered_count,
        "fetched_count": crawl_run.fetched_count,
        "parsed_count": crawl_run.parsed_count,
        "inserted_count": crawl_run.inserted_count,
        "unchanged_count": crawl_run.unchanged_count,
        "failed_count": crawl_run.failed_count,
        "error_summary": crawl_run.error_summary,
        "created_at": crawl_run.created_at,
        "updated_at": crawl_run.updated_at,
    }


def _snapshot_from_model(model: ListingSnapshotModel) -> CanonicalListingSnapshot:
    return CanonicalListingSnapshot(
        snapshot_id=model.snapshot_id,
        workspace_id=model.workspace_id,
        source_id=model.source_id,
        crawl_run_id=model.crawl_run_id,
        external_listing_id=model.external_listing_id,
        source_url=model.source_url,
        title=model.title,
        address_text=model.address_text,
        city=model.city,
        state=model.state,
        postal_code=model.postal_code,
        neighborhood=model.neighborhood,
        price=model.price,
        beds=model.beds,
        baths=model.baths,
        property_type=model.property_type,
        status=ListingSnapshotStatus(model.status),
        description=model.description,
        image_urls=tuple(model.image_urls),
        listed_at=model.listed_at,
        source_updated_at=model.source_updated_at,
        scraped_at=model.scraped_at,
        valid_until=model.valid_until,
        source_payload_hash=model.source_payload_hash,
        source_payload=model.source_payload,
        is_current=model.is_current,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _snapshot_to_values(snapshot: CanonicalListingSnapshot) -> dict[str, object]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "workspace_id": snapshot.workspace_id,
        "source_id": snapshot.source_id,
        "crawl_run_id": snapshot.crawl_run_id,
        "external_listing_id": snapshot.external_listing_id,
        "source_url": snapshot.source_url,
        "title": snapshot.title,
        "address_text": snapshot.address_text,
        "city": snapshot.city,
        "state": snapshot.state,
        "postal_code": snapshot.postal_code,
        "neighborhood": snapshot.neighborhood,
        "price": snapshot.price,
        "beds": snapshot.beds,
        "baths": snapshot.baths,
        "property_type": snapshot.property_type,
        "status": snapshot.status.value,
        "description": snapshot.description,
        "image_urls": list(snapshot.image_urls),
        "listed_at": snapshot.listed_at,
        "source_updated_at": snapshot.source_updated_at,
        "scraped_at": snapshot.scraped_at,
        "valid_until": snapshot.valid_until,
        "source_payload_hash": snapshot.source_payload_hash,
        "source_payload": snapshot.source_payload,
        "is_current": snapshot.is_current,
        "created_at": snapshot.created_at,
        "updated_at": snapshot.updated_at,
    }