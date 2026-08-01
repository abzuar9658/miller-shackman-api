from datetime import datetime
from typing import Protocol

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
    ListingSearchScope,
    ListingSource,
)


class ListingSourceRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        source_id: ListingSourceId,
    ) -> ListingSource | None:
        raise NotImplementedError

    async def get_by_name(self, workspace_id: WorkspaceId, name: str) -> ListingSource | None:
        raise NotImplementedError

    async def list_for_workspace(self, workspace_id: WorkspaceId) -> tuple[ListingSource, ...]:
        raise NotImplementedError

    async def list_enabled(self, *, limit: int = 100) -> tuple[ListingSource, ...]:
        raise NotImplementedError

    async def save(self, source: ListingSource) -> ListingSource:
        raise NotImplementedError


class ListingSearchScopeRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        scope_id: ListingSearchScopeId,
    ) -> ListingSearchScope | None:
        raise NotImplementedError

    async def list_for_source(
        self,
        workspace_id: WorkspaceId,
        source_id: ListingSourceId,
    ) -> tuple[ListingSearchScope, ...]:
        raise NotImplementedError

    async def save(self, scope: ListingSearchScope) -> ListingSearchScope:
        raise NotImplementedError


class ListingCrawlRunRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        crawl_run_id: ListingCrawlRunId,
    ) -> ListingCrawlRun | None:
        raise NotImplementedError

    async def list_for_source(
        self,
        workspace_id: WorkspaceId,
        source_id: ListingSourceId,
        *,
        limit: int = 100,
    ) -> tuple[ListingCrawlRun, ...]:
        raise NotImplementedError

    async def get_latest_for_source(
        self,
        workspace_id: WorkspaceId,
        source_id: ListingSourceId,
    ) -> ListingCrawlRun | None:
        raise NotImplementedError

    async def get_active_for_source(
        self,
        workspace_id: WorkspaceId,
        source_id: ListingSourceId,
    ) -> ListingCrawlRun | None:
        raise NotImplementedError

    async def insert_pending_if_no_active(
        self,
        crawl_run: ListingCrawlRun,
    ) -> ListingCrawlRun | None:
        raise NotImplementedError

    async def claim_pending_by_id(
        self,
        workspace_id: WorkspaceId,
        crawl_run_id: ListingCrawlRunId,
        *,
        now: datetime,
    ) -> ListingCrawlRun | None:
        raise NotImplementedError

    async def save(self, crawl_run: ListingCrawlRun) -> ListingCrawlRun:
        raise NotImplementedError


class ListingSnapshotRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        snapshot_id: ListingSnapshotId,
    ) -> CanonicalListingSnapshot | None:
        raise NotImplementedError

    async def get_current_by_external_id(
        self,
        workspace_id: WorkspaceId,
        source_id: ListingSourceId,
        external_listing_id: str,
    ) -> CanonicalListingSnapshot | None:
        raise NotImplementedError

    async def list_current_for_source(
        self,
        workspace_id: WorkspaceId,
        source_id: ListingSourceId,
        *,
        limit: int = 100,
    ) -> tuple[CanonicalListingSnapshot, ...]:
        raise NotImplementedError

    async def save(self, snapshot: CanonicalListingSnapshot) -> CanonicalListingSnapshot:
        raise NotImplementedError

    async def mark_other_versions_not_current(
        self,
        workspace_id: WorkspaceId,
        source_id: ListingSourceId,
        external_listing_id: str,
        except_snapshot_id: ListingSnapshotId,
    ) -> None:
        raise NotImplementedError
