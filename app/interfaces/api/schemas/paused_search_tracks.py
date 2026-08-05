from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.domain.campaigns import (
    CampaignVersionStatus,
    PausedSearchFallbackTimingPolicy,
    PausedSearchTerminalBehavior,
    PausedSearchTimingBasis,
    PausedSearchTrackFamily,
    PausedSearchTrackStatus,
    PausedSearchTrackStepPhase,
    generate_paused_search_track_key,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import PausedSearchReasonCode
from app.interfaces.api.schemas.campaigns import DormantStepTemplateProfileSchema


class PausedSearchTrackStepRequest(BaseModel):
    phase: PausedSearchTrackStepPhase
    channel: ContactChannel
    delay_hours: int = Field(ge=0)
    message_goal: str = Field(min_length=1, max_length=500)
    template_key: str = Field(min_length=1, max_length=255)
    max_attempts: int = Field(ge=1)
    review_required: bool = False
    interval_days: int | None = Field(default=None, ge=14, le=365)
    max_occurrences: int = Field(default=1, ge=1)
    template_version_id: UUID | None = None
    timing_basis: PausedSearchTimingBasis = PausedSearchTimingBasis.CUSTOMER_REENGAGEMENT_DATE
    fallback_channel: ContactChannel | None = None
    template_profile: DormantStepTemplateProfileSchema | None = None


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
    default_pause_duration_days: int = Field(default=60, ge=30, le=730)
    max_duration_days: int = Field(default=365, ge=30, le=730)
    terminal_behavior: PausedSearchTerminalBehavior = (
        PausedSearchTerminalBehavior.COMPLETE_KEEP_PAUSED
    )
    steps: list[PausedSearchTrackStepRequest] = Field(min_length=1)


class PausedSearchTrackDraftRequest(PausedSearchTrackConfigRequest):
    track_key: str = Field(default="", max_length=255)
    display_name: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def populate_track_key(self) -> "PausedSearchTrackDraftRequest":
        if not self.track_key.strip():
            self.track_key = generate_paused_search_track_key(self.display_name)
        return self


class PausedSearchTrackDraftValidateRequest(PausedSearchTrackDraftRequest):
    pass


class PausedSearchTrackDraftPreviewRequest(PausedSearchTrackDraftRequest):
    as_of: datetime
    timezone: str = Field(min_length=1, max_length=64)
    reengagement_not_before: datetime | None = None


class PausedSearchTrackStepPreviewRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    channel: ContactChannel
    message_goal: str = Field(min_length=1, max_length=500)
    template_profile: DormantStepTemplateProfileSchema | None = None


class PausedSearchValidationFindingResponse(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    field: str
    detail: str


class PausedSearchTrackValidationResponse(BaseModel):
    publishable: bool
    errors: list[PausedSearchValidationFindingResponse]
    warnings: list[PausedSearchValidationFindingResponse]


class PausedSearchTrackDraftValidationResponse(BaseModel):
    status: str
    track_version_id: UUID
    validation: PausedSearchTrackValidationResponse


class PausedSearchTrackPreviewOccurrenceResponse(BaseModel):
    next_action_at: datetime | None
    due_at: datetime | None
    local_next_action_at: datetime | None
    phase: str | None
    step_id: UUID | None
    occurrence_number: int
    outcome: str
    reason_code: str
    reason_detail: str | None
    channel: str
    review_required: bool


class PausedSearchTrackPreviewResponse(BaseModel):
    status: str
    track_version_id: UUID
    preview_reference: str | None
    validation: PausedSearchTrackValidationResponse
    occurrences: list[PausedSearchTrackPreviewOccurrenceResponse]
    maximum_logical_touches: int
    expires_at: datetime | None
    local_expires_at: datetime | None


class PausedSearchTrackPublishRequest(BaseModel):
    draft_version_number: int = Field(ge=1)
    preview_reference: str = Field(min_length=1, max_length=128)
    confirm_warnings: bool = False


class PausedSearchTemplateResponse(BaseModel):
    template_version_id: UUID
    template_key: str
    version: int
    channel: str
    purpose: str
    content: str
    subject: str | None
    allowed_variables: list[str]
    permitted_use_tags: list[str]
    status: str


class PausedSearchTemplateListResponse(BaseModel):
    templates: list[PausedSearchTemplateResponse]


class PausedSearchCapabilityProfileResponse(BaseModel):
    profile_key: str
    profile_version: int
    reason_code: str
    min_recurring_interval_days: int
    max_recurring_interval_days: int
    max_total_touches: int
    max_duration_days: int
    required_safety_tags: list[str]
    restriction: str


class PausedSearchCapabilityProfileListResponse(BaseModel):
    profiles: list[PausedSearchCapabilityProfileResponse]


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
    default_pause_duration_days: int
    created_by_user_id: UUID
    created_at: datetime
    published_at: datetime | None
    max_duration_days: int
    terminal_behavior: PausedSearchTerminalBehavior


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
    interval_days: int | None
    max_occurrences: int
    template_version_id: UUID | None
    timing_basis: PausedSearchTimingBasis
    fallback_channel: ContactChannel | None
    template_profile: DormantStepTemplateProfileSchema | None


class PausedSearchReasonMappingResponse(BaseModel):
    mapping_id: UUID
    workspace_id: UUID
    reason_code: PausedSearchReasonCode
    track_id: UUID
    track_version_id: UUID
    created_by_user_id: UUID
    created_at: datetime


class PausedSearchTrackLeadAssignmentResponse(BaseModel):
    lead_id: UUID
    workflow_id: UUID | None
    track_version_id: UUID | None
    crm_lead_id: str
    primary_email: str | None
    lead_stage: str
    workflow_state: str | None


class PausedSearchTrackAdminResponse(BaseModel):
    status: str
    track: PausedSearchTrackResponse | None
    version: PausedSearchTrackVersionResponse | None
    steps: list[PausedSearchTrackStepResponse]
    reason_mappings: list[PausedSearchReasonMappingResponse]
    assigned_leads: list[PausedSearchTrackLeadAssignmentResponse]
    reasons: list[str]


class PausedSearchTrackSummaryResponse(BaseModel):
    track: PausedSearchTrackResponse
    version: PausedSearchTrackVersionResponse
    step_count: int
    reason_mappings: list[PausedSearchReasonMappingResponse]
    assigned_leads: list[PausedSearchTrackLeadAssignmentResponse]


class PausedSearchTrackListResponse(BaseModel):
    status: str
    tracks: list[PausedSearchTrackSummaryResponse]


class PausedSearchTrackDetailResponse(BaseModel):
    status: str
    track: PausedSearchTrackResponse
    version: PausedSearchTrackVersionResponse
    steps: list[PausedSearchTrackStepResponse]
    reason_mappings: list[PausedSearchReasonMappingResponse]
    assigned_leads: list[PausedSearchTrackLeadAssignmentResponse]


class UncertainOccurrenceResolutionRequest(BaseModel):
    resolution: Literal["sent", "failed", "skipped"]
    reason: str = Field(min_length=1, max_length=1000)


class UncertainOccurrenceResolutionResponse(BaseModel):
    status: str
    occurrence_id: UUID | None = None
    occurrence_status: str | None = None
    workflow_state: str | None = None
    reasons: list[str] = Field(default_factory=list)


class PausedSearchLeadSummaryResponse(BaseModel):
    lead_id: UUID
    display_name: str
    assigned_agent_user_id: UUID | None


class PausedSearchOccurrenceResponse(BaseModel):
    occurrence_id: UUID
    lead_id: UUID
    workflow_id: UUID
    track_version_id: UUID
    step_id: UUID
    phase: str
    occurrence_number: int
    scheduled_for: datetime
    due_at: datetime
    status: str
    logical_touch_count: int
    provider_message_id: str | None
    provider_delivery_status: str | None
    closed_at: datetime | None
    failure_reason: str | None
    lead: PausedSearchLeadSummaryResponse


class PausedSearchOccurrenceListResponse(BaseModel):
    status: str
    occurrences: list[PausedSearchOccurrenceResponse]
    reasons: list[str] = Field(default_factory=list)


class PausedSearchReviewResponse(BaseModel):
    review_id: UUID
    lead_id: UUID
    workflow_id: UUID
    occurrence_id: UUID | None
    kind: str
    status: str
    reason: str
    requested_at: datetime
    review_expiry_at: datetime | None
    reviewer_user_id: UUID | None
    acted_at: datetime | None
    action_reason: str | None
    outbound_message_id: UUID | None
    outbound_message_version: int | None
    message_channel: str | None
    message_subject: str | None
    message_body: str | None
    lead: PausedSearchLeadSummaryResponse


class PausedSearchReviewListResponse(BaseModel):
    status: str
    reviews: list[PausedSearchReviewResponse]
    reasons: list[str] = Field(default_factory=list)


class PausedSearchReviewActionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    idempotency_key: str = Field(min_length=1, max_length=255)


class PausedSearchMessageReviewEditRequest(PausedSearchReviewActionRequest):
    body: str = Field(min_length=1, max_length=4000)
    subject: str | None = Field(default=None, max_length=255)


class PausedSearchPolicyReviewResolveRequest(PausedSearchReviewActionRequest):
    resolution_action: Literal[
        "skip",
        "resume_after_revalidation",
        "migrate",
        "terminalize",
    ]
    target_track_version_id: UUID | None = None
    terminal_behavior: Literal[
        "complete_keep_paused",
        "pause_for_review",
        "close_automation",
    ] | None = None


class PausedSearchReviewActionResponse(BaseModel):
    status: str
    review: PausedSearchReviewResponse | None = None
    occurrence: PausedSearchOccurrenceResponse | None = None
    reasons: list[str] = Field(default_factory=list)
