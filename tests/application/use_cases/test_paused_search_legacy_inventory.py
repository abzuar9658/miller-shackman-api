import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from app.application.use_cases.paused_search_legacy_inventory import (
    inventory_paused_search_legacy_versions,
)
from app.domain.campaigns import PausedSearchTrackStep
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.paused_search_tracks import PausedSearchTrackVersion
from app.domain.common.ids import PausedSearchTrackVersionId, WorkspaceId
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.workflows import LeadWorkflow, WorkflowState
from tests.application.use_cases.test_paused_search_track_admin import (
    ACTOR_ID,
    MEMBERSHIP_ID,
    NOW,
    VERSION_ID,
    _step_tuple,
    _version,
)

OTHER_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000099")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000010")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000011")


class FakeLegacyInventoryRepository:
    def __init__(self) -> None:
        self.versions: tuple[
            tuple[PausedSearchTrackVersion, tuple[PausedSearchTrackStep, ...]], ...
        ] = ()
        self.workflows: tuple[LeadWorkflow, ...] = ()
        self.requested_workspace_ids: list[WorkspaceId] = []

    async def list_legacy_versions(
        self, workspace_id: WorkspaceId
    ) -> tuple[tuple[PausedSearchTrackVersion, tuple[PausedSearchTrackStep, ...]], ...]:
        self.requested_workspace_ids.append(workspace_id)
        return self.versions

    async def list_active_workflows_for_versions(
        self,
        workspace_id: WorkspaceId,
        track_version_ids: tuple[PausedSearchTrackVersionId, ...],
    ) -> tuple[LeadWorkflow, ...]:
        self.requested_workspace_ids.append(workspace_id)
        return tuple(
            workflow
            for workflow in self.workflows
            if workflow.paused_search_track_version_id in track_version_ids
        )


def _actor() -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        user_status=UserStatus.ACTIVE,
        active_role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
        active_workspace_id=WorkspaceId("00000000-0000-0000-0000-000000000001"),
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=MEMBERSHIP_ID,
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


def _workflow() -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="paused-search-workflow",
        workspace_id=WorkspaceId("00000000-0000-0000-0000-000000000001"),
        campaign_enrollment_id=UUID("00000000-0000-0000-0000-000000000012"),
        campaign_id=UUID("00000000-0000-0000-0000-000000000013"),
        lead_id=LEAD_ID,
        state=WorkflowState.ACTIVE_NURTURE,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
        next_action_at=datetime(2030, 1, 2, tzinfo=UTC),
        paused_search_track_version_id=VERSION_ID,
    )


def test_inventory_reports_legacy_versions_and_active_pins() -> None:
    repository = FakeLegacyInventoryRepository()
    legacy_step = _step_tuple(VERSION_ID)[0]
    legacy_step = replace(legacy_step, action=None, review_required=True)
    repository.versions = ((_version(status=CampaignVersionStatus.PUBLISHED), (legacy_step,)),)
    repository.workflows = (_workflow(),)

    workspace_id = _actor().active_workspace_id
    assert workspace_id is not None
    report = asyncio.run(
        inventory_paused_search_legacy_versions(
            actor=_actor(),
            workspace_id=workspace_id,
            repository=repository,
        )
    )

    assert len(report.versions) == 1
    assert report.versions[0].active_workflow_ids == (WORKFLOW_ID,)
    assert report.active_workflows[0].next_action_at == datetime(2030, 1, 2, tzinfo=UTC)


def test_inventory_is_workspace_scoped_and_empty_report_skips_workflow_lookup() -> None:
    repository = FakeLegacyInventoryRepository()

    report = asyncio.run(
        inventory_paused_search_legacy_versions(
            actor=_actor(),
            workspace_id=OTHER_WORKSPACE_ID,
            repository=repository,
        )
    )

    assert report.workspace_id == OTHER_WORKSPACE_ID
    assert report.versions == ()
    assert report.active_workflows == ()
    assert repository.requested_workspace_ids == [OTHER_WORKSPACE_ID]