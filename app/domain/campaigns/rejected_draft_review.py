from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.common.ids import CampaignId, LeadId, UserId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel


class RejectedDraftReviewStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED_SENT = "approved_sent"
    DISMISSED = "dismissed"


@dataclass(frozen=True)
class RejectedDraftReview:
    review_id: UUID
    workspace_id: WorkspaceId
    lead_id: LeadId
    workflow_id: UUID
    workflow_transition_id: UUID
    campaign_id: CampaignId
    campaign_version_id: UUID
    cadence_step_id: UUID
    channel: ContactChannel
    status: RejectedDraftReviewStatus
    reason_codes: tuple[str, ...]
    draft_reason_codes: tuple[str, ...]
    review_blockers: tuple[str, ...]
    draft_safety_flags: tuple[str, ...]
    draft_personalization_notes: tuple[str, ...]
    draft_body: str | None = None
    draft_subject: str | None = None
    raw_llm_response_text: str | None = None
    validation_error: str | None = None
    explanation: str | None = None
    draft_confidence: float | None = None
    draft_model: str | None = None
    draft_prompt_version: str | None = None
    draft_latency_ms: int | None = None
    draft_usage_tokens: int | None = None
    message_version: int = 1
    can_approve_send: bool = False
    reviewed_by_user_id: UserId | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    outbound_message_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
