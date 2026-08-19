from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

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


class LeadPausedSearchProfileResponse(BaseModel):
    paused_search_active: bool
    paused_search_track_key: str | None = None
    paused_search_track_version_id: UUID | None = None
    pause_reason_note: str | None = None
    reengagement_not_before: datetime | None = None
    reengagement_window_label: str | None = None
    paused_search_source: str | None = None
    paused_search_recorded_at: datetime | None = None
    paused_search_recorded_by_user_id: UUID | None = None
    paused_search_last_confirmed_at: datetime | None = None


class LeadPausedSearchHistoryEntryResponse(BaseModel):
    history_id: UUID
    action: str
    actor_user_id: UUID | None
    actor_name: str | None = None
    created_at: datetime
    previous_profile: LeadPausedSearchProfileResponse | None = None
    current_profile: LeadPausedSearchProfileResponse | None = None


class LeadClassificationTraceResponse(BaseModel):
    prompt_text: str | None = None
    input_context: dict[str, object] = Field(default_factory=dict)
    raw_response_text: str | None = None
    parsed_response: dict[str, object] = Field(default_factory=dict)


class LeadClassificationArtifactResponse(BaseModel):
    artifact_id: UUID
    source: str
    outcome: str
    selected_track_key: str | None = None
    track_selection_status: str | None = None
    track_version_id: UUID | None = None
    reengagement_not_before: datetime | None = None
    reengagement_window_label: str | None = None
    confidence: float | None = None
    evidence: list[str] = Field(default_factory=list)
    summary: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    latency_ms: int
    usage_tokens: int | None = None
    applied_status: str
    applied_at: datetime | None = None
    created_at: datetime
    llm_trace: LeadClassificationTraceResponse | None = None


class LeadRoutingReviewResponse(BaseModel):
    review_id: UUID
    artifact_id: UUID
    status: str
    reason_codes: list[str] = Field(default_factory=list)
    resolution: str | None = None
    reviewed_by_user_id: UUID | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class LeadPausedSearchTrackStepPlanResponse(BaseModel):
    step_id: UUID
    track_version_id: UUID
    step_order: int
    phase: str
    channel: str
    delay_hours: int
    message_goal: str
    template_key: str
    max_attempts: int
    review_required: bool
    timing_basis: str
    fallback_channel: str | None = None
    interval_days: int | None = None
    max_occurrences: int
    template_version_id: UUID | None = None


class LeadPausedSearchTrackPlanResponse(BaseModel):
    track_id: UUID
    track_key: str
    display_name: str
    track_status: str
    track_version_id: UUID
    version_number: int
    version_status: str
    selection_guidance: str
    enabled: bool
    allowed_channels: list[str] = Field(default_factory=list)
    fallback_timing_policy: str
    maintenance_interval_days: int
    reactivation_window_days: int
    max_total_touches: int
    default_pause_duration_days: int
    max_duration_days: int
    terminal_behavior: str
    steps: list[LeadPausedSearchTrackStepPlanResponse] = Field(default_factory=list)
    current_step_id: UUID | None = None
    current_step_order: int | None = None
    current_phase: str | None = None
    current_channel: str | None = None
    current_message_goal: str | None = None
    next_action_at: datetime | None = None


class LeadQualificationPlanResponse(BaseModel):
    classification_artifact: LeadClassificationArtifactResponse | None = None
    paused_search_plan: LeadPausedSearchTrackPlanResponse | None = None


class LeadDecisionTreeNodeResponse(BaseModel):
    node_id: str
    kind: str
    label: str
    row: int
    column: int
    status: str
    description: str | None = None
    chips: list[str] = Field(default_factory=list)


class LeadDecisionTreeEdgeResponse(BaseModel):
    edge_id: str
    from_node_id: str
    to_node_id: str
    status: str
    label: str | None = None
    description: str | None = None
    detail_lines: list[str] = Field(default_factory=list)


class LeadDecisionTreeResponse(BaseModel):
    title: str
    subtitle: str
    nodes: list[LeadDecisionTreeNodeResponse] = Field(default_factory=list)
    edges: list[LeadDecisionTreeEdgeResponse] = Field(default_factory=list)


class ClassifyLeadResponse(BaseModel):
    status: str
    lead_id: UUID
    outcome: str | None = None
    confidence: float | None = None
    applied_status: str | None = None
    artifact: LeadClassificationArtifactResponse | None = None
    paused_search: LeadPausedSearchProfileResponse | None = None
    history_entry: LeadPausedSearchHistoryEntryResponse | None = None
    reasons: list[str] = Field(default_factory=list)


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
    paused_search: LeadPausedSearchProfileResponse | None = None
    facts_derived_at: datetime
    last_activity_at: datetime | None
    last_meaningful_communication_at: datetime | None
    last_agent_activity_at: datetime | None


class LeadAssignedCRMAgentResponse(BaseModel):
    external_agent_id: str
    name: str | None = None
    email: str | None = None


class LeadMappedAppUserResponse(BaseModel):
    user_id: UUID
    full_name: str
    email: str


class LeadOwnershipResponse(BaseModel):
    crm_assigned_agent: LeadAssignedCRMAgentResponse | None = None
    mapped_app_user: LeadMappedAppUserResponse | None = None


class LeadWorkflowResponse(BaseModel):
    workflow_id: UUID
    campaign_id: UUID
    state: str
    current_step_id: str | None
    next_action_at: datetime | None
    paused_search_track_version_id: UUID | None = None
    paused_search_track_step_id: UUID | None = None
    last_transition_at: datetime
    pause_reason: str | None
    resume_reason: str | None


class LeadWorkflowOverrideAuditLogResponse(BaseModel):
    audit_log_id: UUID
    workflow_id: UUID
    action: str
    reason: str
    actor_user_id: UUID
    actor_name: str | None = None
    details: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


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
    from_address_redacted: str | None
    to_address_redacted: str | None
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
    content: str | None = None
    channel: str | None = None
    direction: str | None = None
    status: str | None = None
    actor_name: str | None = None
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    transcript_segments: list[dict[str, str | None]] = Field(default_factory=list)


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
    ownership: LeadOwnershipResponse
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


class PendingRoutingReviewItemResponse(BaseModel):
    review: LeadRoutingReviewResponse
    lead: LeadResponse
    artifact: LeadClassificationArtifactResponse


class PendingRoutingReviewListResponse(BaseModel):
    status: str
    items: list[PendingRoutingReviewItemResponse]


class LeadCadenceStepOccurrenceResponse(BaseModel):
    occurrence_number: int
    sent_at: datetime | None = None
    projected_for: datetime | None = None


class LeadCadenceStepProgressResponse(BaseModel):
    step_id: UUID
    step_order: int
    channel: str
    delay_hours: int
    message_goal: str
    status: str
    attempt_count: int
    sent_at: datetime | None = None
    scheduled_for: datetime | None = None
    last_failure_reason: str | None = None
    phase: str | None = None
    interval_days: int | None = None
    max_occurrences: int = 1
    occurrences: list[LeadCadenceStepOccurrenceResponse] = Field(default_factory=list)


class LeadCadenceProgressResponse(BaseModel):
    journey: str
    flow_name: str
    steps: list[LeadCadenceStepProgressResponse] = Field(default_factory=list)
    total_steps: int
    completed_steps: int
    current_step_order: int | None = None
    next_action_at: datetime | None = None


class LeadDetailResponse(BaseModel):
    status: str
    lead: LeadResponse
    ownership: LeadOwnershipResponse
    latest_workflow: LeadWorkflowResponse | None = None
    latest_handoff: HandoffResponse | None = None
    qualification_plan: LeadQualificationPlanResponse | None = None
    decision_tree: LeadDecisionTreeResponse
    status_narrative: str | None = None
    cadence_progress: list[LeadCadenceProgressResponse] = Field(default_factory=list)
    workflow_transitions: list[WorkflowTransitionResponse]
    workflow_override_audits: list[LeadWorkflowOverrideAuditLogResponse] = Field(
        default_factory=list
    )
    paused_search_history: list[LeadPausedSearchHistoryEntryResponse] = Field(default_factory=list)
    routing_reviews: list[LeadRoutingReviewResponse] = Field(default_factory=list)
    rejected_draft_reviews: list[RejectedDraftReviewResponse]
    activity_log: list[LeadActivityItemResponse]
    inbound_messages: list[InboundMessageResponse]
    outbound_messages: list[OutboundMessageResponse]
    handoffs: list[HandoffResponse]


class UpdateLeadPausedSearchRequest(BaseModel):
    active: bool
    selected_track_key: str | None = Field(default=None, min_length=1, max_length=255)
    reason_note: str | None = Field(default=None, max_length=1000)
    reengagement_not_before: datetime | None = None
    reengagement_window_label: str | None = Field(default=None, max_length=100)
    terminal_behavior: str | None = Field(default=None, min_length=1, max_length=50)
    terminal_reason: str | None = Field(default=None, max_length=500)
    progress_handling: Literal["restart", "continue"] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "UpdateLeadPausedSearchRequest":
        if self.active and self.selected_track_key is None:
            raise ValueError("selected_track_key is required when active is true")
        if not self.active and any(
            value is not None
            for value in (
                self.selected_track_key,
                self.reason_note,
                self.reengagement_not_before,
                self.reengagement_window_label,
            )
        ):
            raise ValueError("clear requests cannot include paused-search profile fields")
        if self.active and (self.terminal_behavior is not None or self.terminal_reason is not None):
            raise ValueError("terminal fields are only allowed when clearing the profile")
        if self.terminal_reason is not None and self.terminal_behavior is None:
            raise ValueError("terminal_reason requires terminal_behavior")
        if not self.active and self.progress_handling is not None:
            raise ValueError("progress_handling is only allowed when setting a track")
        return self


class UpdateLeadPausedSearchResponse(BaseModel):
    status: str
    lead_id: UUID | None = None
    paused_search: LeadPausedSearchProfileResponse | None = None
    history_entry: LeadPausedSearchHistoryEntryResponse | None = None
    reasons: list[str] = Field(default_factory=list)
    workflow_terminalized: bool = False
    workflow_state: str | None = None


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
    reason: str | None = Field(default=None, min_length=1, max_length=500)
    route: Literal["classify", "dormant"] = "classify"


class StartLeadManualEnrollmentResponse(BaseModel):
    status: str
    campaign_id: UUID | None = None
    campaign_version_id: UUID | None = None
    campaign_enrollment_id: UUID | None = None
    workflow_id: UUID | None = None
    temporal_workflow_id: str | None = None
    route: str | None = None
    reasons: list[str] = Field(default_factory=list)
    error: str | None = None


class StartSelectedPausedSearchTrackRequest(BaseModel):
    campaign_id: UUID
    reason: str | None = Field(default=None, min_length=1, max_length=500)


class StartSelectedPausedSearchTrackResponse(BaseModel):
    status: str
    campaign_id: UUID | None = None
    campaign_version_id: UUID | None = None
    campaign_enrollment_id: UUID | None = None
    workflow_id: UUID | None = None
    temporal_workflow_id: str | None = None
    route: str | None = None
    reasons: list[str] = Field(default_factory=list)
    error: str | None = None


class ResolveLeadReviewHoldRequest(BaseModel):
    resolution: str
    campaign_id: UUID
    selected_track_key: str | None = Field(default=None, min_length=1, max_length=255)
    pause_reason_note: str | None = Field(default=None, max_length=1000)
    reengagement_not_before: datetime | None = None
    reengagement_window_label: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_shape(self) -> "ResolveLeadReviewHoldRequest":
        if self.resolution == "paused_search" and self.selected_track_key is None:
            raise ValueError("selected_track_key is required for paused_search resolution")
        if self.resolution != "paused_search" and any(
            value is not None
            for value in (
                self.selected_track_key,
                self.pause_reason_note,
                self.reengagement_not_before,
                self.reengagement_window_label,
            )
        ):
            raise ValueError("paused-search fields are only allowed for paused_search resolution")
        return self


class ResolveLeadReviewHoldResponse(BaseModel):
    status: str
    resolution: str | None = None
    lead_id: UUID | None = None
    campaign_id: UUID | None = None
    artifact: LeadClassificationArtifactResponse | None = None
    paused_search: LeadPausedSearchProfileResponse | None = None
    history_entry: LeadPausedSearchHistoryEntryResponse | None = None
    campaign_enrollment_id: UUID | None = None
    workflow_id: str | None = None
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


class PauseLeadWorkflowRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class PauseLeadWorkflowResponse(BaseModel):
    status: str
    workflow_id: UUID | None = None
    workflow_state: str | None = None
    reasons: list[str] = Field(default_factory=list)
    signal_queued: bool = False


class OverridePausedSearchTimingRequest(BaseModel):
    reengagement_not_before: datetime | None = None
    reengagement_window_label: str | None = Field(default=None, max_length=100)
    reason: str = Field(min_length=1, max_length=500)


class OverridePausedSearchTimingResponse(BaseModel):
    status: str
    lead_id: UUID | None = None
    workflow_id: UUID | None = None
    paused_search: LeadPausedSearchProfileResponse | None = None
    next_action_at: datetime | None = None
    reasons: list[str] = Field(default_factory=list)


class SkipPausedSearchNextTouchRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class SkipPausedSearchNextTouchResponse(BaseModel):
    status: str
    lead_id: UUID | None = None
    workflow_id: UUID | None = None
    skipped_step_id: UUID | None = None
    next_action_at: datetime | None = None
    reasons: list[str] = Field(default_factory=list)


class TerminalizePausedSearchRequest(BaseModel):
    terminal_behavior: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=500)


class TerminalizePausedSearchResponse(BaseModel):
    status: str
    lead_id: UUID | None = None
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


class DismissRejectedDraftReviewRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class DismissRejectedDraftReviewResponse(BaseModel):
    status: str
    review_id: UUID | None = None
    workflow_id: UUID | None = None
    reasons: list[str] = Field(default_factory=list)
    signal_queued: bool = False
