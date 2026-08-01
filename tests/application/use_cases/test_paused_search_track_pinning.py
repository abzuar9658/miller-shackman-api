import asyncio
from datetime import UTC, datetime
from uuid import UUID

from app.application.services.paused_search_track_pinning import (
    pin_published_paused_search_track_on_latest_workflow,
    resolve_published_paused_search_track_version_id,
)
from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchReasonMapping,
    PausedSearchTrackFamily,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import PausedSearchReasonCode
from app.domain.workflows import LeadWorkflow, WorkflowState
from tests.application.use_cases._campaign_cadence_fakes import FakeLeadWorkflowRepository
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
)

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000003")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000004")
ENROLLMENT_ID = UUID("00000000-0000-0000-0000-000000000005")
TRACK_ID = UUID("00000000-0000-0000-0000-000000000006")
TRACK_VERSION_ID = UUID("00000000-0000-0000-0000-000000000007")


def test_resolve_returns_published_track_version_id() -> None:
    repository = FakePausedSearchTrackAdminRepository(
        mappings=(_mapping(track_version_id=TRACK_VERSION_ID),),
        versions=(_version(track_version_id=TRACK_VERSION_ID),),
    )

    result = asyncio.run(
        resolve_published_paused_search_track_version_id(
            workspace_id=WORKSPACE_ID,
            pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
            paused_search_track_repository=repository,
        )
    )

    assert result == TRACK_VERSION_ID


def test_resolve_returns_none_when_mapping_points_to_retired_version() -> None:
    repository = FakePausedSearchTrackAdminRepository(
        mappings=(_mapping(track_version_id=TRACK_VERSION_ID),),
        versions=(
            _version(
                track_version_id=TRACK_VERSION_ID,
                status=CampaignVersionStatus.RETIRED,
            ),
        ),
    )

    result = asyncio.run(
        resolve_published_paused_search_track_version_id(
            workspace_id=WORKSPACE_ID,
            pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
            paused_search_track_repository=repository,
        )
    )

    assert result is None


def test_pin_updates_latest_workflow_with_resolved_track_version() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)] = _workflow()
    repository = FakePausedSearchTrackAdminRepository(
        mappings=(_mapping(track_version_id=TRACK_VERSION_ID),),
        versions=(_version(track_version_id=TRACK_VERSION_ID),),
    )

    saved = asyncio.run(
        pin_published_paused_search_track_on_latest_workflow(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
            lead_workflow_repository=workflow_repository,
            paused_search_track_repository=repository,
            now=NOW,
        )
    )

    assert saved is not None
    assert saved.paused_search_track_version_id == TRACK_VERSION_ID


def test_pin_clears_workflow_when_reason_mapping_is_missing() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)] = _workflow(
        paused_search_track_version_id=TRACK_VERSION_ID,
    )

    saved = asyncio.run(
        pin_published_paused_search_track_on_latest_workflow(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
            lead_workflow_repository=workflow_repository,
            paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
            now=NOW,
        )
    )

    assert saved is not None
    assert saved.paused_search_track_version_id is None


def _workflow(*, paused_search_track_version_id: UUID | None = None) -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture:test",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=WorkflowState.PAUSED,
        last_transition_at=NOW,
        state_version=2,
        created_at=NOW,
        updated_at=NOW,
        paused_search_track_version_id=paused_search_track_version_id,
    )


def _version(
    *,
    track_version_id: UUID,
    status: CampaignVersionStatus = CampaignVersionStatus.PUBLISHED,
) -> PausedSearchTrackVersion:
    return PausedSearchTrackVersion(
        track_version_id=track_version_id,
        workspace_id=WORKSPACE_ID,
        track_id=TRACK_ID,
        version_number=1,
        status=status,
        track_family=PausedSearchTrackFamily.MAINTENANCE,
        enabled=True,
        allowed_channels=(ContactChannel.EMAIL,),
        default_for_reason_codes=(PausedSearchReasonCode.WAITING_FOR_RATES,),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE,
        maintenance_interval_days=90,
        reactivation_window_days=30,
        max_total_touches=2,
        requires_review_before_publish=False,
        created_by_user_id=UUID("00000000-0000-0000-0000-000000000008"),
        created_at=NOW,
        published_at=NOW if status == CampaignVersionStatus.PUBLISHED else None,
    )


def _mapping(*, track_version_id: UUID) -> PausedSearchReasonMapping:
    return PausedSearchReasonMapping(
        mapping_id=UUID("00000000-0000-0000-0000-000000000009"),
        workspace_id=WORKSPACE_ID,
        reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
        track_id=TRACK_ID,
        track_version_id=track_version_id,
        created_by_user_id=UUID("00000000-0000-0000-0000-000000000008"),
        created_at=NOW,
    )
