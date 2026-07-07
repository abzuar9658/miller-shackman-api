from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.domain.common.ids import CampaignId, LeadId, WorkspaceId


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


class NotificationProvider(Protocol):
    async def send_preflight_digest(
        self,
        notification: PreflightDigestNotification,
    ) -> NotificationSendResult:
        raise NotImplementedError
