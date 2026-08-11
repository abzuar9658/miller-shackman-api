import pytest

from scripts.report_paused_search_messages import (
    _SCENARIO_BY_KEY,
    SCENARIOS,
    _run_case,
    build_parser,
)


def test_parser_defaults_to_safe_stub_mode_and_all_matrix() -> None:
    args = build_parser().parse_args([])

    assert args.mode == "stub"
    assert args.track is None
    assert args.scenario is None


def test_matrix_includes_handoff_and_suppression_conversation_scenarios() -> None:
    outcomes = {scenario.key: scenario.policy_outcome for scenario in SCENARIOS}

    assert outcomes["buying-interest"] == "human_handoff"
    assert outcomes["human-request"] == "human_handoff"
    assert outcomes["opt-out"] == "suppressed"


@pytest.mark.asyncio
async def test_continue_case_captures_each_email_and_sms_step() -> None:
    case = await _run_case("lease_expiration", _SCENARIO_BY_KEY["new-timeline"], "stub")

    assert case["policy_outcome"] == "continue_ai"
    assert [message["channel"] for message in case["messages"]] == [
        "email",
        "sms",
        "email",
        "sms",
        "email",
    ]
    assert all(message["execution_status"] == "sent" for message in case["messages"])
    assert case["workflow_state"] == "waiting_for_response"


@pytest.mark.asyncio
async def test_handoff_case_writes_no_outbound_messages() -> None:
    case = await _run_case("specific_property_only", _SCENARIO_BY_KEY["buying-interest"], "stub")

    assert case["policy_outcome"] == "human_handoff"
    assert case["messages"] == []
    assert case["workflow_state"] == "active_nurture"