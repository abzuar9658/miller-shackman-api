from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.application.use_cases.paused_search_notification_policy import (
    DefaultPausedSearchNotificationPolicyStatus,
    ensure_default_paused_search_notification_policy,
)
from app.domain.campaigns.paused_search_notifications import PausedSearchNotificationPolicy


class FakePolicyRepository:
    def __init__(self) -> None:
        self.policy: PausedSearchNotificationPolicy | None = None

    async def get_latest(self, workspace_id: UUID) -> PausedSearchNotificationPolicy | None:
        if self.policy is not None and self.policy.workspace_id == workspace_id:
            return self.policy
        return None

    async def save(self, policy: PausedSearchNotificationPolicy) -> PausedSearchNotificationPolicy:
        if self.policy is None:
            self.policy = policy
        return self.policy


@pytest.mark.asyncio
async def test_default_policy_seeding_is_idempotent() -> None:
    repository = FakePolicyRepository()
    workspace_id = UUID("00000000-0000-0000-0000-000000000801")
    now = datetime(2026, 1, 1, tzinfo=UTC)

    first = await ensure_default_paused_search_notification_policy(
        workspace_id=workspace_id,
        repository=repository,
        now=now,
    )
    second = await ensure_default_paused_search_notification_policy(
        workspace_id=workspace_id,
        repository=repository,
        now=now,
    )

    assert first.status is DefaultPausedSearchNotificationPolicyStatus.CREATED
    assert second.status is DefaultPausedSearchNotificationPolicyStatus.ALREADY_PRESENT
    assert first.policy == second.policy
    assert first.policy.version == 1
    assert first.policy.published_at == now
