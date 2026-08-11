from dataclasses import replace
from datetime import datetime
from uuid import UUID

from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTrack,
    PausedSearchTrackAssignment,
    PausedSearchTrackCatalogEntry,
    PausedSearchTrackLeadAssignment,
    PausedSearchTrackStep,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.paused_search_tracks import PausedSearchTrackStatus
from app.domain.common.ids import (
    LeadId,
    PausedSearchTrackId,
    PausedSearchTrackVersionId,
    UserId,
    WorkspaceId,
)
from app.domain.compliance.contactability import ContactChannel

DEFAULT_TRACK_ID = UUID("99999999-9999-9999-9999-999999999999")
DEFAULT_TRACK_VERSION_ID = UUID("88888888-8888-8888-8888-888888888888")


class FakePausedSearchTrackAdminRepository:
    def __init__(
        self,
        *,
        tracks: tuple[PausedSearchTrack, ...] = (),
        versions: tuple[PausedSearchTrackVersion, ...] = (),
        steps: tuple[PausedSearchTrackStep, ...] = (),
    ) -> None:
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

    async def list_active_catalog(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[PausedSearchTrackCatalogEntry, ...]:
        entries: list[PausedSearchTrackCatalogEntry] = []
        for track in self._tracks.values():
            if (
                track.workspace_id != workspace_id
                or track.status is not PausedSearchTrackStatus.ACTIVE
                or track.active_version_id is None
            ):
                continue
            version = self._versions.get((workspace_id, track.active_version_id))
            if (
                version is None
                or version.status is not CampaignVersionStatus.PUBLISHED
                or not version.enabled
            ):
                continue
            entries.append(
                PausedSearchTrackCatalogEntry(
                    track_key=track.track_key,
                    display_name=track.display_name,
                    selection_guidance=version.selection_guidance,
                    track_id=track.track_id,
                    track_version_id=version.track_version_id,
                )
            )
        return tuple(entries)

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


def published_paused_search_track_repository(
    *,
    workspace_id: WorkspaceId,
    now: datetime,
    track_key: str = "waiting-for-rates",
    track_id: PausedSearchTrackId = DEFAULT_TRACK_ID,
    track_version_id: PausedSearchTrackVersionId = DEFAULT_TRACK_VERSION_ID,
) -> FakePausedSearchTrackAdminRepository:
    return FakePausedSearchTrackAdminRepository(
        tracks=(
            PausedSearchTrack(
                track_id=track_id,
                workspace_id=workspace_id,
                track_key=track_key,
                display_name="Waiting for rates",
                status=PausedSearchTrackStatus.ACTIVE,
                active_version_id=track_version_id,
                created_by_user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                created_at=now,
                updated_at=now,
            ),
        ),
        versions=(
            PausedSearchTrackVersion(
                track_version_id=track_version_id,
                workspace_id=workspace_id,
                track_id=track_id,
                version_number=1,
                status=CampaignVersionStatus.PUBLISHED,
                selection_guidance="Select when a lead waits for mortgage rates to improve.",
                enabled=True,
                allowed_channels=(ContactChannel.EMAIL,),
                fallback_timing_policy=(
                    PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL
                ),
                maintenance_interval_days=60,
                reactivation_window_days=30,
                max_total_touches=4,
                created_by_user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                created_at=now,
                published_at=now,
            ),
        ),
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
