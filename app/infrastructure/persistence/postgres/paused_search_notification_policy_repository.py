from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.paused_search_notifications import (
    PausedSearchNotificationEvent,
    PausedSearchNotificationPolicy,
)
from app.domain.common.ids import WorkspaceId
from app.infrastructure.persistence.postgres.models import PausedSearchNotificationPolicyModel


class PostgresPausedSearchNotificationPolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest(
        self,
        workspace_id: WorkspaceId,
    ) -> PausedSearchNotificationPolicy | None:
        result = await self._session.execute(
            select(PausedSearchNotificationPolicyModel)
            .where(PausedSearchNotificationPolicyModel.workspace_id == workspace_id)
            .order_by(PausedSearchNotificationPolicyModel.version.desc())
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return _from_model(model) if model is not None else None

    async def save(
        self,
        policy: PausedSearchNotificationPolicy,
    ) -> PausedSearchNotificationPolicy:
        await self._session.execute(
            insert(PausedSearchNotificationPolicyModel)
            .values(**_to_values(policy))
            .on_conflict_do_nothing(index_elements=["workspace_id", "version"])
        )
        saved = await self._get_by_workspace_and_version(policy.workspace_id, policy.version)
        assert saved is not None
        return saved

    async def _get_by_workspace_and_version(
        self,
        workspace_id: WorkspaceId,
        version: int,
    ) -> PausedSearchNotificationPolicy | None:
        result = await self._session.execute(
            select(PausedSearchNotificationPolicyModel).where(
                PausedSearchNotificationPolicyModel.workspace_id == workspace_id,
                PausedSearchNotificationPolicyModel.version == version,
            )
        )
        model = result.scalar_one_or_none()
        return _from_model(model) if model is not None else None


def _to_values(policy: PausedSearchNotificationPolicy) -> dict[str, object]:
    return {
        "notification_policy_id": policy.notification_policy_id,
        "workspace_id": policy.workspace_id,
        "version": policy.version,
        "enabled_events": [event.value for event in policy.enabled_events],
        "recipient_roles": list(policy.recipient_roles),
        "manager_escalation_hours": policy.manager_escalation_hours,
        "repeated_failure_threshold": policy.repeated_failure_threshold,
        "digest_enabled": policy.digest_enabled,
        "digest_cadence_hours": policy.digest_cadence_hours,
        "created_at": policy.created_at,
        "published_at": policy.published_at,
    }


def _from_model(model: PausedSearchNotificationPolicyModel) -> PausedSearchNotificationPolicy:
    return PausedSearchNotificationPolicy(
        notification_policy_id=model.notification_policy_id,
        workspace_id=model.workspace_id,
        version=model.version,
        enabled_events=tuple(
            PausedSearchNotificationEvent(event) for event in model.enabled_events
        ),
        recipient_roles=tuple(model.recipient_roles),
        manager_escalation_hours=model.manager_escalation_hours,
        repeated_failure_threshold=model.repeated_failure_threshold,
        digest_enabled=model.digest_enabled,
        digest_cadence_hours=model.digest_cadence_hours,
        created_at=model.created_at,
        published_at=model.published_at,
    )
