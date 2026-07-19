from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field

from app.domain.listing_sources import ListingSearchScopeType, ListingSourceType


class ListingSourceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_type: ListingSourceType
    base_url: AnyHttpUrl
    allowed_url_patterns: list[str] = Field(default_factory=list)
    disallowed_url_patterns: list[str] = Field(default_factory=list)
    crawl_frequency_minutes: int = Field(default=1440, ge=1)
    enabled: bool = False
    requires_auth: bool = False
    terms_reviewed_at: datetime | None = None
    terms_reviewed_by_user_id: UUID | None = None
    data_use_policy: str | None = None


class UpdateListingSourceRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    source_type: ListingSourceType | None = None
    base_url: AnyHttpUrl | None = None
    allowed_url_patterns: list[str] | None = None
    disallowed_url_patterns: list[str] | None = None
    crawl_frequency_minutes: int | None = Field(default=None, ge=1)
    enabled: bool | None = None
    requires_auth: bool | None = None
    terms_reviewed_at: datetime | None = None
    terms_reviewed_by_user_id: UUID | None = None
    data_use_policy: str | None = None


class ListingSearchScopeRequest(BaseModel):
    search_type: ListingSearchScopeType
    locations: list[str] = Field(default_factory=list)
    addresses: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    min_beds: Decimal | None = Field(default=None, ge=0)
    limit: int = Field(default=25, ge=1, le=100)
    enabled: bool = True


class UpdateListingSearchScopeRequest(BaseModel):
    search_type: ListingSearchScopeType | None = None
    locations: list[str] | None = None
    addresses: list[str] | None = None
    keywords: list[str] | None = None
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    min_beds: Decimal | None = Field(default=None, ge=0)
    limit: int | None = Field(default=None, ge=1, le=100)
    enabled: bool | None = None


class ListingCrawlRunResponse(BaseModel):
    crawl_run_id: UUID
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    inserted_count: int
    unchanged_count: int
    failed_count: int
    error_summary: str | None = None


class ListingSearchScopeResponse(BaseModel):
    scope_id: UUID
    workspace_id: UUID
    source_id: UUID
    search_type: str
    locations: list[str]
    addresses: list[str]
    keywords: list[str]
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    min_beds: Decimal | None = None
    limit: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ListingSourceResponse(BaseModel):
    source_id: UUID
    workspace_id: UUID
    name: str
    source_type: str
    base_url: str
    allowed_url_patterns: list[str]
    disallowed_url_patterns: list[str]
    crawl_frequency_minutes: int
    enabled: bool
    requires_auth: bool
    terms_reviewed_at: datetime | None = None
    terms_reviewed_by_user_id: UUID | None = None
    data_use_policy: str | None = None
    created_at: datetime
    updated_at: datetime
    scopes: list[ListingSearchScopeResponse] = Field(default_factory=list)
    latest_crawl_run: ListingCrawlRunResponse | None = None
    recent_crawl_runs: list[ListingCrawlRunResponse] = Field(default_factory=list)
    next_due_at: datetime | None = None


class ListingSourceResultResponse(BaseModel):
    status: str
    source: ListingSourceResponse | None = None


class ListingSourceListResponse(BaseModel):
    status: str
    sources: list[ListingSourceResponse]


class ListingSourceCrawlRequestResponse(BaseModel):
    status: str
    crawl_run: ListingCrawlRunResponse | None = None


class ListingSearchScopeResultResponse(BaseModel):
    status: str
    scope: ListingSearchScopeResponse | None = None


class ListingSearchScopeListResponse(BaseModel):
    status: str
    scopes: list[ListingSearchScopeResponse]