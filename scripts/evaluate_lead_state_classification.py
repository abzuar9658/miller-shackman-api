"""Run the real lead-state classifier against synthetic conversations.

This script makes live OpenRouter calls through the production LLM adapter. It
does not create CRM records, send messages, or persist classification artifacts.

Usage:
    uv run python scripts/evaluate_lead_state_classification.py --no-pause
    uv run python scripts/evaluate_lead_state_classification.py --scenario waiting_for_rates
"""

from __future__ import annotations

# ruff: noqa: E402, I001

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.application.ports.llm import LLMClient, LLMCompletionRequest, LLMResult
from app.application.services.llm.lead_state_classification import (
    LeadStateClassificationResult,
    classify_lead_from_conversation,
)
from app.core.config import get_settings
from app.domain.campaigns import PausedSearchTrackCatalogEntry
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.leads import (
    ActivityReliability,
    CanonicalLeadRecord,
    CRMProvider,
    LeadType,
)
from app.infrastructure.providers import build_llm_client
from scripts.seed_paused_search_tracks import TRACK_DEFINITIONS

NOW = datetime(2026, 8, 4, 15, 0, tzinfo=UTC)
DORMANT_THRESHOLD_DAYS = 60
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
NAMESPACE = UUID("22222222-2222-2222-2222-222222222222")


@dataclass(frozen=True)
class EvaluationScenario:
    key: str
    title: str
    description: str
    expected_outcome: str
    expected_track_key: str | None
    events: tuple[CrmConversationEvent, ...]
    lead_last_meaningful_communication_at: datetime | None
    enrollment_signal: str
    expected_handoff_reason: str | None = None
    lead_type: LeadType = LeadType.BUYER
    activity_reliability: ActivityReliability = ActivityReliability.RELIABLE


@dataclass(frozen=True)
class ScenarioEvaluation:
    scenario: EvaluationScenario
    result: LeadStateClassificationResult
    prompt_texts: tuple[str, ...]
    matches: bool


class RecordingLLMClient:
    """Capture production requests without changing the LLM port behavior."""

    def __init__(self, delegate: LLMClient) -> None:
        self._delegate = delegate
        self.requests: list[LLMCompletionRequest] = []

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        return await self._delegate.complete(request)


def _id(value: str) -> UUID:
    return uuid5(NAMESPACE, value)


def _lead(
    *,
    last_meaningful_communication_at: datetime | None,
    lead_type: LeadType,
    activity_reliability: ActivityReliability,
) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=_id("synthetic-lead"),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="synthetic-classification-lead",
        facts_derived_at=NOW,
        source_payload_version="synthetic-evaluation:v1",
        lead_type=lead_type,
        lead_source="synthetic_evaluation",
        lead_stage="long_term_nurture",
        tags=("ai_nurture",),
        primary_email="synthetic.lead@example.test",
        has_email=True,
        activity_reliability=activity_reliability,
        last_meaningful_communication_at=last_meaningful_communication_at,
    )


def _event(
    *,
    scenario_key: str,
    number: int,
    direction: CrmConversationEventDirection,
    content: str,
    occurred_at: datetime,
) -> CrmConversationEvent:
    is_inbound = direction == CrmConversationEventDirection.INBOUND
    return CrmConversationEvent(
        crm_conversation_event_id=_id(f"{scenario_key}:{number}"),
        workspace_id=WORKSPACE_ID,
        lead_id=_id("synthetic-lead"),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        crm_activity_id=f"synthetic-{scenario_key}-{number:02d}",
        activity_type="Text message",
        occurred_at=occurred_at,
        created_at=occurred_at,
        updated_at=occurred_at,
        direction=direction,
        content=content,
        actor_agent_id=None if is_inbound else "synthetic-agent",
        actor_name=None if is_inbound else "Synthetic Agent",
    )


def _paired_events(
    key: str,
    inbound_messages: tuple[str, ...],
    *,
    start: datetime = NOW - timedelta(days=4),
    spacing: timedelta = timedelta(hours=18),
) -> tuple[CrmConversationEvent, ...]:
    outbound_messages = (
        "Hi Jordan, checking in from the team. How are your plans looking?",
        "Thanks for the update. We can follow up when the timing feels right.",
        "I will keep this low pressure. Reply whenever it is useful.",
        "Would a future check-in be helpful, or should we close the loop?",
        "Thanks for staying in touch with us.",
    )
    events: list[CrmConversationEvent] = []
    for index, inbound in enumerate(inbound_messages):
        inbound_at = start + index * spacing
        events.append(
            _event(
                scenario_key=key,
                number=len(events) + 1,
                direction=CrmConversationEventDirection.INBOUND,
                content=inbound,
                occurred_at=inbound_at,
            )
        )
        events.append(
            _event(
                scenario_key=key,
                number=len(events) + 1,
                direction=CrmConversationEventDirection.OUTBOUND,
                content=outbound_messages[index],
                occurred_at=inbound_at + timedelta(hours=2),
            )
        )
    return tuple(events)


def _paused_scenario(
    track_key: str,
    anchor: str,
    *,
    expected_track_key: str | None = None,
) -> EvaluationScenario:
    key = track_key
    events = _paired_events(
        key,
        (
            "We are still interested in buying, but we are not ready to move today.",
            anchor,
            "We still want to buy when this issue is resolved.",
            "Please check back with us later rather than sending active listings now.",
            "We are not asking for an agent call yet; we just need more time.",
        ),
    )
    return EvaluationScenario(
        key=key,
        title=f"Paused-search: {key}",
        description=f"The lead gives a clear {key} reason and remains viable.",
        expected_outcome="paused_search",
        expected_track_key=expected_track_key or key,
        events=events,
        lead_last_meaningful_communication_at=events[-1].occurred_at,
        enrollment_signal="agent_requested_ai_follow_up",
    )


def _seeded_track_catalog() -> tuple[PausedSearchTrackCatalogEntry, ...]:
    return tuple(
        PausedSearchTrackCatalogEntry(
            track_key=definition.key,
            display_name=definition.display_name,
            selection_guidance=definition.selection_guidance,
            track_id=_id(f"seeded-track:{definition.key}"),
            track_version_id=_id(f"seeded-track-version:{definition.key}"),
        )
        for definition in TRACK_DEFINITIONS
    )


def _seeded_paused_scenarios() -> tuple[EvaluationScenario, ...]:
    scenario_messages = {
        "specific_property_only": (
            "We still only want the home at 123 Main Street, but we are not ready to "
            "schedule a showing or speak with an agent. Please do not send alternatives; "
            "check back later.",
        ),
        "waiting_for_inventory": (
            "Nothing available fits our criteria, so please check back when more "
            "inventory appears.",
        ),
        "renter_now_future_buyer": (
            "We are renting for now and may buy after our rental timeline changes.",
        ),
        "lease_expiration": (
            "We want to revisit buying when our lease expires and we move out.",
        ),
        "recently_renewed_lease": (
            "We just renewed our lease, so buying needs to wait until the new timing.",
        ),
        "search_fit_reassessment": (
            "Our criteria and timing no longer fit, and we need to reassess the search.",
        ),
    }
    return tuple(
        EvaluationScenario(
            key=track_key,
            title=f"Seeded paused-search: {track_key}",
            description=f"The lead gives evidence for the seeded {track_key} track.",
            expected_outcome="paused_search",
            expected_track_key=track_key,
            events=_paired_events(track_key, messages),
            lead_last_meaningful_communication_at=NOW,
            enrollment_signal="agent_requested_ai_follow_up",
        )
        for track_key, messages in scenario_messages.items()
    )


def _build_scenarios() -> tuple[EvaluationScenario, ...]:
    scenarios: list[EvaluationScenario] = [
        EvaluationScenario(
            key="dormant_no_conversation",
            title="Dormant: no conversation history",
            description="Agent wants AI follow-up for a lead with no prior conversation.",
            expected_outcome="dormant",
            expected_track_key=None,
            events=(),
            lead_last_meaningful_communication_at=None,
            enrollment_signal="agent_requested_ai_follow_up",
        ),
    ]

    outbound_events = tuple(
        _event(
            scenario_key="dormant_outbound_only",
            number=index + 1,
            direction=CrmConversationEventDirection.OUTBOUND,
            content=(
                "Hi Jordan, this is a low-pressure follow-up from the team. "
                "Let us know if your plans have changed."
            ),
            occurred_at=NOW - timedelta(days=75 - index),
        )
        for index in range(10)
    )
    scenarios.append(
        EvaluationScenario(
            key="dormant_outbound_only",
            title="Dormant: outbound follow-up with no reply",
            description="The agent wants AI to follow up, but the lead never replied.",
            expected_outcome="dormant",
            expected_track_key=None,
            events=outbound_events,
            lead_last_meaningful_communication_at=outbound_events[-1].occurred_at,
            enrollment_signal="agent_requested_ai_follow_up",
        )
    )

    stale_events = _paired_events(
        "dormant_stale_history",
        (
            "We were looking at homes earlier this year.",
            "We are still thinking about it.",
            "Nothing new to report from us.",
            "We are still considering our options.",
            "We will let you know if anything changes.",
        ),
        start=NOW - timedelta(days=82),
        spacing=timedelta(days=3),
    )
    scenarios.append(
        EvaluationScenario(
            key="dormant_stale_history",
            title="Dormant: stale historical conversation",
            description=(
                "Historical interest is older than the dormant threshold with no fresh reply."
            ),
            expected_outcome="dormant",
            expected_track_key=None,
            events=stale_events,
            lead_last_meaningful_communication_at=stale_events[-1].occurred_at,
            enrollment_signal="agent_requested_ai_follow_up",
        )
    )

    reroute_events = _paired_events(
        "dormant_fresh_reply_reroute",
        (
            "We used to be interested, but we went quiet for a while.",
            "We are now thinking about buying again.",
            "We are mainly waiting for rates to improve before taking action.",
            "Please check back after rates settle down.",
            "We would like to talk later, but not schedule a showing today.",
        ),
        start=NOW - timedelta(days=80),
        spacing=timedelta(days=1),
    )
    reroute_events = reroute_events[:-2] + _paired_events(
        "dormant_fresh_reply_reroute_current",
        ("We are thinking about buying again, but we are waiting for rates to improve.",),
        start=NOW - timedelta(hours=3),
        spacing=timedelta(hours=1),
    )
    scenarios.append(
        EvaluationScenario(
            key="dormant_fresh_reply_reroute",
            title="Dormant: fresh reply reroutes to paused-search",
            description="A fresh reply reveals a rates pause, overriding stale dormant history.",
            expected_outcome="paused_search",
            expected_track_key="waiting_for_rates",
            events=reroute_events,
            lead_last_meaningful_communication_at=reroute_events[-1].occurred_at,
            enrollment_signal="agent_requested_ai_follow_up",
        )
    )

    scenarios.extend(
        (
            EvaluationScenario(
                key="review_hold",
                title="Review hold: conflicting and unclear signals",
                description="The lead is contradictory and does not provide a safe route.",
                expected_outcome="review_hold",
                expected_track_key=None,
                events=_paired_events(
                    "review_hold",
                    (
                        "Maybe we want to buy, but maybe not.",
                        "I do not know what we can afford.",
                        "Please send listings, but do not contact me about listings.",
                        "Our plans are unclear right now.",
                        "I am not sure what I want you to do next.",
                    ),
                ),
                lead_last_meaningful_communication_at=NOW - timedelta(hours=2),
                enrollment_signal="agent_requested_ai_follow_up",
            ),
            EvaluationScenario(
                key="human_handoff",
                title="Human handoff: active buyer requests an agent",
                description="The lead has current buying interest and asks for a human call.",
                expected_outcome="human_handoff",
                expected_track_key=None,
                events=_paired_events(
                    "human_handoff",
                    (
                        "We are starting to look seriously again.",
                        "We want a home around $650,000 in Austin.",
                        "Can you send a few options?",
                        "We are hoping to move within three months.",
                        "Can the assigned agent call me today to discuss the next steps?",
                    ),
                ),
                lead_last_meaningful_communication_at=NOW - timedelta(hours=2),
                enrollment_signal="agent_requested_ai_follow_up",
            ),
            EvaluationScenario(
                key="blocked",
                title="Blocked: explicit opt-out",
                description="The lead clearly asks the brokerage to stop outreach.",
                expected_outcome="blocked",
                expected_track_key=None,
                events=_paired_events(
                    "blocked",
                    (
                        "We are not ready to move right now.",
                        "Please keep this low pressure.",
                        "Actually, we are no longer interested.",
                        "There is no need to follow up again.",
                        "Please stop contacting me and remove me from all messages.",
                    ),
                ),
                lead_last_meaningful_communication_at=NOW - timedelta(hours=2),
                enrollment_signal="agent_requested_ai_follow_up",
            ),
        )
    )

    stale_showing_events = _paired_events(
        "stale_showing_request",
        ("Could we see that home this weekend?",),
        start=NOW - timedelta(days=75),
    )
    scenarios.extend(
        (
            EvaluationScenario(
                key="stale_showing_request",
                title="Adversarial: stale showing request",
                description=(
                    "A high-intent showing request is historical and has no fresh lead reply."
                ),
                expected_outcome="dormant",
                expected_track_key=None,
                events=stale_showing_events,
                lead_last_meaningful_communication_at=stale_showing_events[-1].occurred_at,
                enrollment_signal="agent_requested_ai_follow_up",
            ),
            EvaluationScenario(
                key="fresh_showing_after_stale_history",
                title="Adversarial: fresh showing request overrides stale history",
                description=(
                    "A current showing request must still route to a human after old history."
                ),
                expected_outcome="human_handoff",
                expected_track_key=None,
                events=stale_showing_events
                + _paired_events(
                    "fresh_showing_after_stale_history",
                    ("Can you help us schedule a showing this week?",),
                    start=NOW - timedelta(hours=3),
                ),
                lead_last_meaningful_communication_at=NOW - timedelta(hours=1),
                enrollment_signal="agent_requested_ai_follow_up",
                expected_handoff_reason="human_requested",
            ),
            EvaluationScenario(
                key="fresh_property_advice",
                title="Adversarial: fresh property advice request",
                description="The lead asks for advice that requires an agent review.",
                expected_outcome="human_handoff",
                expected_track_key=None,
                events=_paired_events(
                    "fresh_property_advice",
                    ("Is this listing fairly priced, and what should we offer?",),
                    start=NOW - timedelta(hours=3),
                ),
                lead_last_meaningful_communication_at=NOW - timedelta(hours=1),
                enrollment_signal="agent_requested_ai_follow_up",
                expected_handoff_reason="specific_property_or_advice",
            ),
            EvaluationScenario(
                key="active_buyer_interest",
                title="Adversarial: active buyer interest",
                description="The lead expresses current buying intent without asking a question.",
                expected_outcome="human_handoff",
                expected_track_key=None,
                events=_paired_events(
                    "active_buyer_interest",
                    ("We are ready to make an offer and want to move forward now.",),
                    start=NOW - timedelta(hours=3),
                ),
                lead_last_meaningful_communication_at=NOW - timedelta(hours=1),
                enrollment_signal="agent_requested_ai_follow_up",
                expected_handoff_reason="high_interest",
            ),
            EvaluationScenario(
                key="active_seller_interest",
                title="Adversarial: active seller interest",
                description="The seller wants to discuss listing their home with an agent.",
                expected_outcome="human_handoff",
                expected_track_key=None,
                events=_paired_events(
                    "active_seller_interest",
                    ("We are ready to sell our home and want to discuss listing it.",),
                    start=NOW - timedelta(hours=3),
                ),
                lead_last_meaningful_communication_at=NOW - timedelta(hours=1),
                enrollment_signal="agent_requested_ai_follow_up",
                expected_handoff_reason="seller_interest",
                lead_type=LeadType.SELLER,
            ),
            EvaluationScenario(
                key="not_interested_without_opt_out",
                title="Adversarial: no longer interested",
                description="The lead declines further nurture without using an opt-out keyword.",
                expected_outcome="blocked",
                expected_track_key=None,
                events=_paired_events(
                    "not_interested_without_opt_out",
                    (
                        "We are no longer interested in buying.",
                        "Please do not follow up about this search again.",
                    ),
                    start=NOW - timedelta(hours=6),
                    spacing=timedelta(hours=1),
                ),
                lead_last_meaningful_communication_at=NOW - timedelta(hours=1),
                enrollment_signal="agent_requested_ai_follow_up",
            ),
            EvaluationScenario(
                key="contradictory_current_signals",
                title="Adversarial: contradictory current signals",
                description="The lead mixes urgency, uncertainty, and conflicting next steps.",
                expected_outcome="review_hold",
                expected_track_key=None,
                events=_paired_events(
                    "contradictory_current_signals",
                    (
                        "We want to buy immediately if the right home appears.",
                        "Do not send listings or call us until we decide what we want.",
                        "We may be ready next month, but we are not sure.",
                    ),
                    start=NOW - timedelta(hours=6),
                    spacing=timedelta(hours=1),
                ),
                lead_last_meaningful_communication_at=NOW - timedelta(hours=1),
                enrollment_signal="agent_requested_ai_follow_up",
            ),
        )
    )

    anchors = {
        "renter_now_future_buyer_lease_context": (
            "We renewed our lease through March, so we are renting temporarily."
        ),
        "timing_not_right": (
            "The timing is not right for us until next spring."
        ),
        "waiting_for_rates": (
            "Mortgage rates are too high, so we are waiting for rates to improve."
        ),
        "financial_prep": (
            "We need more time to save and get financially prepared for the purchase."
        ),
        "personal_life_timing": (
            "A new baby and a job change mean our personal timing is not right."
        ),
        "other_known_pause": (
            "We have an unresolved permit paperwork issue unrelated to rates, inventory, "
            "renting, finances, or personal timing, so we need that resolved first."
        ),
    }
    scenarios.extend(
        _paused_scenario(
            track_key,
            anchor,
            expected_track_key=(
                "renter_now_future_buyer"
                if track_key == "renter_now_future_buyer_lease_context"
                else None
            ),
        )
        for track_key, anchor in anchors.items()
    )
    scenarios.extend(_seeded_paused_scenarios())
    return tuple(scenarios)


def _parse_args() -> argparse.Namespace:
    scenarios = _build_scenarios()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=tuple(scenario.key for scenario in scenarios),
        help="Run only one scenario. By default, run all sequentially.",
    )
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help="Do not wait for Enter between scenarios.",
    )
    parser.add_argument(
        "--model",
        help="Optional model override; otherwise use OPENROUTER_MODEL from settings.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Run each selected scenario this many times to observe model variability.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Write structured scenario results and aggregate metrics to this JSON file.",
    )
    return parser.parse_args()


def _print_conversation(scenario: EvaluationScenario) -> None:
    print("Conversation:")
    if not scenario.events:
        print("  <no prior CRM conversation events>")
        return
    for index, event in enumerate(scenario.events, start=1):
        speaker = "LEAD" if event.direction == CrmConversationEventDirection.INBOUND else "OUTBOUND"
        print(f"  {index:02d}. {event.occurred_at.isoformat()} {speaker}: {event.content}")


def _classification_payload(result: LeadStateClassificationResult) -> dict[str, object]:
    classification = result
    return {
        "status": classification.status.value,
        "outcome": classification.outcome.value if classification.outcome else None,
        "selected_track_key": classification.selected_track_key,
        "track_selection_status": (
            classification.track_selection_status.value
            if classification.track_selection_status
            else None
        ),
        "track_version_id": (
            str(classification.track_version_id) if classification.track_version_id else None
        ),
        "handoff_reason_code": (
            classification.handoff_reason_code.value if classification.handoff_reason_code else None
        ),
        "confidence": classification.confidence,
        "evidence": classification.evidence,
        "summary": classification.summary,
        "model": classification.model,
        "prompt_version": classification.prompt_version,
        "latency_ms": classification.latency_ms,
        "usage_tokens": classification.usage_tokens,
        "raw_llm_response": classification.raw_llm_response_text,
        "parsed_llm_response": classification.parsed_llm_response,
        "validation_error": classification.validation_error,
        "reasons": [reason.value for reason in classification.reasons],
        "policy_trace": classification.input_context.get("classifier_policy"),
    }


def _scenario_catalog(
    scenario: EvaluationScenario,
) -> tuple[PausedSearchTrackCatalogEntry, ...]:
    if scenario.expected_track_key is None:
        return ()
    if scenario.expected_track_key in {definition.key for definition in TRACK_DEFINITIONS}:
        return _seeded_track_catalog()
    track_key = scenario.expected_track_key
    return (
        PausedSearchTrackCatalogEntry(
            track_key=track_key,
            display_name=track_key.replace("_", " ").title(),
            selection_guidance=(
                f"Select this category when the conversation clearly matches {scenario.description}"
            ),
            track_id=uuid5(NAMESPACE, f"evaluation-track:{track_key}"),
            track_version_id=uuid5(NAMESPACE, f"evaluation-track-version:{track_key}"),
        ),
    )


def _matches(scenario: EvaluationScenario, result: LeadStateClassificationResult) -> bool:
    return (
        result.status.value == "classified"
        and result.outcome is not None
        and result.outcome.value == scenario.expected_outcome
        and (
            scenario.expected_track_key is None
            or result.selected_track_key == scenario.expected_track_key
        )
        and (
            scenario.expected_handoff_reason is None
            or (
                result.handoff_reason_code is not None
                and result.handoff_reason_code.value == scenario.expected_handoff_reason
            )
        )
    )


def _print_result(
    scenario: EvaluationScenario,
    result: LeadStateClassificationResult,
    client: RecordingLLMClient,
) -> bool:
    print("Expected:")
    print(f"  outcome={scenario.expected_outcome}")
    print(f"  selected_track_key={scenario.expected_track_key}")
    print(f"  handoff_reason_code={scenario.expected_handoff_reason}")
    print("Exact prompt(s) sent:")
    for index, request in enumerate(client.requests, start=1):
        print(f"--- request {index}: {request.prompt_version} ---")
        print(request.prompt)
    print("Classification result:")
    print(json.dumps(_classification_payload(result), indent=2, sort_keys=True))
    matches = _matches(scenario, result)
    print(f"Comparison: {'PASS' if matches else 'REVIEW'}")
    return matches


async def _run_scenario(
    scenario: EvaluationScenario,
    *,
    llm_client: LLMClient,
    model: str | None,
    pause_between: bool,
) -> ScenarioEvaluation:
    recording_client = RecordingLLMClient(llm_client)
    print("\n" + "=" * 100)
    print(f"Scenario: {scenario.title} [{scenario.key}]")
    print(f"Description: {scenario.description}")
    print(f"Enrollment signal: {scenario.enrollment_signal}")
    _print_conversation(scenario)
    result = await classify_lead_from_conversation(
        lead=_lead(
            last_meaningful_communication_at=scenario.lead_last_meaningful_communication_at,
            lead_type=scenario.lead_type,
            activity_reliability=scenario.activity_reliability,
        ),
        now=NOW,
        crm_conversation_events=scenario.events,
        llm_client=recording_client,
        paused_search_catalog=_scenario_catalog(scenario),
        dormant_threshold_days=DORMANT_THRESHOLD_DAYS,
        model=model,
    )
    matches = _print_result(scenario, result, recording_client)
    if pause_between:
        try:
            await asyncio.to_thread(input, "\nPress Enter for the next scenario...")
        except EOFError:
            pass
    return ScenarioEvaluation(
        scenario=scenario,
        result=result,
        prompt_texts=tuple(request.prompt for request in recording_client.requests),
        matches=matches,
    )


def _aggregate_metrics(evaluations: tuple[ScenarioEvaluation, ...]) -> dict[str, object]:
    expected_counts = Counter(item.scenario.expected_outcome for item in evaluations)
    actual_counts = Counter(
        item.result.outcome.value if item.result.outcome else "rejected" for item in evaluations
    )
    confusion_counts = Counter(
        (
            item.scenario.expected_outcome,
            item.result.outcome.value if item.result.outcome else "rejected",
        )
        for item in evaluations
    )
    route_breakdown: dict[str, dict[str, int]] = {}
    for expected, total in expected_counts.items():
        route_items = [item for item in evaluations if item.scenario.expected_outcome == expected]
        route_breakdown[expected] = {
            "total": total,
            "pass": sum(item.matches for item in route_items),
            "review": sum(not item.matches for item in route_items),
        }
    scenario_signatures: dict[str, set[tuple[str, str | None]]] = {}
    for item in evaluations:
        scenario_signatures.setdefault(item.scenario.key, set()).add(
            (
                item.result.outcome.value if item.result.outcome else "rejected",
                item.result.selected_track_key,
            )
        )
    confidences = [
        item.result.confidence for item in evaluations if item.result.confidence is not None
    ]
    latencies = [
        item.result.latency_ms for item in evaluations if item.result.latency_ms is not None
    ]
    usage_tokens = [
        item.result.usage_tokens for item in evaluations if item.result.usage_tokens is not None
    ]
    unexpected_handoffs = sum(
        item.result.outcome is not None
        and item.result.outcome.value == "human_handoff"
        and item.scenario.expected_outcome != "human_handoff"
        for item in evaluations
    )
    unexpected_blocks = sum(
        item.result.outcome is not None
        and item.result.outcome.value == "blocked"
        and item.scenario.expected_outcome != "blocked"
        for item in evaluations
    )
    return {
        "total_runs": len(evaluations),
        "passes": sum(item.matches for item in evaluations),
        "reviews": sum(not item.matches for item in evaluations),
        "pass_rate": (
            sum(item.matches for item in evaluations) / len(evaluations) if evaluations else None
        ),
        "classified_runs": sum(item.result.status.value == "classified" for item in evaluations),
        "rejected_runs": sum(item.result.status.value == "rejected" for item in evaluations),
        "expected_outcomes": dict(sorted(expected_counts.items())),
        "actual_outcomes": dict(sorted(actual_counts.items())),
        "outcome_confusion": {
            f"{expected}->{actual}": count
            for (expected, actual), count in sorted(confusion_counts.items())
        },
        "route_breakdown": dict(sorted(route_breakdown.items())),
        "safety_signals": {
            "unexpected_human_handoffs": unexpected_handoffs,
            "unexpected_blocked_routes": unexpected_blocks,
            "unstable_scenarios": sorted(
                key for key, signatures in scenario_signatures.items() if len(signatures) > 1
            ),
        },
        "average_confidence": (sum(confidences) / len(confidences) if confidences else None),
        "average_latency_ms": sum(latencies) / len(latencies) if latencies else None,
        "total_usage_tokens": sum(usage_tokens) if usage_tokens else 0,
    }


def _print_summary(metrics: dict[str, object]) -> None:
    print("\n" + "=" * 100)
    print("Evaluation summary")
    print(f"Runs: {metrics['total_runs']}")
    print(f"Passes: {metrics['passes']}")
    print(f"Reviews: {metrics['reviews']}")
    print(
        f"Pass rate: {metrics['pass_rate']:.1%}"
        if metrics["pass_rate"] is not None
        else "Pass rate: n/a"
    )
    print(f"Classified: {metrics['classified_runs']} | Rejected: {metrics['rejected_runs']}")
    print("\nExpected route breakdown:")
    route_breakdown = metrics["route_breakdown"]
    if isinstance(route_breakdown, dict):
        for route, counts in route_breakdown.items():
            print(
                f"  {route}: {counts['pass']}/{counts['total']} pass"
                if isinstance(counts, dict)
                else f"  {route}: {counts}"
            )
    print("\nOutcome confusion:")
    confusion = metrics["outcome_confusion"]
    if isinstance(confusion, dict):
        for route, count in confusion.items():
            print(f"  {route}: {count}")
    safety_signals = metrics["safety_signals"]
    if isinstance(safety_signals, dict):
        print("\nSafety signals:")
        print(f"  Unexpected human handoffs: {safety_signals['unexpected_human_handoffs']}")
        print(f"  Unexpected blocked routes: {safety_signals['unexpected_blocked_routes']}")
        print(
            "  Unstable scenarios: " + (", ".join(safety_signals["unstable_scenarios"]) or "none")
        )
    print(f"Average confidence: {metrics['average_confidence'] or 'n/a'}")
    print(f"Average latency: {metrics['average_latency_ms'] or 'n/a'} ms")
    print(f"Total usage tokens: {metrics['total_usage_tokens']}")


def _json_event(event: CrmConversationEvent) -> dict[str, object]:
    return {
        "event_id": event.crm_activity_id,
        "direction": event.direction.value if event.direction else None,
        "content": event.content,
        "occurred_at": event.occurred_at.isoformat(),
    }


def _json_evaluation(item: ScenarioEvaluation) -> dict[str, object]:
    scenario = item.scenario
    return {
        "key": scenario.key,
        "title": scenario.title,
        "description": scenario.description,
        "expected": {
            "outcome": scenario.expected_outcome,
            "selected_track_key": scenario.expected_track_key,
            "handoff_reason_code": scenario.expected_handoff_reason,
        },
        "events": [_json_event(event) for event in scenario.events],
        "actual": _classification_payload(item.result),
        "prompts": list(item.prompt_texts),
        "comparison": "PASS" if item.matches else "REVIEW",
    }


def _write_json_report(
    path: Path,
    *,
    model: str,
    evaluations: tuple[ScenarioEvaluation, ...],
    metrics: dict[str, object],
) -> None:
    report = {
        "generated_at": NOW.isoformat(),
        "model": model,
        "prompt_source": "production classifier",
        "dormant_threshold_days": DORMANT_THRESHOLD_DAYS,
        "metrics": metrics,
        "evaluations": [_json_evaluation(item) for item in evaluations],
    }
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Structured report written to {path}")


async def _main() -> int:
    args = _parse_args()
    settings = get_settings()
    llm_client = build_llm_client(settings)
    scenarios = _build_scenarios()
    if args.repeat < 1:
        raise SystemExit("--repeat must be at least 1")
    if args.scenario:
        scenarios = tuple(scenario for scenario in scenarios if scenario.key == args.scenario)
    model = args.model or settings.openrouter_model
    print(f"Live LLM evaluation; model={model}; prompt source=production classifier")
    print(
        "Admin prompt note: classification instructions are currently code-defined; "
        "the exact prompt sent is printed below."
    )
    evaluations: list[ScenarioEvaluation] = []
    for repeat in range(args.repeat):
        if args.repeat > 1:
            print(f"\n===== Evaluation repeat {repeat + 1}/{args.repeat} =====")
        for scenario in scenarios:
            evaluations.append(
                await _run_scenario(
                    scenario,
                    llm_client=llm_client,
                    model=model,
                    pause_between=not args.no_pause,
                )
            )
    evaluation_tuple = tuple(evaluations)
    metrics = _aggregate_metrics(evaluation_tuple)
    _print_summary(metrics)
    if args.json_output:
        _write_json_report(
            args.json_output,
            model=model,
            evaluations=evaluation_tuple,
            metrics=metrics,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
