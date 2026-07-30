from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class PausedSearchContractFixtureIds:
    workspace_id: UUID
    lead_id: UUID
    workflow_id: UUID
    track_id: UUID
    track_version_id: UUID
    step_id: UUID
    customer_timing_id: UUID
    occurrence_id: UUID
    review_id: UUID
    template_id: UUID
    template_version_id: UUID
    notification_id: UUID
    profile_key: str = "timing_not_right"


def paused_search_contract_fixture_ids() -> PausedSearchContractFixtureIds:
    return PausedSearchContractFixtureIds(
        workspace_id=UUID("00000000-0000-0000-0000-000000000801"),
        lead_id=UUID("00000000-0000-0000-0000-000000000802"),
        workflow_id=UUID("00000000-0000-0000-0000-000000000803"),
        track_id=UUID("00000000-0000-0000-0000-000000000804"),
        track_version_id=UUID("00000000-0000-0000-0000-000000000805"),
        step_id=UUID("00000000-0000-0000-0000-000000000806"),
        customer_timing_id=UUID("00000000-0000-0000-0000-000000000807"),
        occurrence_id=UUID("00000000-0000-0000-0000-000000000808"),
        review_id=UUID("00000000-0000-0000-0000-000000000809"),
        template_id=UUID("00000000-0000-0000-0000-000000000810"),
        template_version_id=UUID("00000000-0000-0000-0000-000000000811"),
        notification_id=UUID("00000000-0000-0000-0000-000000000812"),
    )