from typing import Protocol
from uuid import UUID

from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.common.ids import (
    LeadId,
    RefreshSessionId,
    UserId,
    WorkspaceId,
    WorkspaceMembershipId,
)
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