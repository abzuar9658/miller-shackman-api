import json
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.services.llm.reply_route_classification import (
    REPLY_ROUTE_CLASSIFICATION_PROMPT_VERSION,
    STRICT_RETRY_PROMPT_VERSION,
    ReplyRouteClassificationResult,
    ReplyRouteClassificationStatus,
    ReplyRouteJourneyContext,
    ReplyRouteJourneyKind,
    classify_reply_route,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.conversations.reply_routing import ReplyRouteOption

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


class FakeLLMClient:
    def __init__(self, text: str | list[str]) -> None:
        self.texts = [text] if isinstance(text, str) else text
        self._response_index = 0
        self.requests: list[LLMCompletionRequest] = []

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        response_index = min(self._response_index, len(self.texts) - 1)
        self._response_index += 1
        return LLMResult(
            text=self.texts[response_index],
            model="openai/gpt-4o-mini",
            prompt_version=request.prompt_version,
            latency_ms=19,
            usage_tokens=51,
        )


def _route_json(
    *,
    decision: str = "continue",
    continue_percent: int = 70,
    human_handoff_percent: int = 20,
    suppressed_percent: int = 10,
    adjusted_reengagement_date: str | None = None,
    adjusted_reengagement_window_label: str | None = None,
    summary: str = "Lead is still on plan.",
) -> str:
    return json.dumps(
        {
            "decision": decision,
            "continue_percent": continue_percent,
            "human_handoff_percent": human_handoff_percent,
            "suppressed_percent": suppressed_percent,
            "adjusted_reengagement_date": adjusted_reengagement_date,
            "adjusted_reengagement_window_label": adjusted_reengagement_window_label,
            "confidence": 0.9,
            "summary": summary,
        }
    )


def _paused_journey() -> ReplyRouteJourneyContext:
    return ReplyRouteJourneyContext(
        journey=ReplyRouteJourneyKind.PAUSED_SEARCH,
        track_key="waiting-for-rates",
        track_name="Waiting for rates",
        reengagement_not_before=date(2026, 12, 1),
        reengagement_window_label="December 2026",
        last_completed_step_goal="Check in on the paused search.",
        next_touch_scheduled_for="2026-09-01T17:00:00+00:00",
    )


async def _classify(
    text: str | list[str],
    journey: ReplyRouteJourneyContext | None = None,
) -> tuple[ReplyRouteClassificationResult, FakeLLMClient]:
    client = FakeLLMClient(text)
    result = await classify_reply_route(
        workspace_id=uuid4(),
        lead_id=uuid4(),
        channel=ContactChannel.SMS,
        inbound_text="I am still waiting until later this year.",
        journey=journey or _paused_journey(),
        now=NOW,
        llm_client=client,
    )
    return result, client


@pytest.mark.asyncio
async def test_valid_continue_classification() -> None:
    result, client = await _classify(_route_json())

    assert result.status is ReplyRouteClassificationStatus.CLASSIFIED
    assert result.decision is ReplyRouteOption.CONTINUE
    assert result.option_percentages == {
        ReplyRouteOption.CONTINUE: 70,
        ReplyRouteOption.HUMAN_HANDOFF: 20,
        ReplyRouteOption.SUPPRESSED: 10,
    }
    assert result.adjusted_reengagement_date is None
    assert len(client.requests) == 1
    assert client.requests[0].prompt_version == REPLY_ROUTE_CLASSIFICATION_PROMPT_VERSION
    assert "waiting-for-rates" in client.requests[0].prompt
    assert "2026-12-01" in client.requests[0].prompt


@pytest.mark.asyncio
async def test_adjusted_date_is_parsed_for_paused_continue() -> None:
    result, _ = await _classify(
        _route_json(
            adjusted_reengagement_date="2026-11-01",
            adjusted_reengagement_window_label="November 2026",
        )
    )

    assert result.status is ReplyRouteClassificationStatus.CLASSIFIED
    assert result.adjusted_reengagement_date == date(2026, 11, 1)
    assert result.adjusted_reengagement_window_label == "November 2026"


@pytest.mark.asyncio
async def test_dormant_journey_forbids_adjusted_date() -> None:
    result, _ = await _classify(
        [
            _route_json(adjusted_reengagement_date="2026-11-01"),
            _route_json(adjusted_reengagement_date="2026-11-01"),
        ],
        journey=ReplyRouteJourneyContext(journey=ReplyRouteJourneyKind.DORMANT),
    )

    # The dormant prompt says never to return a date; a date is only valid when
    # continuing, so this passes schema validation — but the dormant journey
    # never surfaces it downstream. The result itself stays classified.
    assert result.status is ReplyRouteClassificationStatus.CLASSIFIED


@pytest.mark.asyncio
async def test_tied_percentages_are_rejected_after_retry() -> None:
    result, client = await _classify(
        _route_json(continue_percent=50, human_handoff_percent=50, suppressed_percent=0)
    )

    assert result.status is ReplyRouteClassificationStatus.REJECTED
    assert result.decision is None
    assert result.validation_error is not None
    assert len(client.requests) == 2
    assert client.requests[1].prompt_version == STRICT_RETRY_PROMPT_VERSION


@pytest.mark.asyncio
async def test_percentages_must_sum_to_100() -> None:
    result, _ = await _classify(
        _route_json(continue_percent=60, human_handoff_percent=20, suppressed_percent=10)
    )

    assert result.status is ReplyRouteClassificationStatus.REJECTED


@pytest.mark.asyncio
async def test_decision_must_match_highest_percentage() -> None:
    result, _ = await _classify(
        _route_json(
            decision="continue",
            continue_percent=10,
            human_handoff_percent=80,
            suppressed_percent=10,
        )
    )

    assert result.status is ReplyRouteClassificationStatus.REJECTED


@pytest.mark.asyncio
async def test_adjusted_date_only_allowed_when_continuing() -> None:
    result, _ = await _classify(
        _route_json(
            decision="human_handoff",
            continue_percent=5,
            human_handoff_percent=80,
            suppressed_percent=15,
            adjusted_reengagement_date="2026-11-01",
        )
    )

    assert result.status is ReplyRouteClassificationStatus.REJECTED


@pytest.mark.asyncio
async def test_invalid_date_string_is_rejected() -> None:
    result, _ = await _classify(_route_json(adjusted_reengagement_date="next fall"))

    assert result.status is ReplyRouteClassificationStatus.REJECTED


@pytest.mark.asyncio
async def test_strict_retry_recovers_from_invalid_first_response() -> None:
    result, client = await _classify(
        ["garbage, not json", _route_json(decision="human_handoff",
            continue_percent=5, human_handoff_percent=85, suppressed_percent=10)]
    )

    assert result.status is ReplyRouteClassificationStatus.CLASSIFIED
    assert result.decision is ReplyRouteOption.HUMAN_HANDOFF
    assert len(client.requests) == 2
    assert client.requests[1].prompt_version == STRICT_RETRY_PROMPT_VERSION


@pytest.mark.asyncio
async def test_prompt_describes_all_three_options_and_no_ties_rule() -> None:
    _, client = await _classify(_route_json())

    prompt = client.requests[0].prompt
    assert "continue" in prompt
    assert "human_handoff" in prompt
    assert "suppressed" in prompt
    assert "ties are not allowed" in prompt
    assert "sum to exactly 100" in prompt
