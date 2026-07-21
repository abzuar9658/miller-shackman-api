from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.interfaces.api.schemas.handoffs import HandoffResponse


class LeadChannelContactabilityResponse(BaseModel):
    channel: str
    contactable: bool


class LeadContactabilityResponse(BaseModel):
    sms: LeadChannelContactabilityResponse
    email: LeadChannelContactabilityResponse
    contactable_channels: list[str] = Field(default_factory=list)


class LeadChannelSendabilityResponse(BaseModel):
    channel: str
    sendable: bool
    reasons: list[str] = Field(default_factory=list)


class LeadSendabilityResponse(BaseModel):
    sms: LeadChannelSendabilityResponse
    email: LeadChannelSendabilityResponse
    sendable_channels: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)


class LeadResponse(BaseModel):
    lead_id: UUID
    crm_provider: str
    crm_lead_id: str
    display_name: str
    primary_email: str | None
    primary_phone: str | None
    lead_source: str
    lead_stage: str
    lead_type: str
    tags: list[str]
    has_accountable_owner: bool
    assigned_agent_crm_id: str | None
    assigned_agent_name: str | None
    sms_permission_status: str
    email_permission_status: str
    sms_opted_out: bool
    email_unsubscribed: bool
    do_not_contact: bool | None
    suppression_types: list[str]
    contactability: LeadContactabilityResponse
    sendability: LeadSendabilityResponse
    facts_derived_at: datetime
    last_activity_at: datetime | None
    last_meaningful_communication_at: datetime | None
    last_agent_activity_at: datetime | None


class LeadWorkflowResponse(BaseModel):
    workflow_id: UUID
    campaign_id: UUID
    state: str
    current_step_id: str | None
    next_action_at: datetime | None
    last_transition_at: datetime
    pause_reason: str | None
    resume_reason: str | None


class WorkflowTransitionResponse(BaseModel):
    transition_id: UUID
    workflow_id: UUID
    lead_id: UUID
    campaign_id: UUID
    from_state: str | None
    to_state: str
    reason_code: str
    actor_user_id: UUID | None
    created_at: datetime
    metadata: dict[str, object]


class InboundMessageResponse(BaseModel):
    inbound_message_id: UUID
    conversation_id: UUID
    channel: str
    provider: str
    provider_message_id: str
    body: str
    received_at: datetime
    processed_at: datetime | None
    classification_status: str


class OutboundMessageResponse(BaseModel):
    message_id: UUID
    campaign_id: UUID
    cadence_step_id: str
    channel: str
    status: str
    body: str
    subject: str | None
    scheduled_for: datetime | None
    planned_at: datetime | None
    sent_at: datetime | None
    provider_send_status: str
    provider_name: str | None
    provider_delivery_status: str | None
    delivered_at: datetime | None
    failure_reason: str | None


class LeadActivityItemResponse(BaseModel):
    activity_id: UUID
    lead_id: UUID
    kind: str
    occurred_at: datetime
    title: str
    preview: str
    channel: str | None = None
    direction: str | None = None
    status: str | None = None
    actor_name: str | None = None


class RejectedDraftReviewResponse(BaseModel):
    review_id: UUID
    workflow_id: UUID
    workflow_transition_id: UUID
    campaign_id: UUID
    campaign_version_id: UUID
    cadence_step_id: UUID
    channel: str
    status: str
    reason_codes: list[str] = Field(default_factory=list)
    draft_reason_codes: list[str] = Field(default_factory=list)
    review_blockers: list[str] = Field(default_factory=list)
    draft_safety_flags: list[str] = Field(default_factory=list)
    draft_personalization_notes: list[str] = Field(default_factory=list)
    draft_body: str | None = None
    draft_subject: str | None = None
    raw_llm_response_text: str | None = None
    validation_error: str | None = None
    explanation: str | None = None
    draft_confidence: float | None = None
    draft_model: str | None = None
    draft_prompt_version: str | None = None
    can_approve_send: bool = False
    reviewed_by_user_id: UUID | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    outbound_message_id: UUID | None = None
    created_at: datetime | None = None


class LeadListItemResponse(BaseModel):
    lead: LeadResponse
    latest_workflow: LeadWorkflowResponse | None = None
    latest_handoff: HandoffResponse | None = None
    has_activity: bool = False
    activity_count: int = 0
    inbound_message_count: int = 0
    outbound_message_count: int = 0
    crm_event_count: int = 0
    handoff_count: int = 0
    latest_activity_at: datetime | None = None
    latest_activity_preview: str | None = None
    latest_activity_kind: str | None = None
    has_conversation: bool = False
    latest_inbound_at: datetime | None = None
    latest_inbound_preview: str | None = None


class LeadListResponse(BaseModel):
    status: str
    leads: list[LeadListItemResponse]


class LeadDetailResponse(BaseModel):
    status: str
    lead: LeadResponse
    latest_workflow: LeadWorkflowResponse | None = None
    latest_handoff: HandoffResponse | None = None
    workflow_transitions: list[WorkflowTransitionResponse]
    rejected_draft_reviews: list[RejectedDraftReviewResponse]
    activity_log: list[LeadActivityItemResponse]
    inbound_messages: list[InboundMessageResponse]
    outbound_messages: list[OutboundMessageResponse]
    handoffs: list[HandoffResponse]


class LeadResumeEligibilityResponse(BaseModel):
    status: str
    can_resume: bool
    workflow_id: UUID | None = None
    workflow_state: str | None = None
    contactable_channels: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    blocked_contactability_reasons: list[str] = Field(default_factory=list)


class LeadManualEnrollmentOptionResponse(BaseModel):
    campaign_id: UUID
    campaign_version_id: UUID
    campaign_name: str
    enabled_channels: list[str] = Field(default_factory=list)
    preflight_digest_enabled: bool


class LeadManualEnrollmentOptionsResponse(BaseModel):
    status: str
    campaigns: list[LeadManualEnrollmentOptionResponse] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    total_campaign_count: int = 0
    active_campaign_count: int = 0
    active_published_campaign_count: int = 0
    already_enrolled_campaign_count: int = 0


class StartLeadManualEnrollmentRequest(BaseModel):
    campaign_id: UUID


class StartLeadManualEnrollmentResponse(BaseModel):
    status: str
    campaign_id: UUID | None = None
    campaign_version_id: UUID | None = None
    campaign_enrollment_id: UUID | None = None
    workflow_id: UUID | None = None
    temporal_workflow_id: str | None = None
    reasons: list[str] = Field(default_factory=list)
    error: str | None = None


class ResumeLeadWorkflowRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ResumeLeadWorkflowResponse(BaseModel):
    status: str
    workflow_id: UUID | None = None
    workflow_state: str | None = None
    reasons: list[str] = Field(default_factory=list)
    signal_queued: bool = False


class ApproveRejectedDraftReviewRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ApproveRejectedDraftReviewResponse(BaseModel):
    status: str
    review_id: UUID | None = None
    outbound_message_id: UUID | None = None
    workflow_id: UUID | None = None
    reasons: list[str] = Field(default_factory=list)
    signal_queued: bool = False
