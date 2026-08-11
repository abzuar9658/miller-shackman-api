from app.application.services.llm.lead_state_classification import (
    LeadStateClassificationResult,
    LeadStateClassificationStatus,
)
from app.domain.leads import (
    LeadStateClassificationOutcome,
    PausedSearchTrackSelectionStatus,
)
from scripts.evaluate_lead_state_classification import (
    EvaluationScenario,
    ScenarioEvaluation,
    _aggregate_metrics,
    _build_scenarios,
    _matches,
    _scenario_catalog,
)


def _scenario(
    key: str,
    *,
    expected_outcome: str,
    expected_track_key: str | None = None,
    expected_handoff_reason: str | None = None,
) -> EvaluationScenario:
    return EvaluationScenario(
        key=key,
        title=key,
        description=key,
        expected_outcome=expected_outcome,
        expected_track_key=expected_track_key,
        events=(),
        lead_last_meaningful_communication_at=None,
        enrollment_signal="test",
        expected_handoff_reason=expected_handoff_reason,
    )


def _result(
    outcome: LeadStateClassificationOutcome,
    *,
    track_key: str | None = None,
) -> LeadStateClassificationResult:
    return LeadStateClassificationResult(
        status=LeadStateClassificationStatus.CLASSIFIED,
        prompt_version="test:v1",
        outcome=outcome,
        selected_track_key=track_key,
        track_selection_status=(
            PausedSearchTrackSelectionStatus.SELECTED if track_key else None
        ),
        confidence=0.9,
    )


def test_matches_checks_handoff_reason_when_expected() -> None:
    scenario = _scenario(
        "showing",
        expected_outcome="human_handoff",
        expected_handoff_reason="human_requested",
    )

    assert not _matches(scenario, _result(LeadStateClassificationOutcome.HUMAN_HANDOFF))


def test_aggregate_metrics_reports_route_mismatch_and_safety_signals() -> None:
    passing_scenario = _scenario("rates", expected_outcome="paused_search")
    review_scenario = _scenario("ambiguous", expected_outcome="review_hold")
    evaluations = (
        ScenarioEvaluation(
            scenario=passing_scenario,
            result=_result(LeadStateClassificationOutcome.PAUSED_SEARCH),
            prompt_texts=(),
            matches=True,
        ),
        ScenarioEvaluation(
            scenario=review_scenario,
            result=_result(
                LeadStateClassificationOutcome.PAUSED_SEARCH,
                track_key="other-known-pause",
            ),
            prompt_texts=(),
            matches=False,
        ),
    )

    metrics = _aggregate_metrics(evaluations)

    assert metrics["total_runs"] == 2
    assert metrics["passes"] == 1
    assert metrics["reviews"] == 1
    assert metrics["outcome_confusion"] == {
        "paused_search->paused_search": 1,
        "review_hold->paused_search": 1,
    }
    assert metrics["safety_signals"] == {
        "unexpected_human_handoffs": 0,
        "unexpected_blocked_routes": 0,
        "unstable_scenarios": [],
    }


def test_seeded_scenarios_use_all_six_competing_tracks() -> None:
    expected_keys = {
        "specific_property_only",
        "waiting_for_inventory",
        "renter_now_future_buyer",
        "lease_expiration",
        "recently_renewed_lease",
        "search_fit_reassessment",
    }
    scenarios = {scenario.key: scenario for scenario in _build_scenarios()}

    assert expected_keys <= scenarios.keys()
    for track_key in expected_keys:
        catalog = _scenario_catalog(scenarios[track_key])
        assert {entry.track_key for entry in catalog} == expected_keys
        assert all(entry.selection_guidance for entry in catalog)


def test_legacy_renter_context_targets_the_current_seeded_track() -> None:
    scenarios = {scenario.key: scenario for scenario in _build_scenarios()}
    scenario = scenarios["renter_now_future_buyer_lease_context"]

    assert scenario.expected_track_key == "renter_now_future_buyer"
    assert {entry.track_key for entry in _scenario_catalog(scenario)} == {
        "specific_property_only",
        "waiting_for_inventory",
        "renter_now_future_buyer",
        "lease_expiration",
        "recently_renewed_lease",
        "search_fit_reassessment",
    }
