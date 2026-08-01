from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.paused_search_notifications import (
    PausedSearchNotification,
    PausedSearchNotificationChannel,
    PausedSearchNotificationEvent,
    PausedSearchNotificationStatus,
)
from app.domain.common.ids import WorkspaceId
from app.infrastructure.persistence.postgres.models import PausedSearchNotificationModel


class PostgresPausedSearchNotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> PausedSearchNotification | None:
        result = await self._session.execute(
            select(PausedSearchNotificationModel).where(
                PausedSearchNotificationModel.workspace_id == workspace_id,
                PausedSearchNotificationModel.idempotency_key == idempotency_key,
            )
        )
        model = result.scalar_one_or_none()
        return _from_model(model) if model is not None else None

    async def save(
        self,
        notification: PausedSearchNotification,
    ) -> PausedSearchNotification:
        await self._session.execute(
            insert(PausedSearchNotificationModel)
            .values(**_to_values(notification))
            .on_conflict_do_nothing(index_elements=["workspace_id", "idempotency_key"])
        )
        saved = await self.get_by_idempotency_key(
            notification.workspace_id,
            notification.idempotency_key,
        )
        assert saved is not None
        return saved


def _to_values(notification: PausedSearchNotification) -> dict[str, object]:
    return {
        "notification_id": notification.notification_id,
        "workspace_id": notification.workspace_id,
        "event": notification.event.value,
        "channel": notification.channel.value,
        "status": notification.status.value,
        "idempotency_key": notification.idempotency_key,
        "recipient_user_id": notification.recipient_user_id,
        "recipient_destination": notification.recipient_destination,
        "subject": notification.subject,
        "body": notification.body,
        "policy_id": notification.policy_id,
        "policy_version": notification.policy_version,
        "correlation_id": notification.correlation_id,
        "accepted_at": notification.accepted_at,
        "failed_at": notification.failed_at,
        "failure_reason": notification.failure_reason,
    }


def _from_model(model: PausedSearchNotificationModel) -> PausedSearchNotification:
    return PausedSearchNotification(
        notification_id=model.notification_id,
        workspace_id=model.workspace_id,
        event=PausedSearchNotificationEvent(model.event),
        channel=PausedSearchNotificationChannel(model.channel),
        status=PausedSearchNotificationStatus(model.status),
        idempotency_key=model.idempotency_key,
        recipient_user_id=model.recipient_user_id,
        recipient_destination=model.recipient_destination,
        subject=model.subject,
        body=model.body,
        policy_id=model.policy_id,
        policy_version=model.policy_version,
        correlation_id=model.correlation_id,
        accepted_at=model.accepted_at,
        failed_at=model.failed_at,
        failure_reason=model.failure_reason,
    )
