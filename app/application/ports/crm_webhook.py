from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.application.ports.crm import CRMClient
from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    CampaignExecutionRepository,
    ExternalEventRepository,
    LeadRepository,
    LeadWorkflowRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter


@dataclass(frozen=True)
class FollowUpBossWebhookEventBundle:
    lead_repository: LeadRepository
    external_event_repository: ExternalEventRepository
    lead_workflow_repository: LeadWorkflowRepository
    workflow_transition_repository: WorkflowTransitionRepository
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository
    campaign_execution_repository: CampaignExecutionRepository
    campaign_enrollment_repository: CampaignEnrollmentRepository
    crm_client: CRMClient
    temporal_workflow_starter: TemporalWorkflowStarter
    event_bus: EventBus | None
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None
    commit: Callable[[], Awaitable[None]] | None = None


@dataclass
class FollowUpBossWebhookEventResult:
    status: str
    external_event_id: UUID | None = None
    event_type: str | None = None
    processed_count: int = 0
    ignored_count: int = 0
    duplicate_count: int = 0
    reasons: list[str] = field(default_factory=list)


class FollowUpBossWebhookEventHandler(Protocol):
    async def handle(
        self,
        workspace_id: UUID,
        payload: Mapping[str, Any],
        now: datetime,
    ) -> FollowUpBossWebhookEventResult:
        raise NotImplementedError
