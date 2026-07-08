from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LeadModel(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "crm_provider",
            "crm_lead_id",
            name="uq_leads_workspace_crm_identity",
        ),
        Index("ix_leads_workspace_lead_type", "workspace_id", "lead_type"),
        Index(
            "ix_leads_workspace_last_meaningful",
            "workspace_id",
            "last_meaningful_communication_at",
        ),
    )

    lead_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    crm_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    crm_lead_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_payload_version: Mapped[str] = mapped_column(String(100), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    facts_derived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assigned_agent_crm_id: Mapped[str | None] = mapped_column(String(255))
    assigned_agent_name_present: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    has_accountable_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ownership_last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lead_type: Mapped[str] = mapped_column(String(50), nullable=False)
    classification_reason: Mapped[str] = mapped_column(String(100), nullable=False)
    crm_type_raw: Mapped[str | None] = mapped_column(String(255))
    lead_source: Mapped[str] = mapped_column(String(255), nullable=False, default="unknown")
    lead_stage: Mapped[str] = mapped_column(String(255), nullable=False, default="unknown")
    created_via: Mapped[str] = mapped_column(String(255), nullable=False, default="unknown")
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    mapped_custom_fields: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    primary_email: Mapped[str | None] = mapped_column(String(320))
    primary_phone: Mapped[str | None] = mapped_column(String(50))
    has_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_phone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_sms_capable_phone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    phone_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sms_permission_status: Mapped[str] = mapped_column(String(50), nullable=False)
    email_permission_status: Mapped[str] = mapped_column(String(50), nullable=False)
    sms_opted_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email_unsubscribed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    do_not_contact: Mapped[bool | None] = mapped_column(Boolean)
    suppression_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    permission_evidence: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    crm_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crm_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_meaningful_communication_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    last_agent_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contacted_count: Mapped[int | None] = mapped_column(Integer)
    activity_reliability: Mapped[str] = mapped_column(String(50), nullable=False)
    latest_property_event_type: Mapped[str | None] = mapped_column(String(50))
    latest_property_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_property_price_band: Mapped[str | None] = mapped_column(String(50))
    latest_property_context_present: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OutboundMessageModel(Base):
    __tablename__ = "outbound_messages"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_outbound_messages_workspace_idempotency_key",
        ),
        Index("ix_outbound_messages_workspace_lead", "workspace_id", "lead_id"),
        Index("ix_outbound_messages_workspace_status", "workspace_id", "status"),
    )

    message_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    lead_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    cadence_step_id: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(String(4000), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(255))
    html_body: Mapped[str | None] = mapped_column(String(8000))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    provider_send_status: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    draft_prompt_version: Mapped[str | None] = mapped_column(String(100))
    draft_model: Mapped[str | None] = mapped_column(String(100))
    draft_latency_ms: Mapped[int | None] = mapped_column(Integer)
    draft_usage_tokens: Mapped[int | None] = mapped_column(Integer)
    draft_confidence: Mapped[float | None] = mapped_column(Float)
    draft_personalization_notes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    draft_safety_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserModel(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email_normalized", name="uq_users_email_normalized"),
        Index("ix_users_email_normalized", "email_normalized"),
    )

    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceModel(Base):
    __tablename__ = "workspaces"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    default_timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceMembershipModel(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_workspace_memberships_workspace_user",
        ),
        Index("ix_workspace_memberships_user", "user_id"),
        Index("ix_workspace_memberships_workspace_status", "workspace_id", "status"),
    )

    membership_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PasswordCredentialModel(Base):
    __tablename__ = "password_credentials"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        primary_key=True,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RefreshSessionModel(Base):
    __tablename__ = "refresh_sessions"
    __table_args__ = (
        UniqueConstraint("refresh_token_hash", name="uq_refresh_sessions_token_hash"),
        Index("ix_refresh_sessions_user", "user_id"),
        Index("ix_refresh_sessions_family", "family_id"),
        Index("ix_refresh_sessions_workspace_user", "workspace_id", "user_id"),
    )

    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    family_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    rotated_from_session_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasswordResetTokenModel(Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
        Index("ix_password_reset_tokens_user", "user_id"),
    )

    reset_token_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserInvitationModel(Base):
    __tablename__ = "user_invitations"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_user_invitations_token_hash"),
        Index("ix_user_invitations_workspace_email", "workspace_id", "email_normalized"),
        Index("ix_user_invitations_user", "user_id"),
    )

    invitation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthAuditLogModel(Base):
    __tablename__ = "auth_audit_logs"
    __table_args__ = (
        Index("ix_auth_audit_logs_workspace_created", "workspace_id", "created_at"),
        Index("ix_auth_audit_logs_actor_created", "actor_user_id", "created_at"),
        Index("ix_auth_audit_logs_subject_created", "subject_user_id", "created_at"),
    )

    audit_log_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
    )
    subject_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_details: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CRMSyncJobModel(Base):
    __tablename__ = "crm_sync_jobs"
    __table_args__ = (
        Index(
            "ix_crm_sync_jobs_workspace_provider_created",
            "workspace_id",
            "crm_provider",
            "created_at",
        ),
        Index("ix_crm_sync_jobs_workspace_status_created", "workspace_id", "status", "created_at"),
    )

    sync_job_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    crm_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    sync_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_upserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_reason: Mapped[str | None] = mapped_column(String(1000))
    created_by_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExternalEventModel(Base):
    __tablename__ = "external_events"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            "provider_event_id",
            name="uq_external_events_workspace_provider_event",
        ),
        Index(
            "ix_external_events_workspace_provider_received",
            "workspace_id",
            "provider",
            "received_at",
        ),
        Index(
            "ix_external_events_workspace_status_received", "workspace_id", "status", "received_at"
        ),
        Index(
            "ix_external_events_workspace_lead_received", "workspace_id", "lead_id", "received_at"
        ),
    )

    external_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    crm_lead_id: Mapped[str | None] = mapped_column(String(255))
    lead_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_redacted: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    failure_reason: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LeadWorkflowModel(Base):
    __tablename__ = "lead_workflows"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "temporal_workflow_id",
            name="uq_lead_workflows_workspace_temporal_id",
        ),
        Index("ix_lead_workflows_workspace_state_next", "workspace_id", "state", "next_action_at"),
        Index(
            "ix_lead_workflows_workspace_lead_transition",
            "workspace_id",
            "lead_id",
            "last_transition_at",
        ),
    )

    workflow_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    temporal_workflow_id: Mapped[str] = mapped_column(String(255), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    campaign_enrollment_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    lead_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    current_step_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_transition_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pause_reason: Mapped[str | None] = mapped_column(String(255))
    resume_reason: Mapped[str | None] = mapped_column(String(500))
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkflowTransitionModel(Base):
    __tablename__ = "workflow_transitions"
    __table_args__ = (
        Index(
            "ix_workflow_transitions_workspace_workflow_created",
            "workspace_id",
            "workflow_id",
            "created_at",
        ),
    )

    transition_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    workflow_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("lead_workflows.workflow_id"),
        nullable=False,
    )
    lead_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(50))
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    external_event_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
    )


class ConversationModel(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_workspace_lead_updated", "workspace_id", "lead_id", "updated_at"),
        Index("ix_conversations_workspace_status", "workspace_id", "status"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    lead_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    campaign_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    workflow_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    ai_interaction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InboundMessageModel(Base):
    __tablename__ = "inbound_messages"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            "provider_message_id",
            name="uq_inbound_messages_workspace_provider_message",
        ),
        Index(
            "ix_inbound_messages_workspace_lead_received", "workspace_id", "lead_id", "received_at"
        ),
        Index(
            "ix_inbound_messages_workspace_classification", "workspace_id", "classification_status"
        ),
    )

    inbound_message_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.conversation_id"),
        nullable=False,
    )
    lead_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_event_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    from_address_redacted: Mapped[str | None] = mapped_column(String(255))
    to_address_redacted: Mapped[str | None] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    classification_status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConversationSummaryModel(Base):
    __tablename__ = "conversation_summaries"
    __table_args__ = (
        Index(
            "ix_conversation_summaries_workspace_conversation_created",
            "workspace_id",
            "conversation_id",
            "created_at",
        ),
    )

    summary_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.conversation_id"),
        nullable=False,
    )
    lead_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    preferences: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HandoffModel(Base):
    __tablename__ = "handoffs"
    __table_args__ = (
        Index("ix_handoffs_workspace_status_created", "workspace_id", "status", "created_at"),
        Index(
            "ix_handoffs_workspace_agent_status", "workspace_id", "assigned_agent_user_id", "status"
        ),
    )

    handoff_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    lead_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    campaign_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    workflow_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    conversation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    inbound_message_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    assigned_agent_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    assigned_agent_crm_id: Mapped[str | None] = mapped_column(String(255))
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    latest_inbound_text: Mapped[str | None] = mapped_column(Text)
    preferences: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
