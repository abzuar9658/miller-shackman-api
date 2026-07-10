from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.common.ids import CampaignId, LeadId, UserId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel


class ConversationStatus(StrEnum):
    ACTIVE_AI = "active_ai"
    PAUSED = "paused"
    HUMAN_HANDOFF = "human_handoff"
    HUMAN_OWNED = "human_owned"
    CLOSED = "closed"


class InboundMessageClassificationStatus(StrEnum):
    PENDING = "pending"
    CLASSIFIED = "classified"
    FAILED = "failed"


class HandoffReasonCode(StrEnum):
    HIGH_INTEREST = "high_interest"
    HUMAN_REQUESTED = "human_requested"
    SELLER_INTEREST = "seller_interest"
    SPECIFIC_PROPERTY_OR_ADVICE = "specific_property_or_advice"


class HandoffStatus(StrEnum):
    CREATED = "created"
    NOTIFIED = "notified"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


def _empty_preferences() -> Mapping[str, str]:
    return {}


def _empty_string_mapping() -> Mapping[str, str]:
    return {}


@dataclass(frozen=True)
class WorkspaceHandoffConfig:
    workspace_id: WorkspaceId
    fallback_recipient_email: str | None = None
    crm_handoff_tag: str | None = None
    crm_custom_fields: Mapping[str, str] = field(default_factory=_empty_string_mapping)


def default_workspace_handoff_config(workspace_id: WorkspaceId) -> WorkspaceHandoffConfig:
    return WorkspaceHandoffConfig(workspace_id=workspace_id)


@dataclass(frozen=True)
class HandoffCompletionRecord:
    handoff_id: UUID
    workspace_id: WorkspaceId
    notification_idempotency_key: str
    notification_recipient_id: str | None = None
    notification_recipient_destination: str | None = None
    notification_provider_reference: str | None = None
    notification_sent_at: datetime | None = None
    crm_note_written_at: datetime | None = None
    crm_tag_applied_at: datetime | None = None
    crm_custom_fields_updated_at: datetime | None = None
    completed_at: datetime | None = None
    last_attempted_at: datetime | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class Conversation:
    conversation_id: UUID
    workspace_id: WorkspaceId
    lead_id: LeadId
    created_at: datetime
    updated_at: datetime
    campaign_id: CampaignId | None = None
    workflow_id: UUID | None = None
    status: ConversationStatus = ConversationStatus.ACTIVE_AI
    ai_interaction_count: int = 0
    last_message_at: datetime | None = None


@dataclass(frozen=True)
class InboundMessage:
    inbound_message_id: UUID
    workspace_id: WorkspaceId
    conversation_id: UUID
    lead_id: LeadId
    channel: ContactChannel
    provider: str
    provider_message_id: str
    body: str
    received_at: datetime
    classification_status: InboundMessageClassificationStatus
    created_at: datetime
    external_event_id: UUID | None = None
    from_address_redacted: str | None = None
    to_address_redacted: str | None = None
    processed_at: datetime | None = None


@dataclass(frozen=True)
class ConversationSummary:
    summary_id: UUID
    workspace_id: WorkspaceId
    conversation_id: UUID
    lead_id: LeadId
    summary_text: str
    prompt_version: str
    model: str
    created_at: datetime
    preferences: Mapping[str, str] = field(default_factory=_empty_preferences)
    confidence: float | None = None


@dataclass(frozen=True)
class Handoff:
    handoff_id: UUID
    workspace_id: WorkspaceId
    lead_id: LeadId
    reason_code: HandoffReasonCode
    summary: str
    created_at: datetime
    campaign_id: CampaignId | None = None
    workflow_id: UUID | None = None
    conversation_id: UUID | None = None
    inbound_message_id: UUID | None = None
    assigned_agent_user_id: UserId | None = None
    assigned_agent_crm_id: str | None = None
    latest_inbound_text: str | None = None
    preferences: Mapping[str, str] = field(default_factory=_empty_preferences)
    status: HandoffStatus = HandoffStatus.CREATED
    notified_at: datetime | None = None
    acknowledged_at: datetime | None = None
