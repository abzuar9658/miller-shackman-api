from datetime import time
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.domain.compliance import SmsComplianceState
from app.domain.identity import UserStatus, WorkspaceMembershipRole, WorkspaceMembershipStatus
from app.domain.outbound_drafting import (
    DEFAULT_EMAIL_PROMPT_TEXT,
    DEFAULT_EMAIL_SUBJECT_TEMPLATE,
    DEFAULT_SMS_PROMPT_TEXT,
    SUPPORTED_QUERY_EXTRACTION_FIELDS,
    normalize_config_prompt_text,
    normalize_email_subject_template,
    normalize_email_template,
    normalize_outbound_prompt_text,
    normalize_sms_template,
)
from app.domain.workspace_automation import WorkspaceAutomationStatus
from app.interfaces.api.schemas.auth import (
    MembershipResponse,
    UserResponse,
    WorkspaceResponse,
)


class CreateWorkspaceRequest(BaseModel):
    name: str
    default_timezone: str


class CreateWorkspaceResponse(BaseModel):
    status: str
    workspace: WorkspaceResponse | None = None
    membership: MembershipResponse | None = None


class WorkspaceUserResponse(BaseModel):
    user: UserResponse
    membership: MembershipResponse
    invitation_id: UUID | None = None


class ListWorkspaceUsersResponse(BaseModel):
    status: str
    users: list[WorkspaceUserResponse]


class InviteWorkspaceUserRequest(BaseModel):
    email: EmailStr
    role: WorkspaceMembershipRole
    full_name: str


class InviteWorkspaceUserResponse(BaseModel):
    status: str
    user: UserResponse | None = None
    membership: MembershipResponse | None = None


class ResendInvitationResponse(BaseModel):
    status: str
    invitation_id: UUID | None = None


class UpdateWorkspaceMembershipRequest(BaseModel):
    role: WorkspaceMembershipRole | None = None
    membership_status: WorkspaceMembershipStatus | None = None


class UpdateWorkspaceMembershipResponse(BaseModel):
    status: str
    membership: MembershipResponse | None = None


class UpdateUserStatusRequest(BaseModel):
    user_status: UserStatus


class UpdateUserStatusResponse(BaseModel):
    status: str
    user: UserResponse | None = None


class WorkspaceContactPolicyResponse(BaseModel):
    workspace_id: UUID
    sms_compliance_state: str
    quiet_hours_enabled: bool = True
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    inbound_email_address: str | None = None


class WorkspaceHandoffConfigResponse(BaseModel):
    workspace_id: UUID
    fallback_recipient_email: str | None = None
    crm_handoff_tag: str | None = None
    crm_custom_fields: dict[str, str]


class WorkspaceCRMSyncConfigResponse(BaseModel):
    workspace_id: UUID
    crm_sync_enabled: bool
    crm_sync_interval_seconds: int


class WorkspaceLLMConfigResponse(BaseModel):
    workspace_id: UUID
    openrouter_model: str
    allowed_openrouter_models: list[str]


class WorkspaceOperationalControlResponse(BaseModel):
    workspace_id: UUID
    automation_status: str
    pause_reason: str | None = None


class WorkspaceOutboundDraftingConfigResponse(BaseModel):
    workspace_id: UUID
    revision: int
    prompt_text: str
    sms_prompt_text: str
    sms_template: str
    email_prompt_text: str
    email_template: str
    email_subject_template: str
    enabled_extraction_fields: list[str]
    supported_extraction_fields: list[str]
    supported_template_placeholders: list[str]


class WorkspaceSettingsResponse(BaseModel):
    status: str
    workspace: WorkspaceResponse | None = None
    contact_policy: WorkspaceContactPolicyResponse | None = None
    crm_sync_config: WorkspaceCRMSyncConfigResponse | None = None
    llm_config: WorkspaceLLMConfigResponse | None = None
    handoff_config: WorkspaceHandoffConfigResponse | None = None
    outbound_drafting_config: WorkspaceOutboundDraftingConfigResponse | None = None
    operational_control: WorkspaceOperationalControlResponse | None = None


class UpdateWorkspaceContactPolicyRequest(BaseModel):
    sms_compliance_state: SmsComplianceState
    quiet_hours_enabled: bool = True
    quiet_hours_start: time
    quiet_hours_end: time
    inbound_email_address: EmailStr | None = None

    @field_validator("quiet_hours_end")
    @classmethod
    def quiet_hours_end_must_be_after_start(cls, value: time, info: object) -> time:
        data = getattr(info, "data", {})
        start = data.get("quiet_hours_start")
        if isinstance(start, time) and value <= start:
            raise ValueError("quiet_hours_end must be after quiet_hours_start")
        return value


class UpdateWorkspaceContactPolicyResponse(BaseModel):
    status: str
    contact_policy: WorkspaceContactPolicyResponse | None = None


class UpdateWorkspaceHandoffConfigRequest(BaseModel):
    fallback_recipient_email: EmailStr | None = None
    crm_handoff_tag: str | None = Field(default=None, max_length=255)
    crm_custom_fields: dict[str, str] = Field(default_factory=dict)


class UpdateWorkspaceHandoffConfigResponse(BaseModel):
    status: str
    handoff_config: WorkspaceHandoffConfigResponse | None = None


class UpdateWorkspaceCRMSyncConfigRequest(BaseModel):
    crm_sync_enabled: bool
    crm_sync_interval_seconds: int = Field(ge=60, le=86400)

    @field_validator("crm_sync_interval_seconds")
    @classmethod
    def interval_must_be_whole_minutes(cls, value: int) -> int:
        if value % 60 != 0:
            raise ValueError("crm_sync_interval_seconds must be a whole number of minutes")
        return value


class UpdateWorkspaceCRMSyncConfigResponse(BaseModel):
    status: str
    crm_sync_config: WorkspaceCRMSyncConfigResponse | None = None


class UpdateWorkspaceLLMConfigRequest(BaseModel):
    openrouter_model: str = Field(min_length=1, max_length=255)


class UpdateWorkspaceLLMConfigResponse(BaseModel):
    status: str
    llm_config: WorkspaceLLMConfigResponse | None = None


class UpdateWorkspaceOperationalControlRequest(BaseModel):
    automation_status: WorkspaceAutomationStatus
    pause_reason: str | None = Field(default=None, max_length=1000)


class UpdateWorkspaceOperationalControlResponse(BaseModel):
    status: str
    operational_control: WorkspaceOperationalControlResponse | None = None


class UpdateWorkspaceOutboundDraftingConfigRequest(BaseModel):
    prompt_text: str = Field(min_length=1, max_length=12000)
    sms_prompt_text: str = Field(min_length=1, max_length=12000)
    sms_template: str = Field(min_length=1, max_length=4000)
    email_prompt_text: str = Field(min_length=1, max_length=12000)
    email_template: str = Field(min_length=1, max_length=8000)
    email_subject_template: str = Field(
        default=DEFAULT_EMAIL_SUBJECT_TEMPLATE,
        max_length=255,
    )
    enabled_extraction_fields: list[str] = Field(
        default_factory=lambda: list(SUPPORTED_QUERY_EXTRACTION_FIELDS)
    )

    @field_validator("enabled_extraction_fields")
    @classmethod
    def enabled_extraction_fields_must_be_supported(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in value:
            field_name = raw.strip().lower()
            if field_name not in SUPPORTED_QUERY_EXTRACTION_FIELDS:
                raise ValueError("enabled_extraction_fields contains an unsupported field")
            if field_name not in normalized:
                normalized.append(field_name)
        return normalized

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
        return normalize_outbound_prompt_text(
            value,
            default_text=DEFAULT_SMS_PROMPT_TEXT,
        )

    @field_validator("email_prompt_text")
    @classmethod
    def normalize_email_prompt_text_value(cls, value: str) -> str:
        return normalize_outbound_prompt_text(
            value,
            default_text=DEFAULT_EMAIL_PROMPT_TEXT,
        )

    @field_validator("prompt_text")
    @classmethod
    def normalize_prompt_text_value(cls, value: str) -> str:
        return normalize_config_prompt_text(value)


class UpdateWorkspaceOutboundDraftingConfigResponse(BaseModel):
    status: str
    outbound_drafting_config: WorkspaceOutboundDraftingConfigResponse | None = None


class OutboundDraftPreviewResponse(BaseModel):
    status: str
    body: str | None = None
    subject: str | None = None
    prompt_version: str | None = None
    model: str | None = None


class WorkspaceOutboundDraftingPreviewRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    agent_name: str | None = Field(default=None, max_length=255)
    brokerage_name: str | None = Field(default=None, max_length=255)

    @field_validator("agent_name", "brokerage_name")
    @classmethod
    def normalize_preview_placeholder_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class WorkspaceOutboundDraftingPreviewResponse(BaseModel):
    status: str
    parsed_preferences: dict[str, str] = Field(default_factory=dict)
    listing_context_found: bool = False
    listing_relevance_brief: dict[str, Any] | None = None
    sms_preview: OutboundDraftPreviewResponse | None = None
    email_preview: OutboundDraftPreviewResponse | None = None


class UpdateWorkspaceTimezoneRequest(BaseModel):
    default_timezone: str = Field(min_length=1, max_length=100)

    @field_validator("default_timezone")
    @classmethod
    def default_timezone_must_be_valid(cls, value: str) -> str:
        normalized = value.strip()
        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("default_timezone must be a valid IANA timezone") from exc
        return normalized


class UpdateWorkspaceTimezoneResponse(BaseModel):
    status: str
    workspace: WorkspaceResponse | None = None
