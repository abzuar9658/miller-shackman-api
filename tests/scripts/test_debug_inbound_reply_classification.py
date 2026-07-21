import json
from datetime import UTC, datetime

from scripts.debug_inbound_reply_classification import (
    _build_lead,
    _build_scenarios,
    _build_strict_prompt,
    inspect_llm_output,
)


def test_inspect_llm_output_accepts_valid_structured_json() -> None:
    result = inspect_llm_output(
        json.dumps(
            {
                "intent": "human_requested",
                "confidence": 0.91,
                "asks_for_human": True,
                "shows_buying_interest": False,
                "shows_selling_interest": False,
                "asks_property_or_advice": False,
                "opt_out_detected": False,
                "summary_text": "Lead asked for a call today.",
                "preferences": {"timeline": "today"},
            }
        )
    )

    assert result.validation_ok is True
    assert result.parsed is not None
    assert result.parsed["intent"] == "human_requested"


def test_inspect_llm_output_rejects_legacy_schema() -> None:
    result = inspect_llm_output(
        json.dumps(
            {
                "intent": "human_requested",
                "confidence": 0.91,
                "handoff_required": True,
                "handoff_reason": "human_requested",
                "summary_text": "Lead asked for a call today.",
                "preferences": {"timeline": "today"},
            }
        )
    )

    assert result.validation_ok is False
    assert result.validation_error is not None
    assert "asks_for_human" in result.validation_error


def test_build_strict_prompt_includes_schema_and_enum_constraints() -> None:
    lead = _build_lead(datetime(2026, 7, 20, 12, 0, tzinfo=UTC))

    prompt = _build_strict_prompt(lead=lead, inbound_text="Can someone call me today?")

    assert "Return exactly one valid JSON object and nothing else." in prompt
    assert "Use these intent enum values only" in prompt
    assert '"asks_for_human": true' in prompt.lower()


def test_build_scenarios_includes_strict_debug_variant_by_default() -> None:
    lead = _build_lead(datetime(2026, 7, 20, 12, 0, tzinfo=UTC))

    scenarios = _build_scenarios(
        lead=lead,
        inbound_text="Can someone call me today?",
        prod_only=False,
    )

    assert [scenario.label for scenario in scenarios] == [
        "production_prompt",
        "strict_debug_prompt",
    ]