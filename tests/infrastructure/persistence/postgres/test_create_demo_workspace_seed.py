from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.reporting import WorkspaceOperationsSummary
from app.infrastructure.persistence.postgres.models import (
    CampaignModel,
    HandoffModel,
    LeadModel,
    PreflightDigestModel,
    WorkspaceMembershipModel,
)
from app.infrastructure.persistence.postgres.reporting_repository import PostgresReportingRepository
from app.infrastructure.persistence.postgres.workflow_models import LeadWorkflowModel
from scripts.create_demo_workspace import DemoSeedOptions, seed_demo_workspace


class _FastPasswordHasher:
    def hash_password(self, password: str) -> str:
        return f"fake-hash:{password}"

    def verify_password(self, password: str, password_hash: str) -> bool:
        return password_hash == self.hash_password(password)

    def needs_rehash(self, password_hash: str) -> bool:
        return False


async def test_demo_seed_is_idempotent_and_reportable(
    postgres_session: AsyncSession,
) -> None:
    settings = Settings(sms_provider="sink", email_provider="sink")
    options = DemoSeedOptions(workspace_name="Demo: Miller Schackman Test", reset_leads=True)

    first = await seed_demo_workspace(
        postgres_session,
        settings=settings,
        options=options,
        password_hasher=_FastPasswordHasher(),
    )
    second = await seed_demo_workspace(
        postgres_session,
        settings=settings,
        options=DemoSeedOptions(workspace_name=options.workspace_name),
        password_hasher=_FastPasswordHasher(),
    )
    await postgres_session.flush()

    assert second.workspace_id == first.workspace_id
    assert second.campaign_id == first.campaign_id
    assert await _count(postgres_session, WorkspaceMembershipModel, first.workspace_id) == 3
    assert await _count(postgres_session, CampaignModel, first.workspace_id) == 1
    assert await _count(postgres_session, LeadModel, first.workspace_id) == 12
    assert await _count(postgres_session, LeadWorkflowModel, first.workspace_id) == 12
    assert await _count(postgres_session, HandoffModel, first.workspace_id) == 2
    assert await _count(postgres_session, PreflightDigestModel, first.workspace_id) == 1

    report = await PostgresReportingRepository(postgres_session).get_workspace_operations_summary(
        first.workspace_id,
    )
    _assert_report_has_demo_states(report)


async def _count(session: AsyncSession, model: Any, workspace_id: object) -> int:
    value = await session.scalar(
        select(func.count()).select_from(model).where(model.workspace_id == workspace_id),
    )
    return int(value or 0)


def _assert_report_has_demo_states(report: WorkspaceOperationsSummary) -> None:
    assert report.workflow_counts.queued >= 1
    assert report.workflow_counts.waiting_for_response >= 1
    assert report.workflow_counts.paused >= 1
    assert report.workflow_counts.human_handoff >= 1
    assert report.workflow_counts.completed >= 1
    assert report.message_counts.failed >= 1
    assert report.handoff_counts.acknowledged >= 1
