from tests.application.use_cases._paused_search_contract_fixtures import (
    paused_search_contract_fixture_ids,
)


def test_paused_search_contract_fixture_ids_are_distinct_and_stable() -> None:
    fixture = paused_search_contract_fixture_ids()

    identifiers = (
        fixture.workspace_id,
        fixture.lead_id,
        fixture.workflow_id,
        fixture.track_id,
        fixture.track_version_id,
        fixture.step_id,
        fixture.customer_timing_id,
        fixture.occurrence_id,
        fixture.review_id,
        fixture.template_id,
        fixture.template_version_id,
        fixture.notification_id,
    )

    assert len(set(identifiers)) == len(identifiers)
    assert fixture.profile_key == "timing_not_right"
