from dataclasses import dataclass
from uuid import UUID

from app.application.ports.repositories import PausedSearchLegacyInventoryRepository
from app.domain.common.ids import PausedSearchTrackVersionId, WorkspaceId
from app.domain.identity import AuthenticatedActor, PermissionCapability, evaluate_permission
from app.domain.workflows import LeadWorkflow


@dataclass(frozen=True)
class LegacyInventoryVersion:
    track_version_id: PausedSearchTrackVersionId
    track_id: UUID
    version_number: int
    active_workflow_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class LegacyInventoryReport:
    workspace_id: WorkspaceId
    versions: tuple[LegacyInventoryVersion, ...] = ()
    active_workflows: tuple[LeadWorkflow, ...] = ()
    permission_denied: bool = False


async def inventory_paused_search_legacy_versions(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    repository: PausedSearchLegacyInventoryRepository,
) -> LegacyInventoryReport:
    permission = evaluate_permission(actor, PermissionCapability.VIEW_PAUSED_SEARCH_ANY)
    if not permission.allowed:
        return LegacyInventoryReport(workspace_id=workspace_id, permission_denied=True)

    legacy_versions = await repository.list_legacy_versions(workspace_id)
    version_ids = tuple(version.track_version_id for version, _ in legacy_versions)
    workflows = (
        await repository.list_active_workflows_for_versions(workspace_id, version_ids)
        if version_ids
        else ()
    )
    workflows_by_version: dict[PausedSearchTrackVersionId, list[UUID]] = {}
    for workflow in workflows:
        if workflow.paused_search_track_version_id is not None:
            workflows_by_version.setdefault(workflow.paused_search_track_version_id, []).append(
                workflow.workflow_id
            )
    versions = tuple(
        LegacyInventoryVersion(
            track_version_id=version.track_version_id,
            track_id=version.track_id,
            version_number=version.version_number,
            active_workflow_ids=tuple(workflows_by_version.get(version.track_version_id, ())),
        )
        for version, _ in legacy_versions
    )
    return LegacyInventoryReport(
        workspace_id=workspace_id,
        versions=versions,
        active_workflows=workflows,
    )