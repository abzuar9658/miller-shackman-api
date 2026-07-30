from app.domain.campaigns import (
    PausedSearchReasonMapping,
    PausedSearchTrack,
    PausedSearchTrackStep,
    PausedSearchTrackVersion,
)
from app.domain.common.ids import PausedSearchTrackId, PausedSearchTrackVersionId, WorkspaceId
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
