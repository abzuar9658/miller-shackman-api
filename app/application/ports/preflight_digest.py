from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from app.domain.common.ids import CampaignId, LeadId, WorkspaceId


class PreflightDigestIssueStatus(StrEnum):
    ISSUED = "issued"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class PreflightDigestEntry:
    lead_id: LeadId
    recipient_id: str
    recipient_destination: str
    display_name: str


@dataclass(frozen=True)
class PreflightDigestNotificationRecord:
    recipient_id: str
    idempotency_key: str
    accepted: bool
    provider_reference: str | None = None
    uncertain: bool = False


@dataclass(frozen=True)
class PreflightVetoRecord:
    lead_id: LeadId
    actor_id: str
    recorded_at: datetime
    idempotency_key: str
    reason: str | None = None


@dataclass(frozen=True)
class PreflightDigestRecord:
    digest_id: str
    workspace_id: WorkspaceId
    campaign_id: CampaignId
    batch_id: str
    status: PreflightDigestIssueStatus
    entries: tuple[PreflightDigestEntry, ...]
    notification_records: tuple[PreflightDigestNotificationRecord, ...] = ()
    digest_sent_at: datetime | None = None
    veto_window_expires_at: datetime | None = None
    vetoes: tuple[PreflightVetoRecord, ...] = field(default_factory=tuple)

    @property
    def vetoed_lead_ids(self) -> frozenset[LeadId]:
        return frozenset(veto.lead_id for veto in self.vetoes)


class PreflightDigestRepository(Protocol):
    async def list_digests_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 50,
    ) -> tuple[PreflightDigestRecord, ...]:
        raise NotImplementedError

    async def get_digest_by_id(
        self,
        workspace_id: WorkspaceId,
        digest_id: str,
    ) -> PreflightDigestRecord | None:
        raise NotImplementedError

    async def get_digest(
        self,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
        batch_id: str,
    ) -> PreflightDigestRecord | None:
        raise NotImplementedError

    async def save_digest(self, record: PreflightDigestRecord) -> None:
        raise NotImplementedError
