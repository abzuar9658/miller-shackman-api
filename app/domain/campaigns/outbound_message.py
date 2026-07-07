from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.common.ids import CampaignId, LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel


class OutboundMessageStatus(StrEnum):
    PENDING = "pending"
    CANCELLED = "cancelled"
    SENT = "sent"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


def _empty_string_tuple() -> tuple[str, ...]:
    return ()


@dataclass(frozen=True)
class OutboundMessage:
    message_id: UUID
    workspace_id: WorkspaceId
    lead_id: LeadId
    campaign_id: CampaignId
    cadence_step_id: str
    channel: ContactChannel
    status: OutboundMessageStatus
    idempotency_key: str
    body: str
    created_at: datetime
    updated_at: datetime
    subject: str | None = None
    html_body: str | None = None
    scheduled_for: datetime | None = None
    planned_at: datetime | None = None
    sent_at: datetime | None = None
    message_version: int = 1
    provider_send_status: ProviderSendStatus = ProviderSendStatus.NOT_ATTEMPTED
    provider_message_id: str | None = None
    failure_reason: str | None = None
    draft_prompt_version: str | None = None
    draft_model: str | None = None
    draft_latency_ms: int | None = None
    draft_usage_tokens: int | None = None
    draft_confidence: float | None = None
    draft_personalization_notes: tuple[str, ...] = field(default_factory=_empty_string_tuple)
    draft_safety_flags: tuple[str, ...] = field(default_factory=_empty_string_tuple)
