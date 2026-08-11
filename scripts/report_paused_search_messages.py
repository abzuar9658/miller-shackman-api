"""Export paused-search messages for synthetic conversation scenarios.

The command is read-only with respect to the application. It uses synthetic lead
data and sink email/SMS providers, then writes human-readable logs and one JSON
manifest. The default stub mode needs no API credentials. ``--mode live`` uses
the configured LLM, but still never sends email/SMS or writes CRM/Postgres.

Usage:
    uv run python scripts/report_paused_search_messages.py
    uv run python scripts/report_paused_search_messages.py --track lease_expiration
    uv run python scripts/report_paused_search_messages.py --scenario new-timeline
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.ports.llm import LLMClient, LLMCompletionRequest, LLMResult
from app.core.config import get_settings
from app.domain.campaigns import PausedSearchTrackStep
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.infrastructure.messaging.sink import SinkEmailProvider, SinkSMSProvider
from app.infrastructure.providers import build_llm_client
from scripts.seed_paused_search_tracks import TRACK_DEFINITIONS, _config
from tests.application.use_cases.paused_search_time_machine import PausedSearchTimeMachine
from tests.application.use_cases.test_paused_search_time_machine import (
    NOW,
    _machine,
    _version,
)

OUTPUT_DIRECTORY = Path(__file__).resolve().parents[1] / "logs" / "paused-search-report"
TRACK_KEYS = tuple(definition.key for definition in TRACK_DEFINITIONS)


@dataclass(frozen=True)
class ConversationScenario:
    key: str
    lead_message: str
    policy_outcome: str
    policy_reason: str
    prior_context: str | None = None  # Earlier conversation context for richer tests


SCENARIOS = (
    ConversationScenario(
        "no-response",
        "(No inbound reply after the prior conversation.)",
        "continue_ai",
        "No inbound signal changes the paused-search workflow.",
        "I'm looking for a 2-bedroom condo in Brooklyn, ideally near Prospect Park. "
        "Budget is around $750k. Want to move in the spring.",
    ),
    ConversationScenario(
        "still-waiting",
        "We are still waiting. Please check back next spring.",
        "continue_ai",
        "The lead confirms the existing timing; continue only with bounded check-ins.",
        "Looking for a 3BR house in Williamsburg or Greenpoint, up to $1.2M. "
        "Need to wait until my lease ends in May.",
    ),
    ConversationScenario(
        "new-timeline",
        "Our timing changed. We may be ready to look again in about three months.",
        "continue_ai",
        "The timing context can be used for a future check-in; it does not authorize advice.",
        "Interested in a 2BR apartment in Park Slope with outdoor space, budget $850k. "
        "Was waiting for rates to drop.",
    ),
    ConversationScenario(
        "ambiguous",
        "I am not sure yet, maybe later.",
        "continue_ai_with_caution",
        "Keep the message low-pressure and pause if the next reply remains unclear.",
        "Want a 1BR condo in DUMBO or Brooklyn Heights, max $600k. "
        "Waiting to save more for down payment.",
    ),
    ConversationScenario(
        "listing-question",
        "Can you tell me whether that property is still available and what I should offer?",
        "human_handoff",
        "Property status, offers, and advice require the assigned agent.",
        "Saw a listing for a 2BR at 123 Atlantic Ave in Boerum Hill for $900k. Very interested.",
    ),
    ConversationScenario(
        "buying-interest",
        "We are ready to buy and would like to see homes this week.",
        "human_handoff",
        "Meaningful buying interest stops AI outreach and creates a human handoff.",
        "Looking for 3BR townhouse in Carroll Gardens or Cobble Hill, budget up to $2M.",
    ),
    ConversationScenario(
        "selling-interest",
        "We may sell our home and want to talk through the options.",
        "human_handoff",
        "Selling questions require a human agent.",
        "Own a 4BR brownstone in Fort Greene, considering selling to downsize.",
    ),
    ConversationScenario(
        "human-request",
        "Please have an agent call me.",
        "human_handoff",
        "An explicit request for a person stops AI outreach.",
        "Interested in new construction condos in Gowanus, 2-3BR, $800-950k.",
    ),
    ConversationScenario(
        "opt-out",
        "Please stop texting and emailing me.",
        "suppressed",
        "Opt-out suppresses automated outreach on every channel.",
        None,  # No prior context needed for opt-out
    ),
)
SCENARIO_KEYS = tuple(item.key for item in SCENARIOS)
_SCENARIO_BY_KEY = {item.key: item for item in SCENARIOS}


class PromptCapturingLLM:
    """Wrapper that captures prompts for debugging."""

    def __init__(self, inner: LLMClient, *, show_prompts: bool) -> None:
        self.inner = inner
        self.show_prompts = show_prompts
        self.captured_prompts: list[tuple[str, str, LLMCompletionRequest]] = []
        self.query_extractions: list[tuple[str, LLMCompletionRequest]] = []

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        # Capture query extraction prompts separately
        if request.prompt_version.startswith("outbound_query_extraction"):
            if self.show_prompts:
                self.query_extractions.append((request.prompt_version, request))
        else:
            channel = "EMAIL" if '"channel": "email"' in request.prompt else "SMS"
            if self.show_prompts:
                self.captured_prompts.append((channel, request.prompt_version, request))
        return await self.inner.complete(request)

    async def aclose(self) -> None:
        close = getattr(self.inner, "aclose", None)
        if close is not None:
            await close()


class ScenarioStubLLM(LLMClient):
    """Deterministic drafting adapter for safe local inspection."""

    def __init__(self, scenario: ConversationScenario) -> None:
        self.scenario = scenario

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        prompt = request.prompt.lower()
        if request.prompt_version.startswith("outbound_query_extraction"):
            text = json.dumps(
                {
                    "search_type": "sale",
                    "location": "the lead's stated area" if "timeline" in prompt else None,
                    "keywords": self.scenario.lead_message[:120],
                    "confidence": 0.96,
                    "reasons": ["synthetic scenario context"],
                }
            )
        else:
            is_sms = '"channel": "sms"' in prompt
            body = _stub_body(self.scenario, is_sms=is_sms)
            text = json.dumps(
                {
                    "body": body,
                    "subject": None if is_sms else f"A quick {self.scenario.key} check-in",
                    "confidence": 0.96,
                    "personalization_notes": [
                        f"Synthetic conversation scenario: {self.scenario.key}."
                    ],
                    "safety_flags": [],
                }
            )
        return LLMResult(
            text=text,
            model="diagnostic/stub",
            prompt_version=request.prompt_version,
            latency_ms=0,
            usage_tokens=0,
        )


def _stub_body(scenario: ConversationScenario, *, is_sms: bool) -> str:
    prefix = "Hi Jordan, " if not is_sms else "Hi Jordan — "
    bodies = {
        "no-response": "just checking in on your paused search. Would a future update be useful?",
        "still-waiting": "thanks for the update. Should we keep your timing as-is for now?",
        "new-timeline": "thanks for the timing update. When would you like us to reconnect?",
        "ambiguous": "no pressure — would you like us to check in again later?",
    }
    return prefix + bodies.get(scenario.key, "your agent will follow up with you directly.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", choices=TRACK_KEYS, help="Run one seeded track.")
    parser.add_argument("--scenario", choices=SCENARIO_KEYS, help="Run one conversation scenario.")
    parser.add_argument(
        "--mode",
        choices=("stub", "live"),
        default="stub",
        help="Use deterministic local drafting or the configured LLM (default: stub).",
    )
    parser.add_argument(
        "--show-prompts",
        action="store_true",
        help="Include the full LLM prompt before each generated message.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIRECTORY,
        help="Directory for JSON manifest and per-case .log files.",
    )
    return parser


def _steps(config: Any, version_id: UUID) -> tuple[PausedSearchTrackStep, ...]:
    return tuple(
        PausedSearchTrackStep(
            step_id=uuid5(NAMESPACE_URL, f"paused-search-report:{index}"),
            workspace_id=UUID("50000000-0000-0000-0000-000000000001"),
            track_version_id=version_id,
            step_order=index,
            phase=step.phase,
            channel=step.channel,
            delay_hours=step.delay_hours,
            message_goal=step.message_goal,
            template_key=step.template_key,
            max_attempts=step.max_attempts,
            review_required=step.review_required,
            created_at=NOW,
            timing_basis=step.timing_basis,
            fallback_channel=step.fallback_channel,
            interval_days=step.interval_days,
            max_occurrences=step.max_occurrences,
            template_version_id=step.template_version_id,
            template_profile=step.template_profile,
            action=step.action,
        )
        for index, step in enumerate(config.steps, start=1)
    )


def _conversation_event(
    scenario: ConversationScenario,
    lead_id: UUID,
) -> tuple[CrmConversationEvent, ...]:
    events: list[CrmConversationEvent] = []

    # Add prior context as an earlier inbound message (if present)
    if scenario.prior_context:
        events.append(
            CrmConversationEvent(
                crm_conversation_event_id=uuid5(NAMESPACE_URL, f"scenario:{scenario.key}:prior"),
                workspace_id=UUID("50000000-0000-0000-0000-000000000001"),
                lead_id=lead_id,
                crm_provider="diagnostic",
                crm_activity_id=f"scenario-{scenario.key}-prior",
                activity_type="email",
                occurred_at=NOW - timedelta(days=30),  # Original inquiry 30 days ago
                created_at=NOW - timedelta(days=30),
                updated_at=NOW - timedelta(days=30),
                direction=CrmConversationEventDirection.INBOUND,
                content=scenario.prior_context,
                source_payload_version="diagnostic/v1",
            )
        )

    # Add current reply (if not "no-response")
    if scenario.key != "no-response":
        events.append(
            CrmConversationEvent(
                crm_conversation_event_id=uuid5(NAMESPACE_URL, f"scenario:{scenario.key}"),
                workspace_id=UUID("50000000-0000-0000-0000-000000000001"),
                lead_id=lead_id,
                crm_provider="diagnostic",
                crm_activity_id=f"scenario-{scenario.key}",
                activity_type="sms",
                occurred_at=NOW - timedelta(days=3),
                created_at=NOW - timedelta(days=3),
                updated_at=NOW - timedelta(days=3),
                direction=CrmConversationEventDirection.INBOUND,
                content=scenario.lead_message,
                source_payload_version="diagnostic/v1",
            )
        )
    elif scenario.prior_context:
        # For "no-response", still include prior context
        pass

    return tuple(events)


async def _run_case(
    track: str, scenario: ConversationScenario, mode: str, *, show_prompts: bool = False
) -> dict[str, Any]:
    definition = next(item for item in TRACK_DEFINITIONS if item.key == track)
    config = _config(definition)
    version = replace(
        _version(),
        allowed_channels=config.allowed_channels,
        fallback_timing_policy=config.fallback_timing_policy,
        maintenance_interval_days=config.maintenance_interval_days,
        reactivation_window_days=config.reactivation_window_days,
        max_total_touches=config.max_total_touches,
        default_pause_duration_days=config.default_pause_duration_days,
        max_duration_days=config.max_duration_days,
        terminal_behavior=config.terminal_behavior,
        track_mode=config.track_mode,
        interim_contact_policy=config.interim_contact_policy,
        reply_policy=config.reply_policy,
        channel_sequence=config.channel_sequence,
        max_cycles=config.max_cycles,
        max_ai_interactions=config.max_ai_interactions,
        restart_delay_days=config.restart_delay_days,
        email_writing_purpose=config.email_writing_purpose,
        sms_writing_purpose=config.sms_writing_purpose,
    )
    steps = _steps(config, version.track_version_id)
    machine = _machine(version=version, steps=steps, reengagement_days=180)
    events = _conversation_event(scenario, machine.lead_id)
    machine.crm_conversation_event_repository.saved = list(events)
    machine.email_provider = cast(Any, SinkEmailProvider())
    machine.sms_provider = cast(Any, SinkSMSProvider())
    llm: LLMClient = ScenarioStubLLM(scenario)
    if mode == "live":
        llm = build_llm_client(get_settings())
    prompt_capturing_llm = PromptCapturingLLM(llm, show_prompts=show_prompts)
    machine.llm_client = cast(Any, prompt_capturing_llm)
    messages: list[dict[str, Any]] = []
    try:
        if scenario.policy_outcome not in {"continue_ai", "continue_ai_with_caution"}:
            return _case_result(
                track, scenario, mode, messages, machine, steps, prompt_capturing_llm
            )
        for _ in range(16):
            scheduled = await machine.schedule()
            if scheduled.scheduled_for is None or scheduled.cadence_step_id is None:
                if machine.lead.reengagement_not_before is not None:
                    boundary = machine.lead.reengagement_not_before - timedelta(
                        days=version.reactivation_window_days
                    )
                    if machine.now < boundary:
                        machine.now = boundary
                        continue
                break
            machine.now = max(machine.now, scheduled.scheduled_for)
            email_count = len(machine.email_provider.messages)
            sms_count = len(machine.sms_provider.messages)
            result = await machine.execute(scheduled)
            step = next(item for item in steps if item.step_id == scheduled.cadence_step_id)
            providers = [
                *machine.email_provider.messages[email_count:],
                *machine.sms_provider.messages[sms_count:],
            ]
            for provider_message in providers:
                payload = provider_message.model_dump(mode="json")
                payload.update(
                    {
                        "phase": step.phase.value,
                        "channel": step.channel.value,
                        "step_id": str(step.step_id),
                        "step_order": step.step_order,
                        "scheduled_for": scheduled.scheduled_for.isoformat(),
                        "execution_status": result.status.value,
                    }
                )
                messages.append(payload)
            if not result.has_more_steps or result.status.value not in {
                "sent",
                "already_sent",
                "skipped",
            }:
                break
    finally:
        await prompt_capturing_llm.aclose()
    return _case_result(track, scenario, mode, messages, machine, steps, prompt_capturing_llm)


def _case_result(
    track: str,
    scenario: ConversationScenario,
    mode: str,
    messages: list[dict[str, Any]],
    machine: PausedSearchTimeMachine,
    steps: tuple[PausedSearchTrackStep, ...],
    prompt_capturing_llm: PromptCapturingLLM,
) -> dict[str, Any]:
    snapshot = machine.snapshot()
    return {
        "track": track,
        "track_display_name": next(
            item.display_name for item in TRACK_DEFINITIONS if item.key == track
        ),
        "scenario": scenario.key,
        "conversation": scenario.lead_message,
        "mode": mode,
        "policy_outcome": scenario.policy_outcome,
        "policy_reason": scenario.policy_reason,
        "messages": messages,
        "query_extractions": [
            {
                "prompt_version": version,
                "prompt": request.prompt,
                "model": request.model,
                "temperature": request.temperature,
            }
            for version, request in prompt_capturing_llm.query_extractions
        ],
        "prompts": [
            {
                "channel": channel,
                "prompt_version": version,
                "prompt": request.prompt,
                "model": request.model,
                "temperature": request.temperature,
            }
            for channel, version, request in prompt_capturing_llm.captured_prompts
        ],
        "workflow_state": snapshot.workflow.state.value,
        "schedule_statuses": snapshot.schedule_statuses,
        "execution_statuses": snapshot.execution_statuses,
        "execution_skip_reasons": tuple(
            execution.skip_reason for execution in machine.executions if execution.skip_reason
        ),
        "configured_steps": len(steps),
        "note": "Synthetic report only; no CRM, Postgres, Temporal, email, or SMS writes.",
    }


def _log_text(case: dict[str, Any]) -> str:
    lines = [
        f"TRACK: {case['track_display_name']} ({case['track']})",
        f"SCENARIO: {case['scenario']}",
        f"CONVERSATION: {case['conversation']}",
        f"POLICY OUTCOME: {case['policy_outcome']}",
        f"POLICY REASON: {case['policy_reason']}",
        f"WORKFLOW STATE: {case['workflow_state']}",
        "",
    ]

    # Show query extraction prompts if present
    if case.get("query_extractions"):
        for idx, extraction in enumerate(case["query_extractions"], start=1):
            lines.extend([
                f"{'=' * 80}",
                f"QUERY EXTRACTION {idx}",
                f"{'=' * 80}",
                f"Model: {extraction.get('model', 'N/A')}",
                f"Temperature: {extraction.get('temperature', 'N/A')}",
                f"Prompt Version: {extraction['prompt_version']}",
                "",
                extraction["prompt"],
                "",
                f"{'=' * 80}",
                "",
            ])

    if not case["messages"]:
        lines.append("MESSAGES: none (AI outreach is held by the policy outcome).")

    prompt_index = 0
    for index, message in enumerate(case["messages"], start=1):
        # Show the prompt before the message if available
        if case.get("prompts") and prompt_index < len(case["prompts"]):
            prompt_info = case["prompts"][prompt_index]
            lines.extend(
                [
                    f"{'=' * 80}",
                    f"PROMPT FOR MESSAGE {index} ({prompt_info['channel']})",
                    f"{'=' * 80}",
                    f"Model: {prompt_info.get('model', 'N/A')}",
                    f"Temperature: {prompt_info.get('temperature', 'N/A')}",
                    f"Prompt Version: {prompt_info['prompt_version']}",
                    "",
                    prompt_info["prompt"],
                    "",
                    f"{'=' * 80}",
                    "",
                ]
            )
            prompt_index += 1

        lines.extend(
            [
                f"MESSAGE {index}: {message.get('phase')} / {message.get('channel', '').upper()}",
                f"STEP: {message.get('step_order')} ({message.get('step_id')})",
                f"SCHEDULED FOR: {message.get('scheduled_for')}",
                f"TO: {message.get('to_email') or message.get('to_phone')}",
                f"SUBJECT: {message.get('subject') or '(none)'}",
                f"BODY: {message.get('body')}",
                "",
            ]
        )
    lines.append(case["note"])
    return "\n".join(lines) + "\n"


async def _run(args: argparse.Namespace) -> int:
    tracks = (args.track,) if args.track else TRACK_KEYS
    scenarios = (_SCENARIO_BY_KEY[args.scenario],) if args.scenario else SCENARIOS
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    for track in tracks:
        for scenario in scenarios:
            case = await _run_case(track, scenario, args.mode, show_prompts=args.show_prompts)
            cases.append(case)
            log_path = args.output_dir / f"{track}--{scenario.key}.log"
            log_path.write_text(_log_text(case), encoding="utf-8")
            print(f"Log written to: {log_path}")
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": args.mode,
        "tracks": tracks,
        "scenarios": [scenario.key for scenario in scenarios],
        "cases": cases,
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Manifest written to: {manifest_path}")
    print(f"Cases: {len(cases)} | messages: {sum(len(case['messages']) for case in cases)}")
    return 0


def main() -> int:
    return asyncio.run(_run(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())