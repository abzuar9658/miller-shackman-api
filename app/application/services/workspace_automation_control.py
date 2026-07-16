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