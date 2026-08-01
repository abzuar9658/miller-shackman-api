from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.application.ports.repositories import PausedSearchNotificationPolicyRepository
from app.domain.campaigns.paused_search_notifications import (
    PausedSearchNotificationPolicy,
    default_paused_search_notification_policy,
)


class DefaultPausedSearchNotificationPolicyStatus(StrEnum):
    CREATED = "created"
    ALREADY_PRESENT = "already_present"


@dataclass(frozen=True)
class DefaultPausedSearchNotificationPolicyResult:
    status: DefaultPausedSearchNotificationPolicyStatus
    policy: PausedSearchNotificationPolicy


async def ensure_default_paused_search_notification_policy(
    *,
    workspace_id: UUID,
    repository: PausedSearchNotificationPolicyRepository,
    now: datetime,
) -> DefaultPausedSearchNotificationPolicyResult:
    existing = await repository.get_latest(workspace_id)
    if existing is not None:
        return DefaultPausedSearchNotificationPolicyResult(
            status=DefaultPausedSearchNotificationPolicyStatus.ALREADY_PRESENT,
            policy=existing,
        )

    policy = default_paused_search_notification_policy(workspace_id, now=now)
    saved = await repository.save(policy)
    status = (
        DefaultPausedSearchNotificationPolicyStatus.CREATED
        if saved.notification_policy_id == policy.notification_policy_id
        else DefaultPausedSearchNotificationPolicyStatus.ALREADY_PRESENT
    )
    return DefaultPausedSearchNotificationPolicyResult(status=status, policy=saved)
