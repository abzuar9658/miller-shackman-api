from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PreflightDigestEntryResponse(BaseModel):
    lead_id: UUID
    recipient_id: str
    recipient_destination: str
    display_name: str
    vetoed: bool


class PreflightDigestNotificationResponse(BaseModel):
    recipient_id: str
    idempotency_key: str
    accepted: bool
    provider_reference: str | None = None
    uncertain: bool = False


class PreflightVetoResponse(BaseModel):
    lead_id: UUID
    actor_id: str
    recorded_at: datetime
    idempotency_key: str
    reason: str | None = None


class PreflightDigestSummaryResponse(BaseModel):
    digest_id: str
    campaign_id: UUID
    batch_id: str
    status: str
    lead_count: int
    veto_count: int
    recipient_count: int
    digest_sent_at: datetime | None = None
    veto_window_expires_at: datetime | None = None


class PreflightDigestDetailResponse(BaseModel):
    status: str
    digest: PreflightDigestSummaryResponse
    entries: list[PreflightDigestEntryResponse]
    notifications: list[PreflightDigestNotificationResponse]
    vetoes: list[PreflightVetoResponse]


class PreflightDigestListResponse(BaseModel):
    status: str
    digests: list[PreflightDigestSummaryResponse]
