from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.common.ids import CampaignId, LeadId, WorkspaceId
from app.domain.conversations import HandoffReasonCode


@dataclass(frozen=True)
class PreflightDigestNotificationLead:
    lead_id: LeadId
    display_name: str


@dataclass(frozen=True)
class PreflightDigestNotification:
    workspace_id: WorkspaceId
    campaign_id: CampaignId
    digest_id: str
    batch_id: str
    recipient_id: str
    recipient_destination: str
    leads: tuple[PreflightDigestNotificationLead, ...]
    veto_window_expires_at: datetime
    idempotency_key: str


@dataclass(frozen=True)
class NotificationSendResult:
    accepted: bool
    provider_reference: str | None = None
    uncertain: bool = False


@dataclass(frozen=True)
class HandoffNotification:
    workspace_id: WorkspaceId
    handoff_id: UUID
    lead_id: LeadId
    recipient_id: str
    recipient_destination: str
    assigned_user_name: str | None
    lead_display_name: str
    lead_primary_email: str | None
    lead_primary_phone: str | None
    crm_lead_id: str
    crm_lead_url: str | None
    handoff_reason: HandoffReasonCode
    latest_inbound_text: str
    summary: str
    preferences: dict[str, str]
    recommended_next_action: str
    idempotency_key: str


@dataclass(frozen=True)
class ReviewNotification:
    workspace_id: WorkspaceId
    inbound_message_id: UUID
    lead_id: LeadId
    recipient_id: str
    recipient_destination: str
    lead_display_name: str
    lead_primary_email: str | None
    lead_primary_phone: str | None
    latest_inbound_text: str
    summary: str
    review_reason: str
    channel: str
    idempotency_key: str


class NotificationProvider(Protocol):
    async def send_preflight_digest(
        self,
        notification: PreflightDigestNotification,
    ) -> NotificationSendResult:
        raise NotImplementedError

    async def send_handoff_notification(
        self,
        notification: HandoffNotification,
    ) -> NotificationSendResult:
        raise NotImplementedError

    async def send_review_notification(
        self,
        notification: ReviewNotification,
    ) -> NotificationSendResult:
        raise NotImplementedError
