from datetime import datetime, time
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.compliance.contactability import ContactChannel


class CampaignCadenceStepRequest(BaseModel):
    channel: ContactChannel
    delay_hours: int = Field(ge=0)
    message_goal: str = Field(min_length=1, max_length=500)
    template_key: str = Field(min_length=1, max_length=255)
    max_attempts: int = Field(ge=1)


class CampaignDraftRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    enabled_channels: list[ContactChannel] = Field(min_length=1)
    daily_start_cap: int = Field(gt=0)
    dormant_threshold_days: int = Field(gt=0)
    quiet_hours_start: time
    quiet_hours_end: time
    timezone: str = Field(min_length=1, max_length=100)
    sms_compliance_required: bool = True
    preflight_digest_enabled: bool = False
    prompt_version: str = Field(min_length=1, max_length=100)
    approved_model: str = Field(min_length=1, max_length=100)
    cadence_steps: list[CampaignCadenceStepRequest] = Field(min_length=1)

    @field_validator("quiet_hours_end")
    @classmethod
    def quiet_hours_end_must_be_after_start(cls, value: time, info: object) -> time:
        data = getattr(info, "data", {})
        start = data.get("quiet_hours_start")
        if isinstance(start, time) and value <= start:
            raise ValueError("quiet_hours_end must be after quiet_hours_start")
        return value


class PauseCampaignRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class CampaignResponse(BaseModel):
    campaign_id: UUID
    workspace_id: UUID
    name: str
    status: str
    active_version_id: UUID | None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class CampaignVersionResponse(BaseModel):
    campaign_version_id: UUID
    campaign_id: UUID
    workspace_id: UUID
    version_number: int
    status: str
    enabled_channels: list[str]
    daily_start_cap: int
    dormant_threshold_days: int
    quiet_hours_start: time
    quiet_hours_end: time
    timezone: str
    sms_compliance_required: bool
    preflight_digest_enabled: bool
    prompt_version: str
    approved_model: str
    created_by_user_id: UUID
    created_at: datetime
    published_at: datetime | None


class CampaignCadenceStepResponse(BaseModel):
    cadence_step_id: UUID
    campaign_version_id: UUID
    step_order: int
    channel: str
    delay_hours: int
    message_goal: str
    template_key: str
    max_attempts: int
    created_at: datetime


class CampaignAdminResponse(BaseModel):
    status: str
    campaign: CampaignResponse | None
    version: CampaignVersionResponse | None
    cadence_steps: list[CampaignCadenceStepResponse]
    reasons: list[str]


class CampaignSummaryResponse(BaseModel):
    campaign: CampaignResponse
    latest_version: CampaignVersionResponse
    cadence_step_count: int


class CampaignListResponse(BaseModel):
    status: str
    campaigns: list[CampaignSummaryResponse]


class CampaignDetailResponse(BaseModel):
    status: str
    campaign: CampaignResponse
    version: CampaignVersionResponse
    cadence_steps: list[CampaignCadenceStepResponse]


class RunDormantSelectorRequest(BaseModel):
    batch_id: str | None = Field(default=None, description="Optional batch idempotency key")


class RunDormantSelectorResponse(BaseModel):
    status: str
    workspace_id: UUID
    campaign_id: UUID
    batch_id: str
    digest_required: bool
    digest_id: str | None
    digest_status: str | None
    selected_count: int
    held_back_count: int
    started_count: int
    veto_window_expires_at: datetime | None
    reason: str | None


class RecordPreflightVetoRequest(BaseModel):
    lead_id: UUID
    reason: str | None = None


class RecordPreflightVetoResponse(BaseModel):
    status: str
    digest_id: str | None
    lead_id: UUID
    recorded: bool
    recorded_at: datetime | None
    actor_id: UUID
    duplicate: bool
    reasons: list[str]
