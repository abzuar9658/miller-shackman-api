from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.lead_activity import LeadActivityRepository
from app.application.ports.lead_read import (
    LeadReadClassificationArtifactRepository,
    LeadReadCrmConversationEventRepository,
    LeadReadHandoffRepository,
    LeadReadInboundMessageRepository,
    LeadReadLeadRepository,
    LeadReadOutboundMessageRepository,
    LeadReadPausedSearchHistoryRepository,
    LeadReadPausedSearchTrackRepository,
    LeadReadUserRepository,
    LeadReadWorkflowOverrideAuditRepository,
    LeadReadWorkflowRepository,
    LeadReadWorkflowTransitionRepository,
)
from app.application.ports.rejected_draft_review import RejectedDraftReviewRepository
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    CampaignExecutionRepository,
    CRMAgentRepository,
    LeadRoutingReviewRepository,
    PausedSearchTrackAssignmentRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceRepository,
)
from app.core.database import get_session
from app.infrastructure.persistence.postgres.campaign_enrollment_repository import (
    PostgresCampaignEnrollmentRepository,
)
from app.infrastructure.persistence.postgres.campaign_execution_repository import (
    PostgresCampaignExecutionRepository,
)
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresCrmConversationEventRepository,
    PostgresHandoffRepository,
    PostgresInboundMessageRepository,
)
from app.infrastructure.persistence.postgres.crm_agent_mapping_repository import (
    PostgresCRMAgentRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresUserRepository,
    PostgresWorkspaceRepository,
)
from app.infrastructure.persistence.postgres.lead_activity_repository import (
    PostgresLeadActivityRepository,
)
from app.infrastructure.persistence.postgres.lead_classification_artifact_repository import (
    PostgresLeadClassificationArtifactRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.lead_routing_review_repository import (
    PostgresLeadRoutingReviewRepository,
)
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.paused_search_track_repository import (
    PostgresPausedSearchTrackAdminRepository,
    PostgresPausedSearchTrackAssignmentRepository,
)
from app.infrastructure.persistence.postgres.rejected_draft_review_repository import (
    PostgresRejectedDraftReviewRepository,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowOverrideAuditLogRepository,
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from app.infrastructure.persistence.postgres.workspace_contact_policy_repository import (
    PostgresWorkspaceContactPolicyRepository,
)


@dataclass
class LeadReadBundle:
    lead_repository: LeadReadLeadRepository
    paused_search_history_repository: LeadReadPausedSearchHistoryRepository
    classification_artifact_repository: LeadReadClassificationArtifactRepository
    workflow_repository: LeadReadWorkflowRepository
    workflow_override_audit_repository: LeadReadWorkflowOverrideAuditRepository
    workflow_transition_repository: LeadReadWorkflowTransitionRepository
    paused_search_track_repository: LeadReadPausedSearchTrackRepository
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository
    activity_repository: LeadActivityRepository
    rejected_draft_review_repository: RejectedDraftReviewRepository
    inbound_message_repository: LeadReadInboundMessageRepository
    outbound_message_repository: LeadReadOutboundMessageRepository
    crm_conversation_event_repository: LeadReadCrmConversationEventRepository
    handoff_repository: LeadReadHandoffRepository
    user_repository: LeadReadUserRepository
    crm_agent_repository: CRMAgentRepository
    routing_review_repository: LeadRoutingReviewRepository
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository
    campaign_enrollment_repository: CampaignEnrollmentRepository
    campaign_execution_repository: CampaignExecutionRepository
    workspace_repository: WorkspaceRepository


async def get_lead_read_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LeadReadBundle:
    return LeadReadBundle(
        lead_repository=PostgresLeadRepository(session),
        paused_search_history_repository=PostgresLeadRepository(session),
        classification_artifact_repository=PostgresLeadClassificationArtifactRepository(session),
        workflow_repository=PostgresLeadWorkflowRepository(session),
        workflow_override_audit_repository=PostgresLeadWorkflowOverrideAuditLogRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        paused_search_track_repository=PostgresPausedSearchTrackAdminRepository(session),
        paused_search_track_assignment_repository=PostgresPausedSearchTrackAssignmentRepository(
            session
        ),
        activity_repository=PostgresLeadActivityRepository(session),
        rejected_draft_review_repository=PostgresRejectedDraftReviewRepository(session),
        inbound_message_repository=PostgresInboundMessageRepository(session),
        outbound_message_repository=PostgresOutboundMessageRepository(session),
        crm_conversation_event_repository=PostgresCrmConversationEventRepository(session),
        handoff_repository=PostgresHandoffRepository(session),
        user_repository=PostgresUserRepository(session),
        crm_agent_repository=PostgresCRMAgentRepository(session),
        routing_review_repository=PostgresLeadRoutingReviewRepository(session),
        workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
        campaign_enrollment_repository=PostgresCampaignEnrollmentRepository(session),
        campaign_execution_repository=PostgresCampaignExecutionRepository(session),
        workspace_repository=PostgresWorkspaceRepository(session),
    )
