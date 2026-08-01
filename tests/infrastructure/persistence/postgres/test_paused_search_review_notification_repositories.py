from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.paused_search_notifications import (
    PausedSearchNotification,
    PausedSearchNotificationChannel,
    PausedSearchNotificationEvent,
    PausedSearchNotificationStatus,
    default_paused_search_notification_policy,
)
from app.domain.campaigns.paused_search_reviews import (
    PausedSearchReview,
    PausedSearchReviewKind,
    PausedSearchReviewStatus,
)
from app.infrastructure.persistence.postgres.models import WorkspaceModel
from app.infrastructure.persistence.postgres.paused_search_notification_policy_repository import (
    PostgresPausedSearchNotificationPolicyRepository,
)
from app.infrastructure.persistence.postgres.paused_search_notification_repository import (
    PostgresPausedSearchNotificationRepository,
)
from app.infrastructure.persistence.postgres.paused_search_review_repository import (
    PostgresPausedSearchReviewRepository,
)

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111301")
OTHER_WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111302")
LEAD_ID = UUID("11111111-1111-1111-1111-111111111303")
WORKFLOW_ID = UUID("11111111-1111-1111-1111-111111111304")
REVIEW_ID = UUID("11111111-1111-1111-1111-111111111305")
NOTIFICATION_ID = UUID("11111111-1111-1111-1111-111111111306")


@pytest.mark.asyncio
async def test_paused_search_policy_review_and_notification_repositories_are_idempotent_and_scoped(
    postgres_session: AsyncSession,
) -> None:
    await _seed_workspaces(postgres_session)
    policy_repository = PostgresPausedSearchNotificationPolicyRepository(postgres_session)
    review_repository = PostgresPausedSearchReviewRepository(postgres_session)
    notification_repository = PostgresPausedSearchNotificationRepository(postgres_session)

    policy = default_paused_search_notification_policy(WORKSPACE_ID, now=NOW)
    saved_policy = await policy_repository.save(policy)
    duplicate_policy = await policy_repository.save(policy)
    review = await review_repository.save(_review())
    duplicate_review = await review_repository.save(_review())
    notification = await notification_repository.save(
        _notification(saved_policy.notification_policy_id)
    )
    duplicate_notification = await notification_repository.save(
        _notification(saved_policy.notification_policy_id)
    )

    assert saved_policy == policy
    assert duplicate_policy == policy
    assert duplicate_review == review
    assert duplicate_notification == notification
    assert await policy_repository.get_latest(OTHER_WORKSPACE_ID) is None
    assert await review_repository.get_by_id(OTHER_WORKSPACE_ID, REVIEW_ID) is None
    assert (
        await notification_repository.get_by_idempotency_key(OTHER_WORKSPACE_ID, "review:305")
        is None
    )


async def _seed_workspaces(session: AsyncSession) -> None:
    session.add_all(
        [
            WorkspaceModel(
                workspace_id=WORKSPACE_ID,
                name="Paused Search Workspace",
                status="active",
                default_timezone="UTC",
                created_at=NOW,
                updated_at=NOW,
            ),
            WorkspaceModel(
                workspace_id=OTHER_WORKSPACE_ID,
                name="Other Workspace",
                status="active",
                default_timezone="UTC",
                created_at=NOW,
                updated_at=NOW,
            ),
        ]
    )
    await session.flush()


def _review() -> PausedSearchReview:
    return PausedSearchReview(
        review_id=REVIEW_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        occurrence_id=None,
        kind=PausedSearchReviewKind.MESSAGE,
        status=PausedSearchReviewStatus.PENDING,
        reason="message requires review",
        requested_at=NOW,
    )


def _notification(policy_id: UUID) -> PausedSearchNotification:
    return PausedSearchNotification(
        notification_id=NOTIFICATION_ID,
        workspace_id=WORKSPACE_ID,
        event=PausedSearchNotificationEvent.REVIEW_REQUEST,
        channel=PausedSearchNotificationChannel.IN_APP,
        status=PausedSearchNotificationStatus.PENDING,
        idempotency_key="review:305",
        recipient_user_id=None,
        recipient_destination=None,
        subject="Paused-search review",
        body="A message needs review.",
        policy_id=policy_id,
        policy_version=1,
    )
