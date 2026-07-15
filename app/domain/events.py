from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.common.ids import WorkspaceId


class AggregateType(StrEnum):
    CAMPAIGN = "campaign"
    CRM_SYNC = "crm_sync"
    HANDOFF = "handoff"
    LEAD = "lead"
    MESSAGE = "message"
    WORKFLOW = "workflow"


class DomainEventType(StrEnum):
    CAMPAIGN_BATCH_LAUNCHED = "campaign.batch_launched"
    CAMPAIGN_DRAFT_CREATED = "campaign.draft_created"
    CAMPAIGN_DRAFT_UPDATED = "campaign.draft_updated"
    CAMPAIGN_ENROLLED = "campaign.enrolled"
    CAMPAIGN_PAUSED = "campaign.paused"
    CAMPAIGN_PUBLISHED = "campaign.published"
    CAMPAIGN_RESUMED = "campaign.resumed"
    CRM_SYNC_REQUESTED = "crm_sync.requested"
    HANDOFF_CREATED = "handoff.created"
    LEAD_OPTED_OUT = "lead.opted_out"
    MESSAGE_DELIVERED = "message.delivered"
    MESSAGE_DELIVERY_FAILED = "message.delivery_failed"
    MESSAGE_FAILED = "message.failed"
    MESSAGE_RECEIVED = "message.received"
    MESSAGE_SENT = "message.sent"
    WORKFLOW_TRANSITIONED = "workflow.transitioned"


class OutboxEventStatus(StrEnum):
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


def _empty_payload() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True)
class DomainEvent:
    workspace_id: WorkspaceId
    aggregate_type: AggregateType
    aggregate_id: UUID
    event_type: DomainEventType
    payload: Mapping[str, object] = field(default_factory=_empty_payload)


@dataclass(frozen=True)
class OutboxEvent:
    outbox_event_id: UUID
    workspace_id: WorkspaceId
    aggregate_type: AggregateType
    aggregate_id: UUID
    event_type: DomainEventType
    payload: dict[str, object]
    status: OutboxEventStatus
    attempt_count: int
    available_at: datetime
    created_at: datetime
    published_at: datetime | None = None
    last_error: str | None = None
