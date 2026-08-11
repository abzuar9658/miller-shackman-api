"""Print a live-LLM paused-search cadence simulation.

This diagnostic uses the configured real LLM and capture-only email/SMS
providers. It never writes to Postgres, CRM, Temporal, email, or SMS.

Usage:
    uv run python scripts/paused_search_time_machine.py
    uv run python scripts/paused_search_time_machine.py --track waiting-for-rates
"""

from __future__ import annotations

import argparse
import asyncio
import io
import re
import sys
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.use_cases.paused_search_track_admin import PausedSearchTrackStepInput
from app.core.config import get_settings
from app.domain.campaigns import PausedSearchTrackStep
from app.infrastructure.messaging.sink import SinkEmailProvider, SinkSMSProvider
from app.infrastructure.providers import build_llm_client
from scripts.seed_paused_search_tracks import TRACK_DEFINITIONS, _config
from tests.application.use_cases.paused_search_time_machine import PausedSearchTimeMachine
from tests.application.use_cases.test_paused_search_time_machine import (
    NOW,
    _machine,
    _version,
)

LOG_DIRECTORY = Path(__file__).resolve().parents[1] / "logs"
TRACK_KEYS = tuple(definition.key for definition in TRACK_DEFINITIONS)
TRACK_CHOICES = TRACK_KEYS + tuple(key.replace("_", "-") for key in TRACK_KEYS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--track",
        default="waiting-for-rates",
        choices=TRACK_CHOICES,
        help="Seeded paused-search track to simulate.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run every seeded paused-search track and write one log per track.",
    )
    return parser


async def run_machine(track: str) -> int:
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
    steps = _domain_steps(config.steps, version.track_version_id)
    machine = _machine(version=version, steps=steps, reengagement_days=180)
    settings = get_settings()
    machine.llm_client = build_llm_client(settings)
    machine.email_provider = SinkEmailProvider()
    machine.sms_provider = SinkSMSProvider()
    try:
        await _print_run(machine, track=track, start=NOW)
        snapshot = machine.snapshot()
    finally:
        close = getattr(machine.llm_client, "aclose", None)
        if close is not None:
            await close()
    passed = all(
        status in {"sent", "already_sent", "skipped"}
        for status in snapshot.execution_statuses
    )
    print("\nRESULT: " + ("PASS" if passed else "FAIL"))
    print(f"Messages sent: {len(snapshot.sent_channels)}")
    print(f"Channels: {', '.join(snapshot.sent_channels)}")
    print(f"Configured max touches: {version.max_total_touches}")
    print(f"Final workflow state: {snapshot.workflow.state.value}")
    return 0 if passed else 1


async def _print_run(machine: PausedSearchTimeMachine, *, track: str, start: datetime) -> None:
    print(f"TRACK: {track}")
    print("MODE: live LLM with sink email/SMS providers\n")
    previous = start
    while True:
        scheduled = await machine.schedule()
        if scheduled.scheduled_for is None or scheduled.cadence_step_id is None:
            boundary = (
                machine.lead.reengagement_not_before
                - timedelta(days=machine.track_version.reactivation_window_days)
                if machine.lead.reengagement_not_before is not None
                else None
            )
            if boundary is not None and machine.now < boundary:
                print(
                    f"REACTIVATION WINDOW: {machine.now.isoformat()} -> "
                    f"{boundary.isoformat()}"
                )
                previous = machine.now
                machine.now = boundary
                continue
            print(f"Terminal scheduler result: {scheduled.status.value}")
            if scheduled.skip_reason:
                print(f"Reason: {scheduled.skip_reason}")
            return
        machine.now = max(machine.now, scheduled.scheduled_for)
        print(
            f"TIME MACHINE: {previous.isoformat()} -> {machine.now.isoformat()}"
            f" ({(machine.now - start).days} days elapsed)"
        )
        email_count = len(machine.email_provider.messages)
        sms_count = len(machine.sms_provider.messages)
        result = await machine.execute(scheduled)
        print(
            f"STEP: {len(machine.executions)} | scheduled: {scheduled.scheduled_for.isoformat()}"
            f" | status: {result.status.value}"
        )
        _print_new_messages(machine, email_count=email_count, sms_count=sms_count)
        previous = machine.now
        if not result.has_more_steps or result.status.value not in {
            "sent",
            "already_sent",
            "skipped",
        }:
            return


def _print_new_messages(
    machine: PausedSearchTimeMachine,
    *,
    email_count: int,
    sms_count: int,
) -> None:
    if len(machine.email_provider.messages) > email_count:
        message = machine.email_provider.messages[-1]
        print(
            f"CHANNEL: EMAIL\nTO: {message.to_email}\nSUBJECT: {message.subject}"
            f"\nBODY:\n{message.body}"
        )
    elif len(machine.sms_provider.messages) > sms_count:
        message = machine.sms_provider.messages[-1]
        print(f"CHANNEL: SMS\nTO: {message.to_phone}\nBODY:\n{message.body}")


def _domain_steps(
    steps: tuple[PausedSearchTrackStepInput, ...], track_version_id: UUID
) -> tuple[PausedSearchTrackStep, ...]:
    return tuple(
        PausedSearchTrackStep(
            step_id=uuid5(NAMESPACE_URL, f"paused-search-time-machine:{index}"),
            workspace_id=UUID("50000000-0000-0000-0000-000000000001"),
            track_version_id=track_version_id,
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
        for index, step in enumerate(steps, start=1)
    )


def main() -> int:
    args = build_parser().parse_args()
    requested_tracks = TRACK_KEYS if args.all else (args.track,)
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    overall_exit_code = 0
    for requested_track in requested_tracks:
        track = requested_track.replace("-", "_")
        output = io.StringIO()
        with redirect_stdout(output):
            try:
                exit_code = asyncio.run(run_machine(track))
            except Exception as exc:
                print(f"ERROR: live LLM run failed ({type(exc).__name__}).")
                exit_code = 1
        report = output.getvalue()
        log_path = LOG_DIRECTORY / f"{_safe_track_name(track).replace('_', '-')}.log"
        log_path.write_text(report, encoding="utf-8")
        print(report, end="" if report.endswith("\n") else "\n")
        print(f"Log written to: {log_path}")
        overall_exit_code = max(overall_exit_code, exit_code)
    return overall_exit_code


def _safe_track_name(track: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", track).strip("._")
    return safe_name or "paused-search"


if __name__ == "__main__":
    raise SystemExit(main())