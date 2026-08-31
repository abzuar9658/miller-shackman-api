"""One-time repair: resume lead workflows paused with reason `cadence_step_blocked`.

These workflows were paused by now-fixed issues (SMS drafts exceeding the
320-character cap, provider send failures). Each one is resumed through the
formal `resume_lead_workflow` use case, so every resume gets the full audit
trail: an internal external event, a `manual_resume` workflow transition,
dismissal of pending rejected-draft reviews, and a `resume-requested` Temporal
signal queued via the outbox.

Safe for production:
- Dry run by default; pass --execute to apply.
- One transaction per lead (pessimistic locks via the use case); a failure on
  one lead is rolled back and does not affect the others.
- Resumes are signalled through the temporal signal outbox, so the outbox
  publisher worker (and the Temporal worker) must be running for the
  workflows to actually wake up.

Usage:
    uv run python scripts/repair_blocked_workflows.py                      # dry run, all
    uv run python scripts/repair_blocked_workflows.py --workspace-id <id>  # dry run, one
    uv run python scripts/repair_blocked_workflows.py --execute            # apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.domain.identity import AuthenticatedActor
    from app.infrastructure.persistence.postgres.workflow_models import LeadWorkflowModel

PAUSE_REASON = "cadence_step_blocked"
DEFAULT_REASON = (
    "One-time repair: resume workflows blocked by fixed SMS length and provider issues"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace-id",
        type=UUID,
        default=None,
        help="Only repair workflows in this workspace. Default: all workspaces.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply the resumes. Without this flag the script only reports.",
    )
    parser.add_argument(
        "--reason",
        default=DEFAULT_REASON,
        help="Resume reason recorded on the transition and audit trail.",
    )
    return parser.parse_args()


async def _load_blocked_workflows(
    session: AsyncSession,
    workspace_id: UUID | None,
) -> list[LeadWorkflowModel]:
    from sqlalchemy import select

    from app.infrastructure.persistence.postgres.workflow_models import LeadWorkflowModel

    statement = (
        select(LeadWorkflowModel)
        .where(
            LeadWorkflowModel.state == "paused",
            LeadWorkflowModel.pause_reason == PAUSE_REASON,
        )
        .order_by(LeadWorkflowModel.workspace_id, LeadWorkflowModel.created_at)
    )
    if workspace_id is not None:
        statement = statement.where(LeadWorkflowModel.workspace_id == workspace_id)
    result = await session.execute(statement)
    return list(result.scalars().all())


async def _admin_actor_for_workspace(
    session: AsyncSession,
    workspace_id: UUID,
) -> AuthenticatedActor | None:
    """Pick an active admin membership in the workspace to act as the resume actor."""
    from sqlalchemy import select

    from app.domain.identity import (
        AuthenticatedActor,
        UserStatus,
        WorkspaceMembershipRole,
        WorkspaceMembershipStatus,
        WorkspaceStatus,
    )
    from app.infrastructure.persistence.postgres.models import (
        UserModel,
        WorkspaceMembershipModel,
        WorkspaceModel,
    )

    workspace = (
        await session.execute(
            select(WorkspaceModel).where(WorkspaceModel.workspace_id == workspace_id)
        )
    ).scalar_one_or_none()
    if workspace is None or workspace.status != WorkspaceStatus.ACTIVE.value:
        return None

    role_preference = (
        WorkspaceMembershipRole.BROKERAGE_ADMIN.value,
        WorkspaceMembershipRole.PLATFORM_SUPER_ADMIN.value,
        WorkspaceMembershipRole.MANAGER.value,
    )
    rows = (
        await session.execute(
            select(WorkspaceMembershipModel, UserModel)
            .join(UserModel, UserModel.user_id == WorkspaceMembershipModel.user_id)
            .where(
                WorkspaceMembershipModel.workspace_id == workspace_id,
                WorkspaceMembershipModel.status == WorkspaceMembershipStatus.ACTIVE.value,
                WorkspaceMembershipModel.role.in_(role_preference),
                UserModel.status == UserStatus.ACTIVE.value,
            )
        )
    ).all()
    if not rows:
        return None
    membership, _user = min(rows, key=lambda row: role_preference.index(row[0].role))
    return AuthenticatedActor(
        user_id=membership.user_id,
        user_status=UserStatus.ACTIVE,
        active_role=WorkspaceMembershipRole(membership.role),
        active_workspace_id=workspace_id,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=membership.membership_id,
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


async def _resume_one(
    workspace_id: UUID,
    lead_id: UUID,
    actor: AuthenticatedActor,
    reason: str,
) -> tuple[str, tuple[str, ...]]:
    """Resume one lead in its own transaction. Returns (status, reasons)."""
    from app.application.use_cases.lead_resume import resume_lead_workflow
    from app.core.database import (
        async_session_factory,
        enable_postgres_service_access,
        service_access_commit,
    )
    from app.infrastructure.persistence.postgres.crm_sync_repository import (
        PostgresExternalEventRepository,
    )
    from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
    from app.infrastructure.persistence.postgres.rejected_draft_review_repository import (
        PostgresRejectedDraftReviewRepository,
    )
    from app.infrastructure.persistence.postgres.temporal_signal_outbox_repository import (
        PostgresTemporalSignalOutboxRepository,
    )
    from app.infrastructure.persistence.postgres.workflow_repository import (
        PostgresLeadWorkflowRepository,
        PostgresWorkflowTransitionRepository,
    )
    from app.infrastructure.persistence.postgres.workspace_contact_policy_repository import (
        PostgresWorkspaceContactPolicyRepository,
    )

    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        try:
            result = await resume_lead_workflow(
                actor=actor,
                workspace_id=workspace_id,
                lead_id=lead_id,
                reason=reason,
                lead_repository=PostgresLeadRepository(session),
                workflow_repository=PostgresLeadWorkflowRepository(session),
                lead_workflow_repository=PostgresLeadWorkflowRepository(session),
                workspace_contact_policy_repository=(
                    PostgresWorkspaceContactPolicyRepository(session)
                ),
                workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
                temporal_signal_outbox_repository=PostgresTemporalSignalOutboxRepository(session),
                external_event_repository=PostgresExternalEventRepository(session),
                rejected_draft_review_repository=PostgresRejectedDraftReviewRepository(session),
                commit=service_access_commit(session),
                now=datetime.now(UTC),
            )
        except Exception as exc:
            await session.rollback()
            return "error", (f"{type(exc).__name__}: {exc}",)

    eligibility_reasons: tuple[str, ...] = ()
    if result.eligibility is not None:
        eligibility_reasons = tuple(code.value for code in result.eligibility.reasons)
    reasons = tuple(code.value for code in result.reasons) + eligibility_reasons
    return result.status.value, reasons


async def _main() -> int:
    from app.core.database import async_session_factory, enable_postgres_service_access

    args = _parse_args()
    mode = "EXECUTE" if args.execute else "DRY RUN"

    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        workflows = await _load_blocked_workflows(session, args.workspace_id)
        workspace_ids = sorted({workflow.workspace_id for workflow in workflows})
        actors = {
            workspace_id: await _admin_actor_for_workspace(session, workspace_id)
            for workspace_id in workspace_ids
        }

    print(f"[{mode}] Found {len(workflows)} paused workflow(s) with reason '{PAUSE_REASON}'.")
    if not workflows:
        return 0

    counts: dict[str, int] = {}
    for workflow in workflows:
        actor = actors.get(workflow.workspace_id)
        prefix = f"workspace={workflow.workspace_id} lead={workflow.lead_id}"
        if actor is None:
            counts["no_admin_actor"] = counts.get("no_admin_actor", 0) + 1
            print(f"  SKIP {prefix} — no active admin/manager membership in workspace")
            continue
        if not args.execute:
            counts["would_resume"] = counts.get("would_resume", 0) + 1
            print(f"  WOULD RESUME {prefix} (actor user={actor.user_id} role={actor.active_role})")
            continue
        status, reasons = await _resume_one(
            workflow.workspace_id,
            workflow.lead_id,
            actor,
            args.reason,
        )
        counts[status] = counts.get(status, 0) + 1
        detail = f" reasons={list(reasons)}" if reasons else ""
        print(f"  {status.upper()} {prefix}{detail}")

    print("\nSummary:")
    for status, count in sorted(counts.items()):
        print(f"  {status}: {count}")
    if args.execute:
        print(
            "\nResume signals are queued in the temporal signal outbox; "
            "the outbox publisher worker delivers them to Temporal."
        )
    else:
        print("\nDry run only. Re-run with --execute to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
