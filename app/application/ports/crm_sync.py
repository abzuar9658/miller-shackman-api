from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.domain.common.ids import WorkspaceId
from app.domain.crm_sync import CRMSyncLeadSort
from app.domain.leads import CanonicalLeadRecord


@dataclass(frozen=True)
class CanonicalLeadSnapshotPage:
    leads: tuple[CanonicalLeadRecord, ...] = ()
    next_cursor: str | None = None


class CanonicalLeadSnapshotSource(Protocol):
    async def list_lead_snapshots(
        self,
        *,
        workspace_id: WorkspaceId,
        page_size: int = 100,
        cursor: str | None = None,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
        sort_by: CRMSyncLeadSort | None = None,
        mapped_custom_field_keys: tuple[str, ...] = (),
    ) -> CanonicalLeadSnapshotPage:
        raise NotImplementedError


class CanonicalLeadRefreshSource(Protocol):
    async def get_lead_snapshot(
        self,
        *,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
        mapped_custom_field_keys: tuple[str, ...] = (),
    ) -> CanonicalLeadRecord | None:
        raise NotImplementedError
