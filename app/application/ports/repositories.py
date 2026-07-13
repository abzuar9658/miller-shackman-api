from typing import Any, Protocol
from uuid import UUID

from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.common.ids import (
    LeadId,
    RefreshSessionId,
    UserId,
    UserInvitationId,
    WorkspaceId,
    WorkspaceMembershipId,
)
from app.domain.compliance import WorkspaceContactPolicy
from app.domain.conversations import Handoff, WorkspaceHandoffConfig
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


class ConversationSummaryRepository(Protocol):
    async def save(self, summary: Any) -> Any:
        raise NotImplementedError


class HandoffRepository(Protocol):
    async def list_handoffs(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[Handoff, ...]:
        raise NotImplementedError

    async def get_by_id(self, workspace_id: WorkspaceId, handoff_id: UUID) -> Handoff | None:
        raise NotImplementedError

    async def save(self, handoff: Handoff) -> Handoff:
        raise NotImplementedError


class ConversationRepository(Protocol):
    async def get_latest_for_lead(self, workspace_id: WorkspaceId, lead_id: LeadId) -> Any | None:
        raise NotImplementedError

    async def save(self, conversation: Any) -> Any:
        raise NotImplementedError


class InboundMessageRepository(Protocol):
    async def save(self, message: Any) -> Any:
        raise NotImplementedError


class ExternalEventRepository(Protocol):
    async def get_by_provider_event_id(
        self,
        workspace_id: WorkspaceId,
        provider_name: str,
        provider_event_id: str,
    ) -> Any | None:
        raise NotImplementedError

    async def save(self, event: Any) -> Any:
        raise NotImplementedError


class HandoffCompletionRepository(Protocol):
    async def get_by_handoff_id(self, workspace_id: WorkspaceId, handoff_id: UUID) -> Any | None:
        raise NotImplementedError

    async def save(self, completion: Any) -> Any:
        raise NotImplementedError


class WorkspaceHandoffConfigRepository(Protocol):
    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceHandoffConfig | None:
        raise NotImplementedError

    async def save(self, config: WorkspaceHandoffConfig) -> WorkspaceHandoffConfig:
        raise NotImplementedError


class CampaignAdminAuditLogRepository(Protocol):
    async def append(self, audit_log: Any) -> Any:
        raise NotImplementedError


class CampaignAdminRepository(Protocol):
    async def get_campaign_by_name(self, workspace_id: WorkspaceId, name: str) -> Any | None:
        raise NotImplementedError

    async def save_campaign(self, campaign: Any) -> Any:
        raise NotImplementedError

    async def save_version(self, version: Any) -> Any:
        raise NotImplementedError

    async def replace_cadence_steps(
        self,
        workspace_id: WorkspaceId,
        version_id: UUID,
        steps: tuple[Any, ...],
    ) -> tuple[Any, ...]:
        raise NotImplementedError

    async def get_campaign(self, workspace_id: WorkspaceId, campaign_id: UUID) -> Any | None:
        raise NotImplementedError

    async def get_latest_draft_version(
        self,
        workspace_id: WorkspaceId,
        campaign_id: UUID,
    ) -> Any | None:
        raise NotImplementedError

    async def get_latest_version_number(self, workspace_id: WorkspaceId, campaign_id: UUID) -> int:
        raise NotImplementedError

    async def get_version(self, workspace_id: WorkspaceId, version_id: UUID) -> Any | None:
        raise NotImplementedError

    async def get_cadence_steps(
        self,
        workspace_id: WorkspaceId,
        version_id: UUID,
    ) -> tuple[Any, ...]:
        raise NotImplementedError

    async def retire_published_versions(
        self,
        workspace_id: WorkspaceId,
        campaign_id: UUID,
        except_version_id: UUID,
    ) -> None:
        raise NotImplementedError

    async def list_campaigns(self, workspace_id: WorkspaceId) -> tuple[Any, ...]:
        raise NotImplementedError

    async def get_latest_version(self, workspace_id: WorkspaceId, campaign_id: UUID) -> Any | None:
        raise NotImplementedError


class CampaignExecutionRepository(Protocol):
    async def get_by_version_id(self, workspace_id: WorkspaceId, version_id: UUID) -> Any | None:
        raise NotImplementedError

    async def get_active_for_campaign(
        self,
        workspace_id: WorkspaceId,
        campaign_id: UUID,
    ) -> Any | None:
        raise NotImplementedError


class CampaignEnrollmentRepository(Protocol):
    async def save(self, enrollment: Any) -> Any:
        raise NotImplementedError

    async def get_by_lead_and_campaign(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        campaign_id: UUID,
    ) -> Any | None:
        raise NotImplementedError

    async def count_started_today(
        self,
        workspace_id: WorkspaceId,
        campaign_id: UUID,
        started_since: Any,
    ) -> int:
        raise NotImplementedError


class LeadWorkflowRepository(Protocol):
    async def get_latest_for_lead_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> Any | None:
        raise NotImplementedError

    async def save(self, workflow: Any) -> Any:
        raise NotImplementedError


class WorkflowTransitionRepository(Protocol):
    async def append(self, transition: Any) -> Any:
        raise NotImplementedError


class WorkspaceContactPolicyRepository(Protocol):
    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceContactPolicy | None:
        raise NotImplementedError

    async def save(self, policy: WorkspaceContactPolicy) -> WorkspaceContactPolicy:
        raise NotImplementedError


class ProviderDeliveryMessageRepository(Protocol):
    async def get_by_provider_message_id_for_update(
        self,
        workspace_id: WorkspaceId,
        provider_name: str,
        provider_message_id: str,
    ) -> Any | None:
        raise NotImplementedError

    async def save(self, message: Any) -> Any:
        raise NotImplementedError


class ProviderMessageEventRepository(Protocol):
    async def get_by_external_provider_event_id(
        self,
        workspace_id: WorkspaceId,
        provider_name: str,
        external_event_id: str,
    ) -> Any | None:
        raise NotImplementedError

    async def save(self, event: Any) -> Any:
        raise NotImplementedError


class CRMSyncJobRepository(Protocol):
    async def get_by_id(self, workspace_id: WorkspaceId, sync_job_id: UUID) -> Any | None:
        raise NotImplementedError

    async def list_recent(self, workspace_id: WorkspaceId, limit: int = 100) -> tuple[Any, ...]:
        raise NotImplementedError

    async def save(self, job: Any) -> Any:
        raise NotImplementedError
