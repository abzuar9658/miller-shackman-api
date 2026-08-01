from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class PausedSearchNotificationEvent(StrEnum):
    REVIEW_REQUEST = "review_request"
    HANDOFF = "handoff"
    POLICY_PAUSE = "policy_pause"
    PROVIDER_FAILURE = "provider_failure"
    DURATION_EXPIRATION = "duration_expiration"


class PausedSearchNotificationChannel(StrEnum):
    EMAIL = "email"
    IN_APP = "in_app"


class PausedSearchNotificationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


DEFAULT_PAUSED_SEARCH_NOTIFICATION_EVENTS = (
    PausedSearchNotificationEvent.REVIEW_REQUEST,
    PausedSearchNotificationEvent.HANDOFF,
    PausedSearchNotificationEvent.POLICY_PAUSE,
    PausedSearchNotificationEvent.PROVIDER_FAILURE,
    PausedSearchNotificationEvent.DURATION_EXPIRATION,
)


@dataclass(frozen=True)
class PausedSearchNotificationPolicy:
    notification_policy_id: UUID
    workspace_id: UUID
    version: int
    enabled_events: tuple[PausedSearchNotificationEvent, ...]
    recipient_roles: tuple[str, ...]
    manager_escalation_hours: int
    repeated_failure_threshold: int
    digest_enabled: bool
    digest_cadence_hours: int
    created_at: datetime
    published_at: datetime | None = None


def default_paused_search_notification_policy(
    workspace_id: UUID,
    *,
    now: datetime,
) -> PausedSearchNotificationPolicy:
    return PausedSearchNotificationPolicy(
        notification_policy_id=uuid4(),
        workspace_id=workspace_id,
        version=1,
        enabled_events=DEFAULT_PAUSED_SEARCH_NOTIFICATION_EVENTS,
        recipient_roles=("assigned_agent", "manager", "brokerage_admin"),
        manager_escalation_hours=24,
        repeated_failure_threshold=3,
        digest_enabled=False,
        digest_cadence_hours=24,
        created_at=now,
        published_at=now,
    )


@dataclass(frozen=True)
class PausedSearchNotification:
    notification_id: UUID
    workspace_id: UUID
    event: PausedSearchNotificationEvent
    channel: PausedSearchNotificationChannel
    status: PausedSearchNotificationStatus
    idempotency_key: str
    recipient_user_id: UUID | None
    recipient_destination: str | None
    subject: str
    body: str
    policy_id: UUID
    policy_version: int
    correlation_id: UUID | None = None
    accepted_at: datetime | None = None
    failed_at: datetime | None = None
    failure_reason: str | None = None
