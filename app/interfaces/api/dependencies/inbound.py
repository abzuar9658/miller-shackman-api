from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.crm import CRMClient
from app.application.ports.event_bus import EventBus
from app.application.ports.llm import LLMClient
from app.application.ports.messaging import EmailProvider, SMSProvider
from app.application.ports.notifications import NotificationProvider
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    CampaignExecutionRepository,
    ConversationRepository,
    ConversationSummaryRepository,
    CrmConversationEventRepository,
    ExternalEventRepository,
    HandoffCompletionRepository,
    HandoffRepository,
    InboundMessageCRMCompletionRepository,
    InboundMessageRepository,
    LeadClassificationArtifactRepository,
    LeadRepository,
    LeadRoutingReviewRepository,
    LeadWorkflowRepository,
    OutboundMessageCRMCompletionRepository,
    OutboundMessageRepository,
    PausedSearchAgentReminderRepository,
    PausedSearchOccurrenceRepository,
    PausedSearchTrackAssignmentRepository,
    PausedSearchTrackRepository,
    TemporalSignalOutboxRepository,
    UserRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceOperationalControlRepository,
    WorkspaceOutboundDraftingConfigRepository,
    WorkspaceRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.application.use_cases.process_inbound_message_event import (
    InboundMessageEvent,
    ProcessInboundMessageEventResult,
    process_inbound_message_event,
)
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.domain.crm_sync import ExternalEvent
from app.infrastructure.persistence.postgres.campaign_enrollment_repository import (
    PostgresCampaignEnrollmentRepository,
)
from app.infrastructure.persistence.postgres.campaign_execution_repository import (
    PostgresCampaignExecutionRepository,
)
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresConversationRepository,
    PostgresConversationSummaryRepository,
    PostgresCrmConversationEventRepository,
    PostgresHandoffCompletionRepository,
    PostgresHandoffRepository,
    PostgresInboundMessageCRMCompletionRepository,
    PostgresInboundMessageRepository,
)
from app.infrastructure.persistence.postgres.crm_sync_repository import (
    PostgresExternalEventRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresUserRepository,
    PostgresWorkspaceRepository,
)
from app.infrastructure.persistence.postgres.lead_classification_artifact_repository import (
    PostgresLeadClassificationArtifactRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.lead_routing_review_repository import (
    PostgresLeadRoutingReviewRepository,
)
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageCRMCompletionRepository,
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)
from app.infrastructure.persistence.postgres.paused_search_agent_reminder_repository import (
    PostgresPausedSearchAgentReminderRepository,
)
from app.infrastructure.persistence.postgres.paused_search_occurrence_repository import (
    PostgresPausedSearchOccurrenceRepository,
)
from app.infrastructure.persistence.postgres.paused_search_track_repository import (
    PostgresPausedSearchTrackAdminRepository,
    PostgresPausedSearchTrackAssignmentRepository,
)
from app.infrastructure.persistence.postgres.temporal_signal_outbox_repository import (
    PostgresTemporalSignalOutboxRepository,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from app.infrastructure.persistence.postgres.workspace_contact_policy_repository import (
    PostgresWorkspaceContactPolicyRepository,
)
from app.infrastructure.persistence.postgres.workspace_handoff_config_repository import (
    PostgresWorkspaceHandoffConfigRepository,
)
from app.infrastructure.persistence.postgres.workspace_llm_config_repository import (
    PostgresWorkspaceLLMConfigRepository,
)
from app.infrastructure.persistence.postgres.workspace_operational_control_repository import (
    PostgresWorkspaceOperationalControlRepository,
)
from app.infrastructure.persistence.postgres.workspace_outbound_drafting_config_repository import (
    PostgresWorkspaceOutboundDraftingConfigRepository,
)
from app.infrastructure.providers import (
    build_crm_client,
    build_email_provider,
    build_llm_client,
    build_notification_provider,
    build_sms_provider,
    build_temporal_workflow_starter,
)


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class InboundServiceBundle:
    session: SessionCommitter
    lead_repository: LeadRepository
    external_event_repository: ExternalEventRepository
    conversation_repository: ConversationRepository
    inbound_message_repository: InboundMessageRepository
    crm_conversation_event_repository: CrmConversationEventRepository
    lead_classification_artifact_repository: LeadClassificationArtifactRepository
    conversation_summary_repository: ConversationSummaryRepository
    handoff_repository: HandoffRepository
    handoff_completion_repository: HandoffCompletionRepository
    inbound_message_crm_completion_repository: InboundMessageCRMCompletionRepository
    outbound_message_crm_completion_repository: OutboundMessageCRMCompletionRepository
    paused_search_track_repository: PausedSearchTrackRepository
    lead_workflow_repository: LeadWorkflowRepository
    workflow_transition_repository: WorkflowTransitionRepository
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository
    workspace_llm_config_repository: WorkspaceLLMConfigRepository
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository
    crm_client: CRMClient
    notification_provider: NotificationProvider
    llm_client: LLMClient
    event_bus: EventBus
    default_openrouter_model: str
    workspace_repository: WorkspaceRepository
    campaign_execution_repository: CampaignExecutionRepository
    campaign_enrollment_repository: CampaignEnrollmentRepository
    temporal_workflow_starter: TemporalWorkflowStarter
    workspace_operational_control_repository: WorkspaceOperationalControlRepository
    workspace_outbound_drafting_config_repository: WorkspaceOutboundDraftingConfigRepository
    message_repository: OutboundMessageRepository
    sms_provider: SMSProvider
    email_provider: EmailProvider
    user_repository: UserRepository | None = None
    routing_review_repository: LeadRoutingReviewRepository | None = None
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository | None = None
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None = None
    paused_search_reminder_repository: PausedSearchAgentReminderRepository | None = None
    rollback: Callable[[], Awaitable[None]] | None = None


async def process_inbound_message_event_with_bundle(
    *,
    event: InboundMessageEvent,
    bundle: InboundServiceBundle,
    now: datetime,
    claimed_external_event: ExternalEvent | None = None,
) -> ProcessInboundMessageEventResult:
    return await process_inbound_message_event(
        event=event,
        claimed_external_event=claimed_external_event,
        lead_repository=bundle.lead_repository,
        external_event_repository=bundle.external_event_repository,
        conversation_repository=bundle.conversation_repository,
        inbound_message_repository=bundle.inbound_message_repository,
        crm_conversation_event_repository=bundle.crm_conversation_event_repository,
        lead_classification_artifact_repository=bundle.lead_classification_artifact_repository,
        routing_review_repository=bundle.routing_review_repository,
        conversation_summary_repository=bundle.conversation_summary_repository,
        handoff_repository=bundle.handoff_repository,
        crm_client=bundle.crm_client,
        inbound_message_crm_completion_repository=bundle.inbound_message_crm_completion_repository,
        outbound_message_crm_completion_repository=(
            bundle.outbound_message_crm_completion_repository
        ),
        notification_provider=bundle.notification_provider,
        workspace_handoff_config_repository=bundle.workspace_handoff_config_repository,
        workspace_llm_config_repository=bundle.workspace_llm_config_repository,
        handoff_completion_repository=bundle.handoff_completion_repository,
        user_repository=bundle.user_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        paused_search_track_repository=bundle.paused_search_track_repository,
        paused_search_track_assignment_repository=(
            bundle.paused_search_track_assignment_repository
        ),
        paused_search_occurrence_repository=bundle.paused_search_occurrence_repository,
        paused_search_reminder_repository=bundle.paused_search_reminder_repository,
        llm_client=bundle.llm_client,
        event_bus=bundle.event_bus,
        temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
        default_openrouter_model=bundle.default_openrouter_model,
        workspace_contact_policy_repository=bundle.workspace_contact_policy_repository,
        workspace_repository=bundle.workspace_repository,
        campaign_execution_repository=bundle.campaign_execution_repository,
        campaign_enrollment_repository=bundle.campaign_enrollment_repository,
        workspace_operational_control_repository=bundle.workspace_operational_control_repository,
        workspace_outbound_drafting_config_repository=(
            bundle.workspace_outbound_drafting_config_repository
        ),
        message_repository=bundle.message_repository,
        sms_provider=bundle.sms_provider,
        email_provider=bundle.email_provider,
        now=now,
    )


async def get_inbound_service_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InboundServiceBundle:
    return InboundServiceBundle(
        session=session,
        lead_repository=PostgresLeadRepository(session),
        external_event_repository=PostgresExternalEventRepository(session),
        conversation_repository=PostgresConversationRepository(session),
        inbound_message_repository=PostgresInboundMessageRepository(session),
        crm_conversation_event_repository=PostgresCrmConversationEventRepository(session),
        lead_classification_artifact_repository=PostgresLeadClassificationArtifactRepository(
            session
        ),
        conversation_summary_repository=PostgresConversationSummaryRepository(session),
        handoff_repository=PostgresHandoffRepository(session),
        handoff_completion_repository=PostgresHandoffCompletionRepository(session),
        user_repository=PostgresUserRepository(session),
        inbound_message_crm_completion_repository=PostgresInboundMessageCRMCompletionRepository(
            session
        ),
        outbound_message_crm_completion_repository=PostgresOutboundMessageCRMCompletionRepository(
            session
        ),
        paused_search_track_repository=PostgresPausedSearchTrackAdminRepository(session),
        paused_search_track_assignment_repository=PostgresPausedSearchTrackAssignmentRepository(
            session
        ),
        paused_search_occurrence_repository=PostgresPausedSearchOccurrenceRepository(session),
        paused_search_reminder_repository=PostgresPausedSearchAgentReminderRepository(session),
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
        workspace_handoff_config_repository=PostgresWorkspaceHandoffConfigRepository(session),
        workspace_llm_config_repository=PostgresWorkspaceLLMConfigRepository(session),
        temporal_signal_outbox_repository=PostgresTemporalSignalOutboxRepository(session),
        crm_client=build_crm_client(settings),
        notification_provider=build_notification_provider(settings),
        llm_client=build_llm_client(settings),
        event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
        default_openrouter_model=settings.openrouter_model,
        workspace_repository=PostgresWorkspaceRepository(session),
        campaign_execution_repository=PostgresCampaignExecutionRepository(session),
        campaign_enrollment_repository=PostgresCampaignEnrollmentRepository(session),
        temporal_workflow_starter=await build_temporal_workflow_starter(settings),
        workspace_operational_control_repository=PostgresWorkspaceOperationalControlRepository(
            session
        ),
        workspace_outbound_drafting_config_repository=PostgresWorkspaceOutboundDraftingConfigRepository(
            session
        ),
        message_repository=PostgresOutboundMessageRepository(session),
        sms_provider=build_sms_provider(settings),
        email_provider=build_email_provider(settings),
        routing_review_repository=PostgresLeadRoutingReviewRepository(session),
        rollback=session.rollback,
    )
