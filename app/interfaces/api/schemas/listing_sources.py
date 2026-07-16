from datetime import datetime
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field

from app.domain.listing_sources import ListingSourceType


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


class ListingSourceResultResponse(BaseModel):
    status: str
    source: ListingSourceResponse | None = None


class ListingSourceListResponse(BaseModel):
    status: str
    sources: list[ListingSourceResponse]