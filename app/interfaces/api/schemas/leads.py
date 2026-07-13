from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.interfaces.api.schemas.handoffs import HandoffResponse


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


class LeadListItemResponse(BaseModel):
    lead: LeadResponse
    latest_workflow: LeadWorkflowResponse | None = None
    latest_handoff: HandoffResponse | None = None


class LeadListResponse(BaseModel):
    status: str
    leads: list[LeadListItemResponse]


class LeadDetailResponse(BaseModel):
    status: str
    lead: LeadResponse
    latest_workflow: LeadWorkflowResponse | None = None
    latest_handoff: HandoffResponse | None = None
    workflow_transitions: list[WorkflowTransitionResponse]
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


class ResumeLeadWorkflowRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ResumeLeadWorkflowResponse(BaseModel):
    status: str
    workflow_id: UUID | None = None
    workflow_state: str | None = None
    reasons: list[str] = Field(default_factory=list)
    signal_failure_reason: str | None = None
