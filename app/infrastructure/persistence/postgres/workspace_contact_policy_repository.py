from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common.ids import WorkspaceId
from app.domain.compliance.contactability import WorkspaceContactPolicy
from app.infrastructure.persistence.postgres.models import WorkspaceContactPolicyModel


class PostgresWorkspaceContactPolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceContactPolicy | None:
        result = await self._session.execute(
            select(WorkspaceContactPolicyModel).where(
                WorkspaceContactPolicyModel.workspace_id == workspace_id,
            ),
        )
        model = result.scalar_one_or_none()
        return _policy_from_model(model) if model else None

    async def save(self, policy: WorkspaceContactPolicy) -> WorkspaceContactPolicy:
        now = datetime.now(UTC)
        statement = (
            insert(WorkspaceContactPolicyModel)
            .values(**_policy_to_values(policy, now))
            .on_conflict_do_update(
                index_elements=["workspace_id"],
                set_=_policy_update_values(policy, now),
            )
            .returning(WorkspaceContactPolicyModel)
        )
        result = await self._session.execute(statement)
        return _policy_from_model(result.scalar_one())


def _policy_from_model(model: WorkspaceContactPolicyModel) -> WorkspaceContactPolicy:
    return WorkspaceContactPolicy(
        workspace_id=model.workspace_id,
        quiet_hours_enabled=model.quiet_hours_enabled,
        quiet_hours_start=model.quiet_hours_start,
        quiet_hours_end=model.quiet_hours_end,
        inbound_email_address=model.inbound_email_address,
    )


def _policy_to_values(
    policy: WorkspaceContactPolicy,
    now: datetime,
) -> dict[str, object]:
    return {
        "workspace_id": policy.workspace_id,
        "quiet_hours_enabled": policy.quiet_hours_enabled,
        "quiet_hours_start": policy.quiet_hours_start,
        "quiet_hours_end": policy.quiet_hours_end,
        "inbound_email_address": policy.inbound_email_address,
        "created_at": now,
        "updated_at": now,
    }


def _policy_update_values(
    policy: WorkspaceContactPolicy,
    now: datetime,
) -> dict[str, object]:
    return {
        "quiet_hours_enabled": policy.quiet_hours_enabled,
        "quiet_hours_start": policy.quiet_hours_start,
        "quiet_hours_end": policy.quiet_hours_end,
        "inbound_email_address": policy.inbound_email_address,
        "updated_at": now,
    }
