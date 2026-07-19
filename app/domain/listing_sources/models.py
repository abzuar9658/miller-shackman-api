from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.domain.common.ids import (
    ListingCrawlRunId,
    ListingSearchScopeId,
    ListingSnapshotId,
    ListingSourceId,
    UserId,
    WorkspaceId,
)


class ListingSourceType(StrEnum):
    WEBSITE = "website"
    FEED = "feed"
    MANUAL_UPLOAD = "manual_upload"
    API = "api"


class ListingCrawlStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class ListingSearchScopeType(StrEnum):
    SALE = "sale"
    RENT = "rent"


class ListingSnapshotStatus(StrEnum):
    ACTIVE = "active"
    UNKNOWN = "unknown"
    OFF_MARKET = "off_market"
    SOLD = "sold"
    RENTED = "rented"


@dataclass(frozen=True)
class ListingSource:
    source_id: ListingSourceId
    workspace_id: WorkspaceId
    name: str
    source_type: ListingSourceType
    base_url: str
    created_at: datetime
    updated_at: datetime
    allowed_url_patterns: tuple[str, ...] = ()
    disallowed_url_patterns: tuple[str, ...] = ()
    crawl_frequency_minutes: int = 1440
    enabled: bool = False
    requires_auth: bool = False
    terms_reviewed_at: datetime | None = None
    terms_reviewed_by_user_id: UserId | None = None
    data_use_policy: str | None = None


@dataclass(frozen=True)
class ListingCrawlRun:
    crawl_run_id: ListingCrawlRunId
    workspace_id: WorkspaceId
    source_id: ListingSourceId
    status: ListingCrawlStatus
    started_at: datetime
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    dry_run: bool = False
    discovered_count: int = 0
    fetched_count: int = 0
    parsed_count: int = 0
    inserted_count: int = 0
    unchanged_count: int = 0
    failed_count: int = 0
    error_summary: str | None = None


@dataclass(frozen=True)
class ListingSearchScope:
    scope_id: ListingSearchScopeId
    workspace_id: WorkspaceId
    source_id: ListingSourceId
    search_type: ListingSearchScopeType
    created_at: datetime
    updated_at: datetime
    locations: tuple[str, ...] = ()
    addresses: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    min_beds: Decimal | None = None
    limit: int = 25
    enabled: bool = True


@dataclass(frozen=True)
class CanonicalListingSnapshot:
    snapshot_id: ListingSnapshotId
    workspace_id: WorkspaceId
    source_id: ListingSourceId
    external_listing_id: str
    source_url: str
    source_payload_hash: str
    scraped_at: datetime
    created_at: datetime
    updated_at: datetime
    crawl_run_id: ListingCrawlRunId | None = None
    title: str | None = None
    address_text: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    neighborhood: str | None = None
    price: Decimal | None = None
    beds: Decimal | None = None
    baths: Decimal | None = None
    property_type: str | None = None
    status: ListingSnapshotStatus = ListingSnapshotStatus.UNKNOWN
    description: str | None = None
    image_urls: tuple[str, ...] = ()
    listed_at: datetime | None = None
    source_updated_at: datetime | None = None
    valid_until: datetime | None = None
    source_payload: dict[str, object] | None = None
    is_current: bool = True
