from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import delete, func, inspect, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def main(execute: bool) -> None:
    from app.core.database import (
        async_session_factory,
        enable_postgres_service_access,
    )
    from app.infrastructure.persistence.postgres.models import (
        ConversationModel,
        ConversationSummaryModel,
        CrmConversationEventModel,
        CRMSyncJobModel,
        ExternalEventModel,
        HandoffCompletionModel,
        HandoffModel,
        InboundMessageCRMCompletionModel,
        InboundMessageModel,
        LeadClassificationArtifactModel,
        LeadModel,
        LeadPausedSearchHistoryModel,
        LeadWorkflowOverrideAuditLogModel,
        OutboundMessageCRMCompletionModel,
        OutboundMessageModel,
        PreflightDigestModel,
        PreflightVetoModel,
        ProviderMessageEventModel,
        TemporalSignalOutboxModel,
        WorkspaceModel,
    )
    from app.infrastructure.persistence.postgres.workflow_models import (
        CampaignEnrollmentModel,
        LeadWorkflowModel,
        RejectedDraftReviewModel,
        WorkflowTransitionModel,
    )

    delete_models = (
        ProviderMessageEventModel,
        HandoffCompletionModel,
        RejectedDraftReviewModel,
        HandoffModel,
        LeadWorkflowOverrideAuditLogModel,
        InboundMessageCRMCompletionModel,
        OutboundMessageCRMCompletionModel,
        ConversationSummaryModel,
        CrmConversationEventModel,
        InboundMessageModel,
        ConversationModel,
        LeadClassificationArtifactModel,
        LeadPausedSearchHistoryModel,
        PreflightVetoModel,
        TemporalSignalOutboxModel,
        PreflightDigestModel,
        OutboundMessageModel,
        WorkflowTransitionModel,
        LeadWorkflowModel,
        CampaignEnrollmentModel,
        ExternalEventModel,
        CRMSyncJobModel,
        LeadModel,
    )
    count_models = delete_models

    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        connection = await session.connection()
        existing_tables = await connection.run_sync(
            lambda sync_connection: set(inspect(sync_connection).get_table_names())
        )
        workspaces = (
            await session.execute(
                select(WorkspaceModel.workspace_id, WorkspaceModel.name).order_by(
                    WorkspaceModel.created_at
                )
            )
        ).all()
        if len(workspaces) != 1:
            raise SystemExit(f"Expected exactly 1 workspace, found {len(workspaces)}.")

        workspace_id, workspace_name = workspaces[0]
        print(f"Workspace: {workspace_name} ({workspace_id})")
        print("Lead-related row counts before delete:")
        for model in count_models:
            if model.__tablename__ not in existing_tables:
                print(f"  {model.__tablename__}: <missing table, skipped>")
                continue
            count = await session.scalar(
                select(func.count()).select_from(model).where(model.workspace_id == workspace_id)
            )
            print(f"  {model.__tablename__}: {count}")

        if not execute:
            print("Dry run only. Re-run with --execute to delete.")
            return

        for model in delete_models:
            if model.__tablename__ not in existing_tables:
                print(f"Skipped {model.__tablename__}: table missing")
                continue
            result = await session.execute(delete(model).where(model.workspace_id == workspace_id))
            print(f"Deleted {result.rowcount or 0:>4} from {model.__tablename__}")

        await session.commit()
        print("Delete committed.")

        print("Lead-related row counts after delete:")
        for model in count_models:
            if model.__tablename__ not in existing_tables:
                print(f"  {model.__tablename__}: <missing table, skipped>")
                continue
            count = await session.scalar(
                select(func.count()).select_from(model).where(model.workspace_id == workspace_id)
            )
            print(f"  {model.__tablename__}: {count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(execute=args.execute))
