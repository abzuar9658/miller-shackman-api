from dataclasses import replace
from datetime import datetime

from app.domain.campaigns import (
    PausedSearchReasonMapping,
    PausedSearchTrack,
    PausedSearchTrackAssignment,
    PausedSearchTrackLeadAssignment,
    PausedSearchTrackStep,
    PausedSearchTrackVersion,
)
from app.domain.common.ids import (
    LeadId,
    PausedSearchTrackId,
    PausedSearchTrackVersionId,
    UserId,
    WorkspaceId,
)
from app.domain.leads import PausedSearchReasonCode


class FakePausedSearchTrackAdminRepository:
    def __init__(
        self,
        *,
        mappings: tuple[PausedSearchReasonMapping, ...] = (),
        tracks: tuple[PausedSearchTrack, ...] = (),
        versions: tuple[PausedSearchTrackVersion, ...] = (),
        steps: tuple[PausedSearchTrackStep, ...] = (),
    ) -> None:
        self._mappings = {
            (mapping.workspace_id, mapping.reason_code): mapping for mapping in mappings
        }
        self._tracks = {(track.workspace_id, track.track_id): track for track in tracks}
        self._versions = {
            (version.workspace_id, version.track_version_id): version for version in versions
        }
        self._steps = tuple(steps)

    async def list_tracks(self, workspace_id: WorkspaceId) -> tuple[PausedSearchTrack, ...]:
        return tuple(track for track in self._tracks.values() if track.workspace_id == workspace_id)

    async def list_assigned_leads(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
        *,
        limit: int = 100,
        lock: bool = False,
    ) -> tuple[PausedSearchTrackLeadAssignment, ...]:
        return ()

    async def delete_retired_track(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> None:
        return None

    async def get_track(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrack | None:
        return self._tracks.get((workspace_id, track_id))

    async def get_reason_mapping(
        self,
        workspace_id: WorkspaceId,
        reason_code: PausedSearchReasonCode,
    ) -> PausedSearchReasonMapping | None:
        return self._mappings.get((workspace_id, reason_code))

    async def get_version(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
    ) -> PausedSearchTrackVersion | None:
        return self._versions.get((workspace_id, track_version_id))

    async def get_steps(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
    ) -> tuple[PausedSearchTrackStep, ...]:
        return tuple(
            step
            for step in self._steps
            if step.workspace_id == workspace_id and step.track_version_id == track_version_id
        )


class FakePausedSearchTrackAssignmentRepository:
    def __init__(self, assignments: tuple[PausedSearchTrackAssignment, ...] = ()) -> None:
        self.assignments = list(assignments)

    async def get_active_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> PausedSearchTrackAssignment | None:
        return self._active(workspace_id, lead_id)

    async def get_active_for_lead_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> PausedSearchTrackAssignment | None:
        return self._active(workspace_id, lead_id)

    async def create(
        self,
        assignment: PausedSearchTrackAssignment,
    ) -> PausedSearchTrackAssignment:
        self.assignments.append(assignment)
        return assignment

    async def release_active(
        self,
        *,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        released_at: datetime,
        released_by: UserId | None = None,
        release_reason: str | None = None,
    ) -> PausedSearchTrackAssignment | None:
        active = self._active(workspace_id, lead_id)
        if active is None:
            return None
        released = replace(
            active,
            released_at=released_at,
            released_by=released_by,
            release_reason=release_reason,
        )
        self.assignments[self.assignments.index(active)] = released
        return released

    def _active(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> PausedSearchTrackAssignment | None:
        return next(
            (
                assignment
                for assignment in reversed(self.assignments)
                if assignment.workspace_id == workspace_id
                and assignment.lead_id == lead_id
                and assignment.released_at is None
            ),
            None,
        )
