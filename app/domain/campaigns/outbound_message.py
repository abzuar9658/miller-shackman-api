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


class ProviderDeliveryStatus(StrEnum):
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    FAILED = "failed"
    UNDELIVERED = "undelivered"
    BOUNCED = "bounced"
    DROPPED = "dropped"
    DEFERRED = "deferred"
    UNKNOWN = "unknown"


_OUTBOUND_EMAIL_MESSAGE_ID_PREFIX = "outbound-message"
_OUTBOUND_EMAIL_MESSAGE_ID_DOMAIN = "miller-schackman.local"


def _empty_string_tuple() -> tuple[str, ...]:
    return ()


def build_outbound_email_message_id(message_id: UUID) -> str:
    return f"{_OUTBOUND_EMAIL_MESSAGE_ID_PREFIX}.{message_id}@{_OUTBOUND_EMAIL_MESSAGE_ID_DOMAIN}"


def parse_outbound_email_message_id(value: str) -> UUID | None:
    normalized = value.strip().strip("<>")
    prefix = f"{_OUTBOUND_EMAIL_MESSAGE_ID_PREFIX}."
    suffix = f"@{_OUTBOUND_EMAIL_MESSAGE_ID_DOMAIN}"
    if not normalized.startswith(prefix) or not normalized.endswith(suffix):
        return None
    raw_uuid = normalized[len(prefix) : -len(suffix)]
    try:
        return UUID(raw_uuid)
    except ValueError:
        return None


def build_outbound_reply_to_address(inbound_email_address: str) -> str | None:
    # Plain address only: plus-addressed routing tokens in Reply-To trigger
    # Outlook's reply-redirection heuristics, which disable the Reply button.
    # Inbound attribution relies on In-Reply-To/References thread headers and
    # sender-email fallback instead; plus-addressed replies remain accepted.
    normalized_inbound = inbound_email_address.strip().lower()
    local_part, separator, domain = normalized_inbound.partition("@")
    if not separator or not local_part or not domain:
        return None
    return normalized_inbound


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
    workflow_id: UUID | None = None
    subject: str | None = None
    html_body: str | None = None
    scheduled_for: datetime | None = None
    planned_at: datetime | None = None
    sent_at: datetime | None = None
    message_version: int = 1
    provider_send_status: ProviderSendStatus = ProviderSendStatus.NOT_ATTEMPTED
    provider_name: str | None = None
    provider_message_id: str | None = None
    reply_routing_token: str | None = None
    provider_delivery_status: ProviderDeliveryStatus | None = None
    provider_status_updated_at: datetime | None = None
    delivered_at: datetime | None = None
    failure_reason: str | None = None
    # Human-readable explanation set while the message stays PENDING because a
    # timing guard (frequency limit, quiet hours, simultaneous-channel window)
    # deferred it; cleared once the message leaves PENDING. Lets operators see
    # why a message has not sent instead of an unexplained "pending" state.
    status_detail: str | None = None
    provider_attempt_count: int = 0
    provider_last_attempt_at: datetime | None = None
    provider_next_retry_at: datetime | None = None
    provider_last_failure_kind: str | None = None
    draft_prompt_version: str | None = None
    draft_model: str | None = None
    draft_latency_ms: int | None = None
    draft_usage_tokens: int | None = None
    draft_confidence: float | None = None
    draft_personalization_notes: tuple[str, ...] = field(default_factory=_empty_string_tuple)
    draft_safety_flags: tuple[str, ...] = field(default_factory=_empty_string_tuple)


@dataclass(frozen=True)
class ProviderMessageEvent:
    provider_event_id: UUID
    workspace_id: WorkspaceId
    provider: str
    provider_message_id: str
    outbound_message_id: UUID | None
    external_provider_event_id: str
    event_type: str
    status: ProviderDeliveryStatus
    received_at: datetime
    payload_redacted: dict[str, object]
    created_at: datetime


@dataclass(frozen=True)
class OutboundMessageCRMCompletionRecord:
    outbound_message_id: UUID
    workspace_id: WorkspaceId
    crm_note_idempotency_key: str
    crm_note_written_at: datetime | None = None
    crm_conversation_published_at: datetime | None = None
    crm_snapshot_updated_at: datetime | None = None
    completed_at: datetime | None = None
    last_attempted_at: datetime | None = None
    failure_reason: str | None = None
