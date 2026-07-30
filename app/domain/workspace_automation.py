from dataclasses import dataclass
from enum import StrEnum

from app.domain.common.ids import WorkspaceId


class WorkspaceAutomationStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    SUSPENDED = "suspended"


@dataclass(frozen=True)
class WorkspaceOperationalControl:
    workspace_id: WorkspaceId
    automation_status: WorkspaceAutomationStatus = WorkspaceAutomationStatus.ACTIVE
    pause_reason: str | None = None
    recurring_paused_search_enabled: bool = False


def default_workspace_operational_control(
    workspace_id: WorkspaceId,
) -> WorkspaceOperationalControl:
    return WorkspaceOperationalControl(workspace_id=workspace_id)