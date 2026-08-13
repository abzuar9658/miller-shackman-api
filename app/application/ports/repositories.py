from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from app.domain.attention import AttentionAcknowledgement
from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageCRMCompletionRecord,
    ProviderDeliveryStatus,
)
from app.domain.campaigns.outbound_provider_failure import OutboundProviderFailure
from app.domain.campaigns.outbound_send_reconciliation import (
    OutboundSendReconciliation,
    OutboundSendReconciliationStatus,
)
from app.domain.campaigns.outbound_send_request import (
    OutboundSendRequest,
    OutboundSendRequestStatus,
)
from app.domain.campaigns.paused_search_notifications import (
    PausedSearchNotification,
    PausedSearchNotificationPolicy,
)
from app.domain.campaigns.paused_search_occurrences import RecurringOccurrence
from app.domain.campaigns.paused_search_reminders import PausedSearchAgentReminder
from app.domain.campaigns.paused_search_reviews import PausedSearchReview
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchTrack,
    PausedSearchTrackAdminAuditLog,
    PausedSearchTrackAssignment,
    PausedSearchTrackCatalogEntry,
    PausedSearchTrackLeadAssignment,
    PausedSearchTrackStep,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.template_registry import TemplateVersion
from app.domain.common.ids import (
    CRMAgentRecordId,
    ExtensionDeviceId,
    LeadId,
    PausedSearchTrackId,
    PausedSearchTrackVersionId,
    RefreshSessionId,
    UserId,
    UserInvitationId,
    WorkspaceId,
    WorkspaceMembershipId,
)
from app.domain.compliance import WorkspaceContactPolicy
from app.domain.compliance.contactability import ContactChannel
from app.domain.conversations import CrmConversationEvent, Handoff, WorkspaceHandoffConfig
from app.domain.crm_agent_mapping import (
    CRMAgent,
    WorkspaceAgentCRMMapping,
    WorkspaceAgentMappingConfig,
)
from app.domain.crm_sync import (
    CRMSyncJob,
    CRMSyncWindowState,
    ExternalEvent,
    WorkspaceCRMSyncConfig,
    WorkspaceCRMSyncScheduleTarget,
)
from app.domain.identity import (
    AuthAuditLog,
    ExtensionDevice,
    ExtensionPairingCode,
    PasswordCredential,
    PasswordResetToken,
    RefreshSession,
    User,
    UserInvitation,
    Workspace,
    WorkspaceMembership,
    WorkspaceMembershipRole,
)
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
    CustomerTimingCandidate,
    LeadClassificationArtifact,
    LeadPausedSearchHistoryEntry,
    LeadRoutingReview,
)
from app.domain.llm import WorkspaceLLMConfig
from app.domain.outbound_drafting import WorkspaceOutboundDraftingConfig
from app.domain.workflows import (
    LeadWorkflow,
    LeadWorkflowOverrideAuditLog,
    TemporalSignalOutboxEntry,
)
from app.domain.workspace_automation import WorkspaceOperationalControl


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

    async def list_by_assigned_agent_crm_id(
        self,
        workspace_id: WorkspaceId,
        assigned_agent_crm_id: str,
    ) -> tuple[CanonicalLeadRecord, ...]:
        raise NotImplementedError

    async def get_by_primary_phone(
        self,
        workspace_id: WorkspaceId,
        phone_number: str,
    ) -> CanonicalLeadRecord | None:
        raise NotImplementedError

    async def get_by_primary_email(
        self,
        workspace_id: WorkspaceId,
        email_address: str,
    ) -> CanonicalLeadRecord | None:
        raise NotImplementedError

    async def list_by_primary_email(
        self,
        workspace_id: WorkspaceId,
        email_address: str,
    ) -> tuple[CanonicalLeadRecord, ...]:
        raise NotImplementedError

    async def upsert(self, record: CanonicalLeadRecord) -> CanonicalLeadRecord:
        raise NotImplementedError


class LeadPausedSearchHistoryRepository(Protocol):
    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[LeadPausedSearchHistoryEntry, ...]:
        raise NotImplementedError

    async def append(
        self,
        entry: LeadPausedSearchHistoryEntry,
    ) -> LeadPausedSearchHistoryEntry:
        raise NotImplementedError


class CustomerTimingRepository(Protocol):
    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> tuple[CustomerTimingCandidate, ...]:
        raise NotImplementedError

    async def save(self, candidate: CustomerTimingCandidate) -> CustomerTimingCandidate:
        raise NotImplementedError


class TemplateRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        template_version_id: UUID,
    ) -> TemplateVersion | None:
        raise NotImplementedError

    async def get_by_key_and_version(
        self,
        workspace_id: WorkspaceId,
        template_key: str,
        version: int,
    ) -> TemplateVersion | None:
        raise NotImplementedError

    async def get_latest_approved_by_key(
        self,
        workspace_id: WorkspaceId,
        template_key: str,
    ) -> TemplateVersion | None:
        raise NotImplementedError

    async def save(self, template: TemplateVersion) -> TemplateVersion:
        raise NotImplementedError

    async def list_approved(self, workspace_id: WorkspaceId) -> tuple[TemplateVersion, ...]:
        raise NotImplementedError


class PausedSearchNotificationPolicyRepository(Protocol):
    async def get_latest(self, workspace_id: WorkspaceId) -> PausedSearchNotificationPolicy | None:
        raise NotImplementedError

    async def save(self, policy: PausedSearchNotificationPolicy) -> PausedSearchNotificationPolicy:
        raise NotImplementedError


class PausedSearchReviewRepository(Protocol):
    async def list_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> tuple[PausedSearchReview, ...]:
        raise NotImplementedError

    async def get_by_id(
        self, workspace_id: WorkspaceId, review_id: UUID
    ) -> PausedSearchReview | None:
        raise NotImplementedError

    async def get_by_id_for_update(
        self, workspace_id: WorkspaceId, review_id: UUID
    ) -> PausedSearchReview | None:
        raise NotImplementedError

    async def get_by_occurrence(
        self,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
        kind: str,
    ) -> PausedSearchReview | None:
        raise NotImplementedError

    async def create_or_get(self, review: PausedSearchReview) -> PausedSearchReview:
        raise NotImplementedError

    async def save(self, review: PausedSearchReview) -> PausedSearchReview:
        raise NotImplementedError


class PausedSearchNotificationRepository(Protocol):
    async def get_by_idempotency_key(
        self, workspace_id: WorkspaceId, idempotency_key: str
    ) -> PausedSearchNotification | None:
        raise NotImplementedError

    async def save(self, notification: PausedSearchNotification) -> PausedSearchNotification:
        raise NotImplementedError


class PausedSearchAgentReminderRepository(Protocol):
    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> PausedSearchAgentReminder | None:
        raise NotImplementedError

    async def create_or_get(
        self,
        reminder: PausedSearchAgentReminder,
    ) -> PausedSearchAgentReminder:
        raise NotImplementedError

    async def cancel_open_for_workflow(
        self,
        *,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        now: datetime,
    ) -> int:
        raise NotImplementedError


class CrmConversationEventRepository(Protocol):
    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[CrmConversationEvent, ...]:
        raise NotImplementedError

    async def save(self, event: CrmConversationEvent) -> CrmConversationEvent:
        raise NotImplementedError


class LeadClassificationArtifactRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        artifact_id: UUID,
    ) -> LeadClassificationArtifact | None:
        raise NotImplementedError

    async def save(
        self,
        artifact: LeadClassificationArtifact,
    ) -> LeadClassificationArtifact:
        raise NotImplementedError

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[LeadClassificationArtifact, ...]:
        raise NotImplementedError


class LeadRoutingReviewRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        review_id: UUID,
    ) -> LeadRoutingReview | None:
        raise NotImplementedError

    async def get_by_artifact_id(
        self,
        workspace_id: WorkspaceId,
        artifact_id: UUID,
    ) -> LeadRoutingReview | None:
        raise NotImplementedError

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 20,
    ) -> tuple[LeadRoutingReview, ...]:
        raise NotImplementedError

    async def list_pending_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[LeadRoutingReview, ...]:
        raise NotImplementedError

    async def save(self, review: LeadRoutingReview) -> LeadRoutingReview:
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

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[OutboundMessage, ...]:
        raise NotImplementedError


    async def get_by_provider_message_id_for_workspace(
        self,
        workspace_id: WorkspaceId,
        provider_name: str,
        provider_message_id: str,
    ) -> OutboundMessage | None:
        raise NotImplementedError

    async def get_by_reply_routing_token(
        self,
        workspace_id: WorkspaceId,
        reply_routing_token: str,
    ) -> OutboundMessage | None:
        raise NotImplementedError

    async def save(self, message: OutboundMessage) -> OutboundMessage:
        raise NotImplementedError


class OutboundMessageCRMCompletionRepository(Protocol):
    async def get_by_outbound_message_id(
        self,
        workspace_id: WorkspaceId,
        outbound_message_id: UUID,
    ) -> OutboundMessageCRMCompletionRecord | None:
        raise NotImplementedError

    async def save(
        self,
        record: OutboundMessageCRMCompletionRecord,
    ) -> OutboundMessageCRMCompletionRecord:
        raise NotImplementedError


class OutboundSendReconciliationRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        reconciliation_id: UUID,
    ) -> OutboundSendReconciliation | None:
        raise NotImplementedError

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundSendReconciliation | None:
        raise NotImplementedError

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        reconciliation_id: UUID,
    ) -> OutboundSendReconciliation | None:
        raise NotImplementedError

    async def get_by_outbound_message_id_for_update(
        self,
        workspace_id: WorkspaceId,
        outbound_message_id: UUID,
    ) -> OutboundSendReconciliation | None:
        raise NotImplementedError

    async def get_by_idempotency_key_for_update(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundSendReconciliation | None:
        raise NotImplementedError

    async def create_or_get(
        self,
        reconciliation: OutboundSendReconciliation,
    ) -> OutboundSendReconciliation:
        raise NotImplementedError

    async def resolve(
        self,
        *,
        workspace_id: WorkspaceId,
        reconciliation_id: UUID,
        status: OutboundSendReconciliationStatus,
        now: datetime,
        provider_message_id: str | None = None,
        provider_delivery_status: ProviderDeliveryStatus | None = None,
        failure_reason: str | None = None,
    ) -> OutboundSendReconciliation | None:
        raise NotImplementedError

class OutboundSendRequestRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        request_id: UUID,
    ) -> OutboundSendRequest | None:
        raise NotImplementedError

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundSendRequest | None:
        raise NotImplementedError

    async def get_by_outbound_message_id(
        self,
        workspace_id: WorkspaceId,
        outbound_message_id: UUID,
    ) -> OutboundSendRequest | None:
        raise NotImplementedError

    async def create_or_get(self, request: OutboundSendRequest) -> OutboundSendRequest:
        raise NotImplementedError

    async def save(self, request: OutboundSendRequest) -> OutboundSendRequest:
        raise NotImplementedError

    async def claim_due_pending(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[OutboundSendRequest, ...]:
        raise NotImplementedError

    async def recover_stale_dispatching(
        self,
        *,
        stale_before: datetime,
        now: datetime,
        limit: int,
    ) -> tuple[OutboundSendRequest, ...]:
        raise NotImplementedError

    async def get_due_pending_summary(
        self,
        *,
        now: datetime,
    ) -> tuple[int, datetime | None]:
        raise NotImplementedError

    async def list_exceptions(
        self,
        *,
        workspace_id: WorkspaceId,
        statuses: tuple[OutboundSendRequestStatus, ...],
        stale_before: datetime,
        older_than: datetime | None = None,
        channel: ContactChannel | None = None,
        provider_name: str | None = None,
        limit: int = 100,
    ) -> tuple[OutboundSendRequest, ...]:
        raise NotImplementedError


class OutboundProviderFailureRepository(Protocol):
    async def create_or_get(
        self,
        failure: OutboundProviderFailure,
    ) -> OutboundProviderFailure:
        raise NotImplementedError

    async def list_open(
        self,
        workspace_id: WorkspaceId,
        limit: int = 100,
    ) -> list[OutboundProviderFailure]:
        raise NotImplementedError

    async def get_by_outbound_message_id(
        self,
        workspace_id: WorkspaceId,
        outbound_message_id: UUID,
    ) -> OutboundProviderFailure | None:
        raise NotImplementedError


class UserRepository(Protocol):
    async def get_by_id(self, user_id: UserId) -> User | None:
        raise NotImplementedError

    async def get_by_email_normalized(self, email_normalized: str) -> User | None:
        raise NotImplementedError

    async def get_active_by_workspace_email_normalized(
        self,
        workspace_id: WorkspaceId,
        email_normalized: str,
        *,
        allowed_roles: tuple[WorkspaceMembershipRole, ...],
    ) -> User | None:
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


class ExtensionPairingCodeRepository(Protocol):
    async def get_by_token_hash_for_update(
        self,
        workspace_id: WorkspaceId,
        token_hash: str,
    ) -> ExtensionPairingCode | None:
        raise NotImplementedError

    async def revoke_pending_for_user(
        self,
        workspace_id: WorkspaceId,
        user_id: UserId,
        *,
        revoked_at: datetime,
    ) -> int:
        raise NotImplementedError

    async def save(self, pairing_code: ExtensionPairingCode) -> ExtensionPairingCode:
        raise NotImplementedError


class ExtensionDeviceRepository(Protocol):
    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        device_id: ExtensionDeviceId,
    ) -> ExtensionDevice | None:
        raise NotImplementedError

    async def list_by_workspace_and_user(
        self,
        workspace_id: WorkspaceId,
        user_id: UserId,
    ) -> tuple[ExtensionDevice, ...]:
        raise NotImplementedError

    async def count_active_for_user(
        self,
        workspace_id: WorkspaceId,
        user_id: UserId,
    ) -> int:
        raise NotImplementedError

    async def save(self, device: ExtensionDevice) -> ExtensionDevice:
        raise NotImplementedError


class ConversationSummaryRepository(Protocol):
    async def get_latest_for_conversation(
        self,
        workspace_id: WorkspaceId,
        conversation_id: UUID,
    ) -> Any | None:
        raise NotImplementedError

    async def save(self, summary: Any) -> Any:
        raise NotImplementedError


class HandoffRepository(Protocol):
    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[Handoff, ...]:
        raise NotImplementedError

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
    async def get_by_id(self, workspace_id: WorkspaceId, inbound_message_id: UUID) -> Any | None:
        raise NotImplementedError

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[Any, ...]:
        raise NotImplementedError


    async def save(self, message: Any) -> Any:
        raise NotImplementedError


class ExternalEventRepository(Protocol):
    async def get_by_provider_event_id(
        self,
        workspace_id: WorkspaceId,
        provider_name: str,
        provider_event_id: str,
    ) -> ExternalEvent | None:
        raise NotImplementedError

    async def save(self, event: ExternalEvent) -> ExternalEvent:
        raise NotImplementedError


class ExternalEventRetryRepository(Protocol):
    async def claim_due_retryable(
        self,
        *,
        provider_name: str,
        now: datetime,
        limit: int = 10,
    ) -> tuple[ExternalEvent, ...]:
        raise NotImplementedError


class CRMAgentRepository(Protocol):
    async def get_by_record_id(
        self,
        workspace_id: WorkspaceId,
        agent_record_id: CRMAgentRecordId,
    ) -> CRMAgent | None:
        raise NotImplementedError

    async def get_by_external_id(
        self,
        workspace_id: WorkspaceId,
        crm_provider: CRMProvider,
        external_agent_id: str,
    ) -> CRMAgent | None:
        raise NotImplementedError

    async def list_for_workspace(self, workspace_id: WorkspaceId) -> tuple[CRMAgent, ...]:
        raise NotImplementedError

    async def save(self, agent: CRMAgent) -> CRMAgent:
        raise NotImplementedError


class WorkspaceAgentCRMMappingRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        mapping_id: UUID,
    ) -> WorkspaceAgentCRMMapping | None:
        raise NotImplementedError

    async def get_by_crm_agent_record_id(
        self,
        workspace_id: WorkspaceId,
        crm_agent_record_id: CRMAgentRecordId,
    ) -> WorkspaceAgentCRMMapping | None:
        raise NotImplementedError

    async def list_for_workspace(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[WorkspaceAgentCRMMapping, ...]:
        raise NotImplementedError

    async def save(self, mapping: WorkspaceAgentCRMMapping) -> WorkspaceAgentCRMMapping:
        raise NotImplementedError


class HandoffCompletionRepository(Protocol):
    async def get_by_handoff_id(self, workspace_id: WorkspaceId, handoff_id: UUID) -> Any | None:
        raise NotImplementedError

    async def save(self, completion: Any) -> Any:
        raise NotImplementedError


class InboundMessageCRMCompletionRepository(Protocol):
    async def get_by_inbound_message_id(
        self,
        workspace_id: WorkspaceId,
        inbound_message_id: UUID,
    ) -> Any | None:
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


class WorkspaceCRMSyncConfigRepository(Protocol):
    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceCRMSyncConfig | None:
        raise NotImplementedError

    async def list_active_workspace_schedule_targets(
        self,
        *,
        limit: int = 100,
        default_interval_seconds: int,
    ) -> tuple[WorkspaceCRMSyncScheduleTarget, ...]:
        raise NotImplementedError

    async def save(self, config: WorkspaceCRMSyncConfig) -> WorkspaceCRMSyncConfig:
        raise NotImplementedError


class CRMSyncWindowStateRepository(Protocol):
    async def get_by_workspace_provider(
        self,
        workspace_id: WorkspaceId,
        crm_provider: str,
    ) -> CRMSyncWindowState | None:
        raise NotImplementedError

    async def save(self, state: CRMSyncWindowState) -> CRMSyncWindowState:
        raise NotImplementedError

    async def delete(self, workspace_id: WorkspaceId, crm_provider: str) -> None:
        raise NotImplementedError


class WorkspaceAgentMappingConfigRepository(Protocol):
    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceAgentMappingConfig | None:
        raise NotImplementedError

    async def save(self, config: WorkspaceAgentMappingConfig) -> WorkspaceAgentMappingConfig:
        raise NotImplementedError


class WorkspaceLLMConfigRepository(Protocol):
    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceLLMConfig | None:
        raise NotImplementedError

    async def save(self, config: WorkspaceLLMConfig) -> WorkspaceLLMConfig:
        raise NotImplementedError


class WorkspaceOutboundDraftingConfigRepository(Protocol):
    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceOutboundDraftingConfig | None:
        raise NotImplementedError

    async def save(
        self,
        config: WorkspaceOutboundDraftingConfig,
    ) -> WorkspaceOutboundDraftingConfig:
        raise NotImplementedError


class WorkspaceOperationalControlRepository(Protocol):
    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceOperationalControl | None:
        raise NotImplementedError

    async def save(
        self,
        control: WorkspaceOperationalControl,
    ) -> WorkspaceOperationalControl:
        raise NotImplementedError


class AttentionAcknowledgementRepository(Protocol):
    async def list_for_user(
        self,
        workspace_id: WorkspaceId,
        user_id: UserId,
    ) -> tuple[AttentionAcknowledgement, ...]:
        raise NotImplementedError

    async def get_by_item_id(
        self,
        workspace_id: WorkspaceId,
        user_id: UserId,
        attention_item_id: str,
    ) -> AttentionAcknowledgement | None:
        raise NotImplementedError

    async def save(
        self,
        acknowledgement: AttentionAcknowledgement,
    ) -> AttentionAcknowledgement:
        raise NotImplementedError

    async def delete(
        self,
        workspace_id: WorkspaceId,
        user_id: UserId,
        attention_item_id: str,
    ) -> None:
        raise NotImplementedError


class CampaignAdminAuditLogRepository(Protocol):
    async def append(self, audit_log: Any) -> Any:
        raise NotImplementedError


class PausedSearchTrackAdminAuditLogRepository(Protocol):
    async def append(
        self,
        audit_log: PausedSearchTrackAdminAuditLog,
    ) -> PausedSearchTrackAdminAuditLog:
        raise NotImplementedError


class PausedSearchTrackRepository(Protocol):
    async def list_active_catalog(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[PausedSearchTrackCatalogEntry, ...]:
        raise NotImplementedError

    async def get_track(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrack | None:
        raise NotImplementedError

    async def get_version(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
    ) -> PausedSearchTrackVersion | None:
        raise NotImplementedError

    async def get_steps(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
    ) -> tuple[PausedSearchTrackStep, ...]:
        raise NotImplementedError


class PausedSearchLegacyInventoryRepository(Protocol):
    async def list_legacy_versions(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[tuple[PausedSearchTrackVersion, tuple[PausedSearchTrackStep, ...]], ...]:
        raise NotImplementedError

    async def list_active_workflows_for_versions(
        self,
        workspace_id: WorkspaceId,
        track_version_ids: tuple[PausedSearchTrackVersionId, ...],
    ) -> tuple[LeadWorkflow, ...]:
        raise NotImplementedError

class PausedSearchTrackAssignmentRepository(Protocol):
    async def get_active_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> PausedSearchTrackAssignment | None:
        raise NotImplementedError

    async def get_active_for_lead_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> PausedSearchTrackAssignment | None:
        raise NotImplementedError

    async def create(
        self,
        assignment: PausedSearchTrackAssignment,
    ) -> PausedSearchTrackAssignment:
        raise NotImplementedError

    async def release_active(
        self,
        *,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        released_at: datetime,
        released_by: UserId | None = None,
        release_reason: str | None = None,
    ) -> PausedSearchTrackAssignment | None:
        raise NotImplementedError


class PausedSearchOccurrenceRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
    ) -> RecurringOccurrence | None:
        raise NotImplementedError

    async def get_latest_for_step(
        self,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        track_version_id: PausedSearchTrackVersionId,
        step_id: UUID,
    ) -> RecurringOccurrence | None:
        raise NotImplementedError

    async def get_by_identity(
        self,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        track_version_id: PausedSearchTrackVersionId,
        step_id: UUID,
        occurrence_number: int,
        scheduled_for: datetime,
    ) -> RecurringOccurrence | None:
        raise NotImplementedError

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> RecurringOccurrence | None:
        raise NotImplementedError

    async def create_or_get(self, occurrence: RecurringOccurrence) -> RecurringOccurrence:
        raise NotImplementedError

    async def get_by_provider_message_id_for_update(
        self,
        workspace_id: WorkspaceId,
        provider_message_id: str,
    ) -> RecurringOccurrence | None:
        raise NotImplementedError

    async def update_status(
        self,
        *,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
        status: str,
        now: datetime,
        provider_message_id: str | None = None,
        provider_delivery_status: ProviderDeliveryStatus | None = None,
        failure_reason: str | None = None,
        fallback_used: bool | None = None,
    ) -> RecurringOccurrence | None:
        raise NotImplementedError

    async def cancel_open_for_workflow(
        self,
        *,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        now: datetime,
        reason: str,
    ) -> int:
        raise NotImplementedError

    async def resolve_uncertain(
        self,
        *,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
        status: str,
        now: datetime,
        reason: str,
    ) -> RecurringOccurrence | None:
        raise NotImplementedError

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
    ) -> RecurringOccurrence | None:
        raise NotImplementedError

class PausedSearchOccurrenceOperationsRepository(Protocol):
    async def list_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        lead_id: UUID | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> tuple[RecurringOccurrence, ...]:
        raise NotImplementedError

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
    ) -> RecurringOccurrence | None:
        raise NotImplementedError

    async def update_status(
        self,
        *,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
        status: str,
        now: datetime,
        provider_message_id: str | None = None,
        provider_delivery_status: ProviderDeliveryStatus | None = None,
        failure_reason: str | None = None,
        fallback_used: bool | None = None,
    ) -> RecurringOccurrence | None:
        raise NotImplementedError


class PausedSearchTrackAdminRepository(Protocol):
    async def list_tracks(self, workspace_id: WorkspaceId) -> tuple[PausedSearchTrack, ...]:
        raise NotImplementedError

    async def list_assigned_leads(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
        *,
        limit: int = 100,
        lock: bool = False,
    ) -> tuple[PausedSearchTrackLeadAssignment, ...]:
        raise NotImplementedError

    async def delete_retired_track(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> None:
        raise NotImplementedError

    async def get_track(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrack | None:
        raise NotImplementedError

    async def get_track_for_update(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrack | None:
        raise NotImplementedError

    async def get_track_by_key(
        self,
        workspace_id: WorkspaceId,
        track_key: str,
    ) -> PausedSearchTrack | None:
        raise NotImplementedError

    async def save_track(self, track: PausedSearchTrack) -> PausedSearchTrack:
        raise NotImplementedError

    async def get_version(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
    ) -> PausedSearchTrackVersion | None:
        raise NotImplementedError

    async def get_latest_draft_version(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrackVersion | None:
        raise NotImplementedError

    async def get_latest_version(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrackVersion | None:
        raise NotImplementedError

    async def get_latest_version_number(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> int:
        raise NotImplementedError

    async def save_version(
        self,
        version: PausedSearchTrackVersion,
    ) -> PausedSearchTrackVersion:
        raise NotImplementedError

    async def get_steps(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
    ) -> tuple[PausedSearchTrackStep, ...]:
        raise NotImplementedError

    async def replace_steps(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
        steps: tuple[PausedSearchTrackStep, ...],
    ) -> tuple[PausedSearchTrackStep, ...]:
        raise NotImplementedError

    async def retire_published_versions(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
        except_version_id: PausedSearchTrackVersionId | None,
    ) -> None:
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

    async def list_active_for_workspace(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[Any, ...]:
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
    async def list_active_paused_search_for_lead_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> tuple[LeadWorkflow, ...]:
        raise NotImplementedError

    async def get_latest_for_lead_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> LeadWorkflow | None:
        raise NotImplementedError

    async def list_paused_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[LeadWorkflow, ...]:
        raise NotImplementedError

    async def save(self, workflow: LeadWorkflow) -> LeadWorkflow:
        raise NotImplementedError


class WorkflowTransitionRepository(Protocol):
    async def append(self, transition: Any) -> Any:
        raise NotImplementedError

    async def list_for_workflow(
        self,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        limit: int = 100,
    ) -> tuple[Any, ...]:
        raise NotImplementedError


class LeadWorkflowOverrideAuditLogRepository(Protocol):
    async def append(
        self,
        audit_log: LeadWorkflowOverrideAuditLog,
    ) -> LeadWorkflowOverrideAuditLog:
        raise NotImplementedError


class TemporalSignalOutboxRepository(Protocol):
    async def append(self, entry: TemporalSignalOutboxEntry) -> TemporalSignalOutboxEntry:
        raise NotImplementedError

    async def claim_available_batch(
        self,
        *,
        now: datetime,
        limit: int,
        lease_duration: timedelta,
        max_attempts: int,
    ) -> tuple[TemporalSignalOutboxEntry, ...]:
        raise NotImplementedError

    async def mark_sent(
        self,
        temporal_signal_id: UUID,
        *,
        now: datetime,
    ) -> TemporalSignalOutboxEntry:
        raise NotImplementedError

    async def mark_failed(
        self,
        temporal_signal_id: UUID,
        *,
        error: str,
        available_at: datetime,
        now: datetime,
    ) -> TemporalSignalOutboxEntry:
        raise NotImplementedError

    async def mark_terminal_failure(
        self,
        temporal_signal_id: UUID,
        *,
        error: str,
        now: datetime,
    ) -> TemporalSignalOutboxEntry:
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
    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        message_id: UUID,
    ) -> Any | None:
        raise NotImplementedError

    async def get_by_provider_message_id(
        self,
        provider_name: str,
        provider_message_id: str,
    ) -> Any | None:
        raise NotImplementedError

    async def get_by_provider_message_id_for_update(
        self,
        provider_name: str,
        provider_message_id: str,
    ) -> Any | None:
        raise NotImplementedError

    async def save(self, message: Any) -> Any:
        raise NotImplementedError


class ProviderMessageEventRepository(Protocol):
    async def get_by_external_provider_event_id(
        self,
        provider_name: str,
        external_event_id: str,
    ) -> Any | None:
        raise NotImplementedError

    async def save(self, event: Any) -> Any:
        raise NotImplementedError


class CRMSyncJobRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        sync_job_id: UUID,
    ) -> CRMSyncJob | None:
        raise NotImplementedError

    async def list_recent(
        self,
        workspace_id: WorkspaceId,
        limit: int = 100,
    ) -> tuple[CRMSyncJob, ...]:
        raise NotImplementedError

    async def get_latest_for_workspace_provider(
        self,
        workspace_id: WorkspaceId,
        crm_provider: str,
    ) -> CRMSyncJob | None:
        raise NotImplementedError

    async def get_latest_completed_for_workspace_provider(
        self,
        workspace_id: WorkspaceId,
        crm_provider: str,
    ) -> CRMSyncJob | None:
        raise NotImplementedError

    async def get_active_for_workspace_provider(
        self,
        workspace_id: WorkspaceId,
        crm_provider: str,
    ) -> CRMSyncJob | None:
        raise NotImplementedError

    async def insert_pending_if_no_active(
        self,
        job: CRMSyncJob,
    ) -> CRMSyncJob | None:
        raise NotImplementedError

    async def claim_pending_by_id(
        self,
        workspace_id: WorkspaceId,
        sync_job_id: UUID,
        *,
        now: datetime,
    ) -> CRMSyncJob | None:
        raise NotImplementedError

    async def fail_stale_active_jobs(
        self,
        *,
        now: datetime,
        pending_timeout_seconds: int,
        running_timeout_seconds: int,
    ) -> int:
        raise NotImplementedError

    async def touch_running_heartbeat(
        self,
        workspace_id: WorkspaceId,
        sync_job_id: UUID,
        *,
        now: datetime,
    ) -> CRMSyncJob | None:
        raise NotImplementedError

    async def save_if_running(self, job: CRMSyncJob) -> CRMSyncJob | None:
        raise NotImplementedError

    async def save(self, job: CRMSyncJob) -> CRMSyncJob:
        raise NotImplementedError
