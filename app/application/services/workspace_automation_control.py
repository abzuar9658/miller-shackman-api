from collections.abc import Collection

from app.application.ports.repositories import WorkspaceOperationalControlRepository
from app.domain.common.ids import WorkspaceId
from app.domain.workspace_automation import (
    WorkspaceAutomationStatus,
    WorkspaceOperationalControl,
    default_workspace_operational_control,
)


async def resolve_workspace_operational_control(
    *,
    workspace_id: WorkspaceId,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None,
) -> WorkspaceOperationalControl:
    if workspace_operational_control_repository is None:
        return default_workspace_operational_control(workspace_id)

    control = await workspace_operational_control_repository.get_by_workspace_id(workspace_id)
    return control or default_workspace_operational_control(workspace_id)


def workspace_automation_is_active(control: WorkspaceOperationalControl) -> bool:
    return control.automation_status == WorkspaceAutomationStatus.ACTIVE


def workspace_automation_block_reason(control: WorkspaceOperationalControl) -> str:
    if control.pause_reason:
        return (
            f"Workspace automation is {control.automation_status.value}: "
            f"{control.pause_reason.strip()}"
        )
    return f"Workspace automation is {control.automation_status.value}."


def recurring_paused_search_is_enabled(
    *,
    control: WorkspaceOperationalControl,
    workspace_id: WorkspaceId,
    pilot_workspace_ids: Collection[WorkspaceId] | None = None,
) -> bool:
    if not control.recurring_paused_search_enabled:
        return False
    return pilot_workspace_ids is None or workspace_id in pilot_workspace_ids


def recurring_paused_search_block_reason(
    *,
    control: WorkspaceOperationalControl,
    workspace_id: WorkspaceId,
    pilot_workspace_ids: Collection[WorkspaceId] | None = None,
) -> str:
    if not control.recurring_paused_search_enabled:
        return "Recurring paused-search maintenance is disabled for this workspace."
    if pilot_workspace_ids is not None and workspace_id not in pilot_workspace_ids:
        return "Workspace is not included in the recurring paused-search pilot allowlist."
    return "Recurring paused-search maintenance is not enabled."
