from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.campaigns import (
    CampaignVersionStatus,
    PausedSearchFallbackTimingPolicy,
    PausedSearchTrackFamily,
    PausedSearchTrackStatus,
    PausedSearchTrackStepPhase,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import PausedSearchReasonCode


class PausedSearchTrackStepRequest(BaseModel):
    phase: PausedSearchTrackStepPhase
    channel: ContactChannel
    delay_hours: int = Field(ge=0)
    message_goal: str = Field(min_length=1, max_length=500)
    template_key: str = Field(min_length=1, max_length=255)
    max_attempts: int = Field(ge=1)
    review_required: bool = False


class PausedSearchTrackConfigRequest(BaseModel):
    track_family: PausedSearchTrackFamily
    enabled: bool
    allowed_channels: list[ContactChannel] = Field(min_length=1)
    default_for_reason_codes: list[PausedSearchReasonCode] = Field(default_factory=list)
    fallback_timing_policy: PausedSearchFallbackTimingPolicy
    maintenance_interval_days: int = Field(ge=1)
    reactivation_window_days: int = Field(ge=1)
    max_total_touches: int = Field(ge=1)
    requires_review_before_publish: bool = False
    steps: list[PausedSearchTrackStepRequest] = Field(min_length=1)


class PausedSearchTrackDraftRequest(PausedSearchTrackConfigRequest):
    track_key: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)


class PausedSearchTrackResponse(BaseModel):
    track_id: UUID
    workspace_id: UUID
    track_key: str
    display_name: str
    status: PausedSearchTrackStatus
    active_version_id: UUID | None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class PausedSearchTrackVersionResponse(BaseModel):
    track_version_id: UUID
    workspace_id: UUID
    track_id: UUID
    version_number: int
    status: CampaignVersionStatus
    track_family: PausedSearchTrackFamily
    enabled: bool
    allowed_channels: list[ContactChannel]
    default_for_reason_codes: list[PausedSearchReasonCode]
    fallback_timing_policy: PausedSearchFallbackTimingPolicy
    maintenance_interval_days: int
    reactivation_window_days: int
    max_total_touches: int
    requires_review_before_publish: bool
    created_by_user_id: UUID
    created_at: datetime
    published_at: datetime | None


class PausedSearchTrackStepResponse(BaseModel):
    step_id: UUID
    track_version_id: UUID
    step_order: int
    phase: PausedSearchTrackStepPhase
    channel: ContactChannel
    delay_hours: int
    message_goal: str
    template_key: str
    max_attempts: int
    review_required: bool
    created_at: datetime


class PausedSearchReasonMappingResponse(BaseModel):
    mapping_id: UUID
    workspace_id: UUID
    reason_code: PausedSearchReasonCode
    track_id: UUID
    track_version_id: UUID
    created_by_user_id: UUID
    created_at: datetime


class PausedSearchTrackAdminResponse(BaseModel):
    status: str
    track: PausedSearchTrackResponse | None
    version: PausedSearchTrackVersionResponse | None
    steps: list[PausedSearchTrackStepResponse]
    reason_mappings: list[PausedSearchReasonMappingResponse]
    reasons: list[str]


class PausedSearchTrackSummaryResponse(BaseModel):
    track: PausedSearchTrackResponse
    version: PausedSearchTrackVersionResponse
    step_count: int
    reason_mappings: list[PausedSearchReasonMappingResponse]


class PausedSearchTrackListResponse(BaseModel):
    status: str
    tracks: list[PausedSearchTrackSummaryResponse]


class PausedSearchTrackDetailResponse(BaseModel):
    status: str
    track: PausedSearchTrackResponse
    version: PausedSearchTrackVersionResponse
    steps: list[PausedSearchTrackStepResponse]
    reason_mappings: list[PausedSearchReasonMappingResponse]