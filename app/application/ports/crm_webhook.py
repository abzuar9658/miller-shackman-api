from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.application.ports.crm import CRMClient
from app.application.ports.event_bus import EventBus
from app.application.ports.llm import LLMClient
from app.application.ports.notifications import NotificationProvider
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    CampaignExecutionRepository,
    CrmConversationEventRepository,
    ExternalEventRepository,
    HandoffCompletionRepository,
    HandoffRepository,
    LeadClassificationArtifactRepository,
    LeadRepository,
    LeadRoutingReviewRepository,
    LeadWorkflowRepository,
    PausedSearchOccurrenceRepository,
    PausedSearchTrackMappingRepository,
    TemporalSignalOutboxRepository,
    UserRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceLLMConfigRepository,
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
    lead_classification_artifact_repository: LeadClassificationArtifactRepository
    paused_search_track_repository: PausedSearchTrackMappingRepository
    crm_conversation_event_repository: CrmConversationEventRepository
    workspace_llm_config_repository: WorkspaceLLMConfigRepository
    crm_client: CRMClient
    temporal_workflow_starter: TemporalWorkflowStarter
    llm_client: LLMClient
    event_bus: EventBus | None
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None
    handoff_repository: HandoffRepository | None = None
    handoff_completion_repository: HandoffCompletionRepository | None = None
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None = None
    notification_provider: NotificationProvider | None = None
    user_repository: UserRepository | None = None
    routing_review_repository: LeadRoutingReviewRepository | None = None
    default_openrouter_model: str = "openai/gpt-4o-mini"
    commit: Callable[[], Awaitable[None]] | None = None
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository | None = None


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
