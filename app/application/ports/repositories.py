from typing import Protocol
from uuid import UUID

from app.domain.campaigns.enrollment import CampaignEnrollment
from app.domain.campaigns.execution import CampaignExecutionConfig
from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.common.ids import (
    LeadId,
    RefreshSessionId,
    UserId,
    UserInvitationId,
    WorkspaceId,
    WorkspaceMembershipId,
)
from app.domain.compliance.contactability import WorkspaceContactPolicy
from app.domain.conversations import Conversation, ConversationSummary, Handoff, InboundMessage
from app.domain.crm_sync import CRMSyncJob, ExternalEvent
from app.domain.identity import (
    AuthAuditLog,
    PasswordCredential,
    PasswordResetToken,
    RefreshSession,
    User,
    UserInvitation,
    Workspace,
    WorkspaceMembership,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import LeadWorkflow, WorkflowTransition


class LeadRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        raise NotImplementedError

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        raise NotImplementedError

    async def get_by_crm_id(
        self,
        workspace_id: WorkspaceId,
        crm_provider: CRMProvider,
        crm_lead_id: str,
    ) -> CanonicalLeadRecord | None:
        raise NotImplementedError

    async def upsert(self, record: CanonicalLeadRecord) -> CanonicalLeadRecord:
        raise NotImplementedError


class OutboundMessageRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        message_id: UUID,
    ) -> OutboundMessage | None:
        raise NotImplementedError

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundMessage | None:
        raise NotImplementedError

    async def get_by_idempotency_key_for_update(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundMessage | None:
        raise NotImplementedError

    async def save(self, message: OutboundMessage) -> OutboundMessage:
        raise NotImplementedError


class CampaignExecutionRepository(Protocol):
    async def get_by_version_id(
        self,
        workspace_id: WorkspaceId,
        campaign_version_id: UUID,
    ) -> CampaignExecutionConfig | None:
        raise NotImplementedError


class CampaignEnrollmentRepository(Protocol):
    async def get_by_lead_and_campaign(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        campaign_id: UUID,
    ) -> CampaignEnrollment | None:
        raise NotImplementedError

    async def save(self, enrollment: CampaignEnrollment) -> CampaignEnrollment:
        raise NotImplementedError


class LeadWorkflowRepository(Protocol):
    async def get_latest_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> LeadWorkflow | None:
        raise NotImplementedError

    async def get_latest_for_lead_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> LeadWorkflow | None:
        raise NotImplementedError

    async def save(self, workflow: LeadWorkflow) -> LeadWorkflow:
        raise NotImplementedError


class WorkflowTransitionRepository(Protocol):
    async def append(self, transition: WorkflowTransition) -> WorkflowTransition:
        raise NotImplementedError

    async def list_for_workflow(
        self,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        limit: int = 100,
    ) -> tuple[WorkflowTransition, ...]:
        raise NotImplementedError


class CRMSyncJobRepository(Protocol):
    async def get_by_id(self, workspace_id: WorkspaceId, sync_job_id: UUID) -> CRMSyncJob | None:
        raise NotImplementedError

    async def list_recent(
        self,
        workspace_id: WorkspaceId,
        limit: int = 100,
    ) -> tuple[CRMSyncJob, ...]:
        raise NotImplementedError

    async def save(self, job: CRMSyncJob) -> CRMSyncJob:
        raise NotImplementedError


class ExternalEventRepository(Protocol):
    async def get_by_provider_event_id(
        self,
        workspace_id: WorkspaceId,
        provider: str,
        provider_event_id: str,
    ) -> ExternalEvent | None:
        raise NotImplementedError

    async def save(self, event: ExternalEvent) -> ExternalEvent:
        raise NotImplementedError


class ConversationRepository(Protocol):
    async def get_latest_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> Conversation | None:
        raise NotImplementedError

    async def save(self, conversation: Conversation) -> Conversation:
        raise NotImplementedError


class InboundMessageRepository(Protocol):
    async def save(self, message: InboundMessage) -> InboundMessage:
        raise NotImplementedError


class ConversationSummaryRepository(Protocol):
    async def save(self, summary: ConversationSummary) -> ConversationSummary:
        raise NotImplementedError


class HandoffRepository(Protocol):
    async def save(self, handoff: Handoff) -> Handoff:
        raise NotImplementedError


class UserRepository(Protocol):
    async def get_by_id(self, user_id: UserId) -> User | None:
        raise NotImplementedError

    async def get_by_email_normalized(self, email_normalized: str) -> User | None:
        raise NotImplementedError

    async def save(self, user: User) -> User:
        raise NotImplementedError


class WorkspaceRepository(Protocol):
    async def get_by_id(self, workspace_id: WorkspaceId) -> Workspace | None:
        raise NotImplementedError

    async def save(self, workspace: Workspace) -> Workspace:
        raise NotImplementedError


class WorkspaceContactPolicyRepository(Protocol):
    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceContactPolicy | None:
        raise NotImplementedError

    async def save(self, policy: WorkspaceContactPolicy) -> WorkspaceContactPolicy:
        raise NotImplementedError


class WorkspaceMembershipRepository(Protocol):
    async def get_by_id(
        self,
        membership_id: WorkspaceMembershipId,
    ) -> WorkspaceMembership | None:
        raise NotImplementedError

    async def get_by_user_and_workspace(
        self,
        user_id: UserId,
        workspace_id: WorkspaceId,
    ) -> WorkspaceMembership | None:
        raise NotImplementedError

    async def list_by_user_id(self, user_id: UserId) -> tuple[WorkspaceMembership, ...]:
        raise NotImplementedError

    async def list_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[WorkspaceMembership, ...]:
        raise NotImplementedError

    async def save(self, membership: WorkspaceMembership) -> WorkspaceMembership:
        raise NotImplementedError


class PasswordCredentialRepository(Protocol):
    async def get_by_user_id(self, user_id: UserId) -> PasswordCredential | None:
        raise NotImplementedError

    async def get_by_user_id_for_update(self, user_id: UserId) -> PasswordCredential | None:
        raise NotImplementedError

    async def save(self, credential: PasswordCredential) -> PasswordCredential:
        raise NotImplementedError


class RefreshSessionRepository(Protocol):
    async def get_by_id(self, session_id: RefreshSessionId) -> RefreshSession | None:
        raise NotImplementedError

    async def get_by_token_hash(self, token_hash: str) -> RefreshSession | None:
        raise NotImplementedError

    async def get_by_token_hash_for_update(self, token_hash: str) -> RefreshSession | None:
        raise NotImplementedError

    async def list_by_user_id(self, user_id: UserId) -> tuple[RefreshSession, ...]:
        raise NotImplementedError

    async def save(self, session: RefreshSession) -> RefreshSession:
        raise NotImplementedError


class PasswordResetTokenRepository(Protocol):
    async def get_by_token_hash(self, token_hash: str) -> PasswordResetToken | None:
        raise NotImplementedError

    async def get_by_token_hash_for_update(self, token_hash: str) -> PasswordResetToken | None:
        raise NotImplementedError

    async def save(self, token: PasswordResetToken) -> PasswordResetToken:
        raise NotImplementedError


class InvitationRepository(Protocol):
    async def get_by_id(self, invitation_id: UserInvitationId) -> UserInvitation | None:
        raise NotImplementedError

    async def get_by_token_hash(self, token_hash: str) -> UserInvitation | None:
        raise NotImplementedError

    async def get_by_token_hash_for_update(self, token_hash: str) -> UserInvitation | None:
        raise NotImplementedError

    async def get_by_workspace_and_email_normalized(
        self,
        workspace_id: WorkspaceId,
        email_normalized: str,
    ) -> UserInvitation | None:
        raise NotImplementedError

    async def save(self, invitation: UserInvitation) -> UserInvitation:
        raise NotImplementedError


class AuthAuditLogRepository(Protocol):
    async def append(self, audit_log: AuthAuditLog) -> AuthAuditLog:
        raise NotImplementedError
