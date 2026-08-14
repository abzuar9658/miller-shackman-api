from datetime import datetime, time
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.compliance.contactability import ContactChannel
from app.domain.outbound_drafting import (
    DEFAULT_EMAIL_PROMPT_TEXT,
    DEFAULT_EMAIL_SUBJECT_TEMPLATE,
    DEFAULT_EMAIL_TEMPLATE,
    DEFAULT_PROMPT_TEXT,
    DEFAULT_SMS_PROMPT_TEXT,
    DEFAULT_SMS_TEMPLATE,
    SUPPORTED_QUERY_EXTRACTION_FIELDS,
    DormantCallToAction,
    DormantGreeting,
    DormantListingContextBehavior,
    DormantMessageLength,
    DormantMessageStyle,
    DormantMessageTone,
    DormantPersonalizationField,
    DormantSignOff,
    normalize_config_prompt_text,
    normalize_email_subject_template,
    normalize_email_template,
    normalize_enabled_extraction_fields,
    normalize_outbound_prompt_text,
    normalize_sms_template,
)


class DormantStepTemplateProfileSchema(BaseModel):
    tone: DormantMessageTone = DormantMessageTone.WARM
    style: DormantMessageStyle = DormantMessageStyle.FRIENDLY_FOLLOW_UP
    length: DormantMessageLength = DormantMessageLength.SHORT
    call_to_action: DormantCallToAction = DormantCallToAction.INVITE_REPLY
    greeting: DormantGreeting = DormantGreeting.LEAD_FIRST_NAME
    sign_off: DormantSignOff = DormantSignOff.NONE
    listing_context: DormantListingContextBehavior = (
        DormantListingContextBehavior.WHEN_AVAILABLE
    )
    personalization_fields: list[DormantPersonalizationField] = Field(
        default_factory=lambda: [
            DormantPersonalizationField.LEAD_FIRST_NAME,
            DormantPersonalizationField.LOCATION,
            DormantPersonalizationField.RECENT_CONVERSATION,
            DormantPersonalizationField.APPROVED_LISTING_CONTEXT,
        ]
    )
    custom_instructions: str | None = Field(default=None, max_length=1000)


class CampaignCadenceStepRequest(BaseModel):
    channel: ContactChannel
    delay_hours: int = Field(ge=0)
    message_goal: str = Field(min_length=1, max_length=500)
    template_key: str = Field(min_length=1, max_length=255)
    max_attempts: int = Field(ge=1)
    template_profile: DormantStepTemplateProfileSchema | None = None


class CampaignConfigRequest(BaseModel):
    enabled_channels: list[ContactChannel] = Field(min_length=1)
    daily_start_cap: int = Field(gt=0)
    dormant_threshold_days: int = Field(gt=0)
    quiet_hours_start: time
    quiet_hours_end: time
    timezone: str = Field(min_length=1, max_length=100)
    preflight_digest_enabled: bool = False
    crm_enrollment_tag: str | None = Field(default=None, max_length=255)
    allow_assigned_agent_manual_enrollment: bool = True
    prompt_version: str = Field(min_length=1, max_length=100)
    approved_model: str = Field(min_length=1, max_length=100)
    cadence_steps: list[CampaignCadenceStepRequest] = Field(min_length=1)
    prompt_text: str = Field(default=DEFAULT_PROMPT_TEXT, min_length=1, max_length=12000)
    sms_prompt_text: str = Field(
        default=DEFAULT_SMS_PROMPT_TEXT,
        min_length=1,
        max_length=12000,
    )
    sms_template: str = Field(default=DEFAULT_SMS_TEMPLATE, min_length=1, max_length=4000)
    email_prompt_text: str = Field(
        default=DEFAULT_EMAIL_PROMPT_TEXT,
        min_length=1,
        max_length=12000,
    )
    email_template: str = Field(
        default=DEFAULT_EMAIL_TEMPLATE,
        min_length=1,
        max_length=8000,
    )
    email_subject_template: str = Field(
        default=DEFAULT_EMAIL_SUBJECT_TEMPLATE,
        max_length=255,
    )
    enabled_extraction_fields: list[str] = Field(
        default_factory=lambda: list(SUPPORTED_QUERY_EXTRACTION_FIELDS)
    )

    @field_validator("quiet_hours_end")
    @classmethod
    def quiet_hours_end_must_be_after_start(cls, value: time, info: object) -> time:
        data = getattr(info, "data", {})
        start = data.get("quiet_hours_start")
        if isinstance(start, time) and value <= start:
            raise ValueError("quiet_hours_end must be after quiet_hours_start")
        return value

    @field_validator("enabled_extraction_fields")
    @classmethod
    def enabled_extraction_fields_must_be_supported(cls, value: list[str]) -> list[str]:
        normalized = normalize_enabled_extraction_fields(value)
        if any(raw.strip().lower() not in SUPPORTED_QUERY_EXTRACTION_FIELDS for raw in value):
            raise ValueError("enabled_extraction_fields contains an unsupported field")
        return list(normalized)

    @field_validator("sms_template")
    @classmethod
    def normalize_sms_template_value(cls, value: str) -> str:
        return normalize_sms_template(value)

    @field_validator("email_template")
    @classmethod
    def normalize_email_template_value(cls, value: str) -> str:
        return normalize_email_template(value)

    @field_validator("email_subject_template")
    @classmethod
    def normalize_email_subject_template_value(cls, value: str) -> str:
        return normalize_email_subject_template(value)

    @field_validator("sms_prompt_text")
    @classmethod
    def normalize_sms_prompt_text_value(cls, value: str) -> str:
        return normalize_outbound_prompt_text(value, default_text=DEFAULT_SMS_PROMPT_TEXT)

    @field_validator("email_prompt_text")
    @classmethod
    def normalize_email_prompt_text_value(cls, value: str) -> str:
        return normalize_outbound_prompt_text(value, default_text=DEFAULT_EMAIL_PROMPT_TEXT)

    @field_validator("prompt_text")
    @classmethod
    def normalize_prompt_text_value(cls, value: str) -> str:
        return normalize_config_prompt_text(value)


class CampaignDraftRequest(CampaignConfigRequest):
    name: str = Field(min_length=1, max_length=255)


class NurtureSettingsDraftRequest(CampaignConfigRequest):
    pass


class NurtureSettingsPreviewRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    agent_name: str | None = Field(default=None, max_length=255)
    brokerage_name: str | None = Field(default=None, max_length=255)
    template_key: str | None = Field(default=None, max_length=255)
    draft: NurtureSettingsDraftRequest | None = None

    @field_validator("agent_name", "brokerage_name", "template_key")
    @classmethod
    def normalize_preview_placeholder_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PauseCampaignRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ResumeCampaignRequest(BaseModel):
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
    preflight_digest_enabled: bool
    crm_enrollment_tag: str | None
    allow_assigned_agent_manual_enrollment: bool
    prompt_version: str
    approved_model: str
    prompt_text: str
    sms_prompt_text: str
    sms_template: str
    email_prompt_text: str
    email_template: str
    email_subject_template: str
    enabled_extraction_fields: list[str]
    supported_extraction_fields: list[str]
    supported_template_placeholders: list[str]
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
    template_profile: DormantStepTemplateProfileSchema | None = None


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


class NurtureSettingsPolicyResponse(BaseModel):
    nurture_settings_id: UUID
    workspace_id: UUID
    name: str
    status: str
    active_settings_version_id: UUID | None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class NurtureSettingsConfigResponse(BaseModel):
    settings_version_id: UUID
    nurture_settings_id: UUID
    workspace_id: UUID
    revision: int
    status: str
    enabled_channels: list[str]
    daily_start_cap: int
    dormant_threshold_days: int
    quiet_hours_start: time
    quiet_hours_end: time
    timezone: str
    preflight_digest_enabled: bool
    crm_enrollment_tag: str | None
    allow_assigned_agent_manual_enrollment: bool
    prompt_version: str
    approved_model: str
    prompt_text: str
    sms_prompt_text: str
    sms_template: str
    email_prompt_text: str
    email_template: str
    email_subject_template: str
    enabled_extraction_fields: list[str]
    supported_extraction_fields: list[str]
    supported_template_placeholders: list[str]
    created_by_user_id: UUID
    created_at: datetime
    published_at: datetime | None


class NurtureCadenceStepResponse(BaseModel):
    step_id: UUID
    settings_version_id: UUID
    step_order: int
    channel: str
    delay_hours: int
    message_goal: str
    template_key: str
    max_attempts: int
    created_at: datetime
    template_profile: DormantStepTemplateProfileSchema | None = None


class NurtureSettingsAdminResponse(BaseModel):
    status: str
    nurture_settings: NurtureSettingsPolicyResponse | None
    settings: NurtureSettingsConfigResponse | None
    cadence: list[NurtureCadenceStepResponse]
    reasons: list[str]


class NurtureSettingsDetailResponse(BaseModel):
    status: str
    nurture_settings: NurtureSettingsPolicyResponse
    settings: NurtureSettingsConfigResponse
    cadence: list[NurtureCadenceStepResponse]


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
    paused_search_started_count: int
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
    actor_id: str
    duplicate: bool
    reasons: list[str]
