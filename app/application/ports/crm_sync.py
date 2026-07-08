from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.domain.common.ids import WorkspaceId
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
        mapped_custom_field_keys: tuple[str, ...] = (),
    ) -> CanonicalLeadSnapshotPage:
        raise NotImplementedError