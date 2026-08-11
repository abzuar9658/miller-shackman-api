"""Simulate the passage of time for one lead's live nurture workflow.

Shifts the lead's schedule timestamps back by N days in Postgres
(lead_workflows.next_action_at plus the lead's outbound_messages history so
frequency limits behave as if time really passed), then signals the running
Temporal workflow with `reschedule-requested` so it re-plans immediately.

Requires: `make infra-up` and `make worker` running. Quiet hours still apply
against the real wall clock (sends only 10 AM-5 PM brokerage time).

Usage:
    uv run python scripts/lead_time_machine.py --lead-id <uuid>            # interactive
    uv run python scripts/lead_time_machine.py --lead-id <uuid> --days 2   # one-shot
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TERMINAL_STATES = ("completed", "suppressed", "closed")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lead-id", required=True, type=UUID, help="Lead UUID.")
    parser.add_argument(
        "--days",
        type=float,
        default=None,
        help="Pass this many days once and exit. Omit for interactive mode.",
    )
    return parser.parse_args()


async def _load_workflow(session: object, lead_id: UUID) -> object | None:
    from sqlalchemy import select

    from app.infrastructure.persistence.postgres.workflow_models import LeadWorkflowModel

    result = await session.execute(
        select(LeadWorkflowModel)
        .where(
            LeadWorkflowModel.lead_id == lead_id,
            LeadWorkflowModel.state.not_in(TERMINAL_STATES),
        )
        .order_by(LeadWorkflowModel.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def _print_status(lead_id: UUID, temporal_client: object) -> None:
    from app.core.database import async_session_factory, enable_postgres_service_access

    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        workflow = await _load_workflow(session, lead_id)
        if workflow is None:
            print(f"No active (non-terminal) lead_workflows row for lead {lead_id}.")
            return
        print(f"workflow_id:          {workflow.workflow_id}")
        print(f"temporal_workflow_id: {workflow.temporal_workflow_id}")
        print(f"state:                {workflow.state}")
        print(f"current_step_id:      {workflow.current_step_id}")
        print(f"next_action_at:       {workflow.next_action_at}")
        temporal_workflow_id = workflow.temporal_workflow_id

    handle = temporal_client.get_workflow_handle(temporal_workflow_id)
    try:
        snapshot = await handle.query("snapshot")
        print(f"temporal snapshot:    {snapshot}")
    except Exception as exc:  # workflow may not be running
        print(f"temporal query failed: {type(exc).__name__}: {exc}")


async def _pass_time(lead_id: UUID, days: float, temporal_client: object) -> None:
    from sqlalchemy import update

    from app.core.database import async_session_factory, enable_postgres_service_access
    from app.infrastructure.persistence.postgres.models import OutboundMessageModel
    from app.infrastructure.persistence.postgres.workflow_models import LeadWorkflowModel
    from app.infrastructure.workflows.temporal.lead_nurture import RescheduleWorkflowSignal

    delta = timedelta(days=days)
    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        workflow = await _load_workflow(session, lead_id)
        if workflow is None:
            print(f"No active (non-terminal) lead_workflows row for lead {lead_id}.")
            return

        old_next = workflow.next_action_at
        temporal_workflow_id = workflow.temporal_workflow_id
        workspace_id = workflow.workspace_id

        if old_next is not None:
            await session.execute(
                update(LeadWorkflowModel)
                .where(LeadWorkflowModel.workflow_id == workflow.workflow_id)
                .values(next_action_at=LeadWorkflowModel.next_action_at - delta)
            )

        shifted = await session.execute(
            update(OutboundMessageModel)
            .where(
                OutboundMessageModel.workspace_id == workspace_id,
                OutboundMessageModel.lead_id == lead_id,
            )
            .values(
                created_at=OutboundMessageModel.created_at - delta,
                updated_at=OutboundMessageModel.updated_at - delta,
                scheduled_for=OutboundMessageModel.scheduled_for - delta,
                planned_at=OutboundMessageModel.planned_at - delta,
                sent_at=OutboundMessageModel.sent_at - delta,
                delivered_at=OutboundMessageModel.delivered_at - delta,
                provider_status_updated_at=(
                    OutboundMessageModel.provider_status_updated_at - delta
                ),
            )
        )
        await session.commit()

        new_next = old_next - delta if old_next is not None else None
        print(f"Shifted next_action_at: {old_next} -> {new_next}")
        print(f"Shifted {shifted.rowcount} outbound_messages row(s) back {days} day(s).")

    handle = temporal_client.get_workflow_handle(temporal_workflow_id)
    signal = RescheduleWorkflowSignal(
        workspace_id=workspace_id,
        lead_id=lead_id,
        occurred_at=datetime.now(UTC).isoformat(),
        reason=f"lead_time_machine: simulated {days} day(s) passing",
    )
    try:
        await handle.signal("reschedule-requested", signal)
        print("Sent reschedule-requested signal to Temporal workflow.")
        print("Watch it at the Temporal UI (workflow id above).")
    except Exception as exc:
        print(f"Signal failed: {type(exc).__name__}: {exc}")


async def _interactive(lead_id: UUID, temporal_client: object) -> None:
    print("Commands: <days> (e.g. 1, 2, 0.5) = pass time | s = status | q = quit")
    await _print_status(lead_id, temporal_client)
    while True:
        try:
            raw = (await asyncio.to_thread(input, "time-machine> ")).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if raw in {"q", "quit", "exit"}:
            return
        if raw in {"s", "status"}:
            await _print_status(lead_id, temporal_client)
            continue
        try:
            days = float(raw.removesuffix("d").removesuffix("day").removesuffix("days"))
        except ValueError:
            print("Enter a number of days (e.g. 1), 's' for status, or 'q' to quit.")
            continue
        if days <= 0:
            print("Days must be positive.")
            continue
        await _pass_time(lead_id, days, temporal_client)


async def _main() -> int:
    from app.core.config import get_settings
    from app.infrastructure.workflows.temporal.worker import connect_temporal_client

    args = _parse_args()
    temporal_client = await connect_temporal_client(get_settings())
    if args.days is not None:
        await _pass_time(args.lead_id, args.days, temporal_client)
        await _print_status(args.lead_id, temporal_client)
    else:
        await _interactive(args.lead_id, temporal_client)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
