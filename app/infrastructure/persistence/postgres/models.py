from datetime import datetime, time
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.campaigns.paused_search_tracks import (
    DEFAULT_PAUSED_SEARCH_EMAIL_WRITING_PURPOSE,
    DEFAULT_PAUSED_SEARCH_SMS_WRITING_PURPOSE,
)
from app.domain.lead_assignment import AssignmentResolutionStatus
from app.domain.outbound_drafting import (
    DEFAULT_EMAIL_PROMPT_TEXT,
    DEFAULT_EMAIL_SUBJECT_TEMPLATE,
    DEFAULT_EMAIL_TEMPLATE,
    DEFAULT_PROMPT_TEXT,
    DEFAULT_SMS_PROMPT_TEXT,
    DEFAULT_SMS_TEMPLATE,
    SUPPORTED_QUERY_EXTRACTION_FIELDS,
)
from app.infrastructure.persistence.postgres.partial_index_predicates import (
    ACTIVE_PAUSED_SEARCH_ASSIGNMENT_INDEX_WHERE_SQL,
    PENDING_RUNNING_STATUS_INDEX_WHERE_SQL,
)


class Base(DeclarativeBase):
    pass


class TemplateVersionModel(Base):
    __tablename__ = "template_versions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "template_key",
            "version",
            name="uq_template_versions_workspace_key_version",
        ),
        UniqueConstraint(
            "workspace_id",
            "template_version_id",
            name="uq_template_versions_workspace_id_version_id",
        ),
        Index("ix_template_versions_workspace_channel", "workspace_id", "channel"),
        Index("ix_template_versions_workspace_status", "workspace_id", "status"),
    )

    template_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    template_key: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text)
    prompt_text: Mapped[str | None] = mapped_column(Text)
    allowed_variables: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    permitted_use_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PausedSearchNotificationPolicyModel(Base):
    __tablename__ = "paused_search_notification_policies"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "version", name="uq_paused_search_notification_policy_workspace_version"
        ),
        Index(
            "ix_paused_search_notification_policies_workspace_created",
            "workspace_id",
            "created_at",
        ),
    )

    notification_policy_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled_events: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    recipient_roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    manager_escalation_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    repeated_failure_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    digest_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    digest_cadence_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PausedSearchReviewModel(Base):
    __tablename__ = "paused_search_reviews"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "occurrence_id",
            "kind",
            name="uq_paused_search_reviews_workspace_occurrence_kind",
        ),
        Index(
            "ix_paused_search_reviews_workspace_status_requested",
            "workspace_id",
            "status",
            "requested_at",
        ),
        Index("ix_paused_search_reviews_workspace_workflow", "workspace_id", "workflow_id"),
    )

    review_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    lead_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    workflow_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    occurrence_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_expiry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewer_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    action_reason: Mapped[str | None] = mapped_column(String(1000))
    outbound_message_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("outbound_messages.message_id"),
    )
    outbound_message_version: Mapped[int | None] = mapped_column(Integer)


class PausedSearchNotificationModel(Base):
    __tablename__ = "paused_search_notifications"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_paused_search_notifications_workspace_idempotency",
        ),
        Index(
            "ix_paused_search_notifications_workspace_status",
            "workspace_id",
            "status",
        ),
    )

    notification_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event: Mapped[str] = mapped_column(String(100), nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(500), nullable=False)
    recipient_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    recipient_destination: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    policy_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    correlation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(1000))


class LeadModel(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "crm_provider",
            "crm_lead_id",
            name="uq_leads_workspace_crm_identity",
        ),
        Index("ix_leads_workspace_primary_email", "workspace_id", "primary_email"),
        Index("ix_leads_workspace_lead_type", "workspace_id", "lead_type"),
        Index("ix_leads_workspace_primary_phone", "workspace_id", "primary_phone"),
        Index("ix_leads_workspace_paused_search_active", "workspace_id", "paused_search_active"),
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
    assigned_agent_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
    )
    effective_owner_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
    )
    effective_owner_source: Mapped[str | None] = mapped_column(String(100))
    assignment_resolution_status: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default=AssignmentResolutionStatus.UNRESOLVED.value,
    )
    assignment_last_resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    paused_search_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    paused_search_track_key: Mapped[str | None] = mapped_column(String(100))
    paused_search_track_version_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    pause_reason_note: Mapped[str | None] = mapped_column(Text)
    reengagement_not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reengagement_window_label: Mapped[str | None] = mapped_column(String(100))
    paused_search_source: Mapped[str | None] = mapped_column(String(100))
    paused_search_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_search_recorded_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
    )
    paused_search_last_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LeadPausedSearchHistoryModel(Base):
    __tablename__ = "lead_paused_search_history"
    __table_args__ = (
        Index(
            "ix_lead_paused_search_history_workspace_lead_created",
            "workspace_id",
            "lead_id",
            "created_at",
        ),
    )

    history_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("leads.lead_id"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    previous_paused_search_track_key: Mapped[str | None] = mapped_column(String(100))
    previous_paused_search_track_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True)
    )
    previous_reason_note: Mapped[str | None] = mapped_column(Text)
    previous_reengagement_not_before: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    previous_reengagement_window_label: Mapped[str | None] = mapped_column(String(100))
    previous_source: Mapped[str | None] = mapped_column(String(100))
    previous_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    previous_recorded_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
    )
    previous_last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    current_paused_search_track_key: Mapped[str | None] = mapped_column(String(100))
    current_paused_search_track_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True)
    )
    current_reason_note: Mapped[str | None] = mapped_column(Text)
    current_reengagement_not_before: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    current_reengagement_window_label: Mapped[str | None] = mapped_column(String(100))
    current_source: Mapped[str | None] = mapped_column(String(100))
    current_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_recorded_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
    )
    current_last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CustomerTimingModel(Base):
    __tablename__ = "customer_timing_candidates"
    __table_args__ = (
        Index("ix_customer_timing_workspace_lead_created", "workspace_id", "lead_id", "created_at"),
    )

    timing_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leads.lead_id"), nullable=False
    )
    customer_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LeadClassificationArtifactModel(Base):
    __tablename__ = "lead_classification_artifacts"
    __table_args__ = (
        Index(
            "ix_lead_classification_artifacts_workspace_lead_created",
            "workspace_id",
            "lead_id",
            "created_at",
        ),
    )

    artifact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leads.lead_id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(100), nullable=False)
    selected_track_key: Mapped[str | None] = mapped_column(String(255))
    track_selection_status: Mapped[str | None] = mapped_column(String(50))
    track_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("paused_search_track_versions.track_version_id"),
    )
    reengagement_not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reengagement_window_label: Mapped[str | None] = mapped_column(String(100))
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    summary: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(255), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    usage_tokens: Mapped[int | None] = mapped_column(Integer)
    prompt_text: Mapped[str | None] = mapped_column(Text)
    input_context: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    raw_llm_response_text: Mapped[str | None] = mapped_column(Text)
    parsed_llm_response: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    applied_status: Mapped[str] = mapped_column(String(100), nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LeadRoutingReviewModel(Base):
    __tablename__ = "lead_routing_reviews"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "artifact_id",
            name="uq_lead_routing_reviews_workspace_artifact",
        ),
        Index(
            "ix_lead_routing_reviews_workspace_status_created",
            "workspace_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_lead_routing_reviews_workspace_lead_created",
            "workspace_id",
            "lead_id",
            "created_at",
        ),
    )

    review_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leads.lead_id"), nullable=False
    )
    artifact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("lead_classification_artifacts.artifact_id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    resolution: Mapped[str | None] = mapped_column(String(100))
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ListingSourceModel(Base):
    __tablename__ = "listing_sources"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_listing_sources_workspace_name"),
        Index("ix_listing_sources_workspace_enabled", "workspace_id", "enabled"),
    )

    source_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    allowed_url_patterns: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    disallowed_url_patterns: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    crawl_frequency_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=1440)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_auth: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    terms_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terms_reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
    )
    data_use_policy: Mapped[str | None] = mapped_column(String())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ListingSearchScopeModel(Base):
    __tablename__ = "listing_source_search_scopes"
    __table_args__ = (
        Index(
            "ix_listing_source_search_scopes_workspace_source_enabled",
            "workspace_id",
            "source_id",
            "enabled",
        ),
    )

    scope_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    source_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("listing_sources.source_id"),
        nullable=False,
    )
    search_type: Mapped[str] = mapped_column(String(20), nullable=False)
    locations: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    addresses: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    max_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    min_beds: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    limit: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ListingCrawlRunModel(Base):
    __tablename__ = "listing_crawl_runs"
    __table_args__ = (
        Index(
            "uq_listing_crawl_runs_one_active_source",
            "workspace_id",
            "source_id",
            unique=True,
            postgresql_where=text(PENDING_RUNNING_STATUS_INDEX_WHERE_SQL),
        ),
        Index(
            "ix_listing_crawl_runs_workspace_source_started",
            "workspace_id",
            "source_id",
            "started_at",
        ),
        Index(
            "ix_listing_crawl_runs_workspace_status_started",
            "workspace_id",
            "status",
            "started_at",
        ),
    )

    crawl_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    source_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("listing_sources.source_id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parsed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(String())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ListingSnapshotModel(Base):
    __tablename__ = "listing_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "source_id",
            "external_listing_id",
            "source_payload_hash",
            name="uq_listing_snapshots_workspace_source_external_payload",
        ),
        Index(
            "ix_listing_snapshots_workspace_source_external_current",
            "workspace_id",
            "source_id",
            "external_listing_id",
            "is_current",
        ),
        Index(
            "ix_listing_snapshots_workspace_source_status_current",
            "workspace_id",
            "source_id",
            "status",
            "is_current",
        ),
        Index(
            "ix_listing_snapshots_workspace_source_scraped",
            "workspace_id",
            "source_id",
            "scraped_at",
        ),
    )

    snapshot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    source_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("listing_sources.source_id"),
        nullable=False,
    )
    crawl_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("listing_crawl_runs.crawl_run_id"),
    )
    external_listing_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    address_text: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str | None] = mapped_column(String(255))
    postal_code: Mapped[str | None] = mapped_column(String(50))
    neighborhood: Mapped[str | None] = mapped_column(String(255))
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    beds: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    baths: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    property_type: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String())
    image_urls: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    listed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    source_payload: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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
        UniqueConstraint(
            "workspace_id",
            "reply_routing_token",
            name="uq_outbound_messages_workspace_reply_routing_token",
        ),
        Index("ix_outbound_messages_workspace_lead", "workspace_id", "lead_id"),
        Index("ix_outbound_messages_provider_message", "provider_name", "provider_message_id"),
        Index("ix_outbound_messages_workspace_reply_token", "workspace_id", "reply_routing_token"),
        Index("ix_outbound_messages_workspace_status", "workspace_id", "status"),
    )

    message_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    lead_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    workflow_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
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
    provider_name: Mapped[str | None] = mapped_column(String(50))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    reply_routing_token: Mapped[str | None] = mapped_column(String(64))
    provider_delivery_status: Mapped[str | None] = mapped_column(String(50))
    provider_status_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    status_detail: Mapped[str | None] = mapped_column(String(500))
    provider_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_last_failure_kind: Mapped[str | None] = mapped_column(String(50))
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


class OutboundSendReconciliationModel(Base):
    __tablename__ = "outbound_send_reconciliations"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_outbound_reconciliations_workspace_idempotency",
        ),
        UniqueConstraint(
            "workspace_id",
            "outbound_message_id",
            name="uq_outbound_reconciliations_workspace_message",
        ),
        Index(
            "ix_outbound_reconciliations_workspace_status",
            "workspace_id",
            "status",
        ),
    )

    reconciliation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    workflow_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    temporal_workflow_id: Mapped[str] = mapped_column(String(255), nullable=False)
    outbound_message_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("outbound_messages.message_id"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    provider_delivery_status: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(500))


class OutboundSendRequestModel(Base):
    __tablename__ = "outbound_send_requests"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_outbound_send_requests_workspace_idempotency",
        ),
        UniqueConstraint(
            "workspace_id",
            "outbound_message_id",
            name="uq_outbound_send_requests_workspace_message",
        ),
        Index(
            "ix_outbound_send_requests_status_available_created",
            "status",
            "available_at",
            "created_at",
        ),
        Index(
            "ix_outbound_send_requests_workspace_status_created",
            "workspace_id",
            "status",
            "created_at",
        ),
    )

    request_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    workflow_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    temporal_workflow_id: Mapped[str] = mapped_column(String(255), nullable=False)
    outbound_message_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("outbound_messages.message_id"), nullable=False
    )
    reconciliation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("outbound_send_reconciliations.reconciliation_id"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(500), nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    failure_kind: Mapped[str | None] = mapped_column(String(50))
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OutboundProviderFailureModel(Base):
    __tablename__ = "outbound_provider_failures"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "outbound_message_id",
            name="uq_outbound_provider_failures_workspace_message",
        ),
        Index(
            "ix_outbound_provider_failures_workspace_status_created",
            "workspace_id",
            "status",
            "created_at",
        ),
    )

    failure_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    outbound_message_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("outbound_messages.message_id"),
        nullable=False,
    )
    workflow_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(50), nullable=False)
    failure_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    failure_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    first_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CampaignModel(Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_campaigns_workspace_name"),
        Index("ix_campaigns_workspace_status", "workspace_id", "status"),
    )

    campaign_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    active_version_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    created_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CampaignVersionModel(Base):
    __tablename__ = "campaign_versions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "campaign_id",
            "version_number",
            name="uq_campaign_versions_workspace_campaign_version",
        ),
        Index(
            "ix_campaign_versions_workspace_campaign_status",
            "workspace_id",
            "campaign_id",
            "status",
        ),
    )

    campaign_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("campaigns.campaign_id"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled_channels: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    daily_start_cap: Mapped[int] = mapped_column(Integer, nullable=False)
    dormant_threshold_days: Mapped[int] = mapped_column(Integer, nullable=False)
    quiet_hours_start: Mapped[time] = mapped_column(Time(), nullable=False)
    quiet_hours_end: Mapped[time] = mapped_column(Time(), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    preflight_digest_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    crm_enrollment_tag: Mapped[str | None] = mapped_column(String(255))
    allow_assigned_agent_manual_enrollment: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    approved_model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False, default=DEFAULT_PROMPT_TEXT)
    sms_prompt_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=DEFAULT_SMS_PROMPT_TEXT,
    )
    sms_template: Mapped[str] = mapped_column(Text, nullable=False, default=DEFAULT_SMS_TEMPLATE)
    email_prompt_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=DEFAULT_EMAIL_PROMPT_TEXT,
    )
    email_template: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=DEFAULT_EMAIL_TEMPLATE,
    )
    email_subject_template: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=DEFAULT_EMAIL_SUBJECT_TEMPLATE,
    )
    enabled_extraction_fields: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: list(SUPPORTED_QUERY_EXTRACTION_FIELDS),
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CampaignCadenceStepModel(Base):
    __tablename__ = "campaign_cadence_steps"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "campaign_version_id",
            "step_order",
            name="uq_cadence_steps_workspace_version_order",
        ),
    )

    cadence_step_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    campaign_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("campaign_versions.campaign_version_id"),
        nullable=False,
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    delay_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    message_goal: Mapped[str] = mapped_column(String(1000), nullable=False)
    template_key: Mapped[str] = mapped_column(String(255), nullable=False)
    template_profile: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CampaignAdminAuditLogModel(Base):
    __tablename__ = "campaign_admin_audit_logs"
    __table_args__ = (
        Index(
            "ix_campaign_admin_audit_workspace_campaign",
            "workspace_id",
            "campaign_id",
            "created_at",
        ),
        Index("ix_campaign_admin_audit_actor_created", "actor_user_id", "created_at"),
        Index("ix_campaign_admin_audit_workspace_action", "workspace_id", "action", "created_at"),
    )

    audit_log_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaigns.campaign_id"), nullable=False
    )
    campaign_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaign_versions.campaign_version_id")
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PausedSearchTrackModel(Base):
    __tablename__ = "paused_search_tracks"
    __table_args__ = (
        UniqueConstraint("workspace_id", "track_key", name="uq_paused_tracks_workspace_key"),
        Index("ix_paused_tracks_workspace_status", "workspace_id", "status"),
    )

    track_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    track_key: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    active_version_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    created_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PausedSearchTrackVersionModel(Base):
    __tablename__ = "paused_search_track_versions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "track_id",
            "version_number",
            name="uq_paused_track_versions_workspace_track_version",
        ),
        Index(
            "ix_paused_track_versions_workspace_track_status",
            "workspace_id",
            "track_id",
            "status",
        ),
    )

    track_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    track_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("paused_search_tracks.track_id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    selection_guidance: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allowed_channels: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    fallback_timing_policy: Mapped[str] = mapped_column(String(100), nullable=False)
    maintenance_interval_days: Mapped[int] = mapped_column(Integer, nullable=False)
    reactivation_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    max_total_touches: Mapped[int] = mapped_column(Integer, nullable=False)
    max_duration_days: Mapped[int] = mapped_column(Integer, nullable=False, default=365)
    default_pause_duration_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
    )
    terminal_behavior: Mapped[str] = mapped_column(
        String(50), nullable=False, default="complete_keep_paused"
    )
    track_mode: Mapped[str] = mapped_column(
        String(50), nullable=False, default="custom_bounded"
    )
    interim_contact_policy: Mapped[str] = mapped_column(
        String(80), nullable=False, default="not_allowed"
    )
    reply_policy: Mapped[str] = mapped_column(String(50), nullable=False, default="end")
    channel_sequence: Mapped[str] = mapped_column(
        String(20), nullable=False, default="sequential"
    )
    max_cycles: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_ai_interactions: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    restart_delay_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    email_writing_purpose: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=DEFAULT_PAUSED_SEARCH_EMAIL_WRITING_PURPOSE,
    )
    sms_writing_purpose: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=DEFAULT_PAUSED_SEARCH_SMS_WRITING_PURPOSE,
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PausedSearchTrackStepModel(Base):
    __tablename__ = "paused_search_track_steps"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "track_version_id",
            "step_order",
            name="uq_paused_track_steps_workspace_version_order",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "template_version_id"],
            ["template_versions.workspace_id", "template_versions.template_version_id"],
            name="fk_paused_track_steps_template_workspace",
        ),
    )

    step_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    template_profile: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    track_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("paused_search_track_versions.track_version_id"),
        nullable=False,
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(50), nullable=False)
    timing_basis: Mapped[str] = mapped_column(
        String(50), nullable=False, default="customer_reengagement_date"
    )
    fallback_channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    delay_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    message_goal: Mapped[str] = mapped_column(String(1000), nullable=False)
    template_key: Mapped[str] = mapped_column(String(255), nullable=False)
    template_version_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False, default="send")
    interval_days: Mapped[int | None] = mapped_column(Integer)
    max_occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecurringOccurrenceModel(Base):
    __tablename__ = "paused_search_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "workflow_id",
            "track_version_id",
            "step_id",
            "occurrence_number",
            "scheduled_for",
            name="uq_paused_occurrences_workspace_identity",
        ),
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_paused_occurrences_workspace_idempotency",
        ),
        Index(
            "ix_paused_occurrences_workspace_workflow_status",
            "workspace_id",
            "workflow_id",
            "status",
        ),
        Index(
            "ix_paused_occurrences_workspace_due",
            "workspace_id",
            "status",
            "scheduled_for",
        ),
    )

    occurrence_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leads.lead_id"), nullable=False
    )
    workflow_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("lead_workflows.workflow_id"), nullable=False
    )
    track_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("paused_search_track_versions.track_version_id"),
        nullable=False,
    )
    step_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("paused_search_track_steps.step_id"), nullable=False
    )
    phase: Mapped[str] = mapped_column(String(50), nullable=False)
    occurrence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(500), nullable=False)
    logical_touch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    provider_delivery_status: Mapped[str | None] = mapped_column(String(50))
    correlation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone_snapshot: Mapped[str | None] = mapped_column(String(100))


class PausedSearchAgentReminderModel(Base):
    __tablename__ = "paused_search_agent_reminders"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_paused_search_agent_reminders_workspace_idempotency",
        ),
        Index(
            "ix_paused_search_agent_reminders_workspace_status_due",
            "workspace_id",
            "status",
            "due_at",
        ),
    )

    reminder_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leads.lead_id"), nullable=False
    )
    workflow_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("lead_workflows.workflow_id"), nullable=False
    )
    occurrence_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("paused_search_occurrences.occurrence_id"), nullable=False
    )
    assigned_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PausedSearchTrackAssignmentModel(Base):
    __tablename__ = "paused_search_track_assignments"
    __table_args__ = (
        Index(
            "uq_paused_search_track_assignments_active_lead",
            "workspace_id",
            "lead_id",
            unique=True,
            postgresql_where=text(ACTIVE_PAUSED_SEARCH_ASSIGNMENT_INDEX_WHERE_SQL),
        ),
        Index(
            "ix_paused_search_track_assignments_active_track",
            "workspace_id",
            "track_id",
            postgresql_where=text(ACTIVE_PAUSED_SEARCH_ASSIGNMENT_INDEX_WHERE_SQL),
        ),
    )

    assignment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leads.lead_id", ondelete="CASCADE"), nullable=False
    )
    track_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("paused_search_tracks.track_id", ondelete="SET NULL"),
    )
    track_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("paused_search_track_versions.track_version_id", ondelete="SET NULL"),
    )
    track_key_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    track_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    track_version_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    assigned_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL")
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL")
    )
    release_reason: Mapped[str | None] = mapped_column(Text)


class PausedSearchTrackAdminAuditLogModel(Base):
    __tablename__ = "paused_search_track_admin_audit_logs"
    __table_args__ = (
        Index("ix_paused_track_audit_workspace_track", "workspace_id", "track_id", "created_at"),
        Index("ix_paused_track_audit_workspace_action", "workspace_id", "action", "created_at"),
    )

    audit_log_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    track_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("paused_search_tracks.track_id", ondelete="SET NULL"),
        nullable=True,
    )
    track_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("paused_search_track_versions.track_version_id", ondelete="SET NULL"),
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LeadWorkflowOverrideAuditLogModel(Base):
    __tablename__ = "lead_workflow_override_audit_logs"
    __table_args__ = (
        Index(
            "ix_lead_workflow_override_audit_workspace_lead",
            "workspace_id",
            "lead_id",
            "created_at",
        ),
        Index(
            "ix_lead_workflow_override_audit_workspace_action",
            "workspace_id",
            "action",
            "created_at",
        ),
    )

    audit_log_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leads.lead_id"), nullable=False
    )
    workflow_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("lead_workflows.workflow_id"), nullable=False
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
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
        Index(
            "ix_crm_sync_jobs_workspace_status_created",
            "workspace_id",
            "status",
            "created_at",
        ),
        Index(
            "uq_crm_sync_jobs_one_active_workspace_provider",
            "workspace_id",
            "crm_provider",
            unique=True,
            postgresql_where=text(PENDING_RUNNING_STATUS_INDEX_WHERE_SQL),
        ),
    )

    sync_job_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
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
    failure_reason: Mapped[str | None] = mapped_column(String(255))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CRMSyncWindowStateModel(Base):
    __tablename__ = "crm_sync_window_states"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "crm_provider",
            name="uq_crm_sync_window_states_workspace_provider",
        ),
        Index(
            "ix_crm_sync_window_states_workspace_provider_updated",
            "workspace_id",
            "crm_provider",
            "updated_at",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        primary_key=True,
    )
    crm_provider: Mapped[str] = mapped_column(String(50), primary_key=True)
    sync_type: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_cursor: Mapped[str] = mapped_column(Text, nullable=False)
    sort_by: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CRMAgentModel(Base):
    __tablename__ = "crm_agents"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "crm_provider",
            "crm_agent_id",
            name="uq_crm_agents_workspace_provider_agent",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_crm_agents_workspace_id"),
        Index("ix_crm_agents_workspace_active", "workspace_id", "is_active"),
        Index("ix_crm_agents_workspace_email", "workspace_id", "email_normalized"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    crm_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    crm_agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    email_normalized: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceAgentCRMMappingModel(Base):
    __tablename__ = "workspace_agent_crm_mappings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "crm_agent_id"],
            ["crm_agents.workspace_id", "crm_agents.id"],
        ),
        UniqueConstraint(
            "workspace_id",
            "crm_agent_id",
            name="uq_workspace_agent_crm_mappings_workspace_crm_agent",
        ),
        Index("ix_workspace_agent_crm_mappings_workspace_status", "workspace_id", "mapping_status"),
    )

    mapping_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    crm_agent_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    app_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id")
    )
    mapping_status: Mapped[str] = mapped_column(String(50), nullable=False)
    resolution_source: Mapped[str] = mapped_column(String(100), nullable=False)
    resolved_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    )

    external_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    crm_lead_id: Mapped[str | None] = mapped_column(String(255))
    lead_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("leads.lead_id"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_redacted: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    failure_reason: Mapped[str | None] = mapped_column(String(255))
    failure_kind: Mapped[str | None] = mapped_column(String(50))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderMessageEventModel(Base):
    __tablename__ = "provider_message_events"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            "external_provider_event_id",
            name="uq_provider_message_events_workspace_provider_event",
        ),
        Index(
            "ix_provider_message_events_provider_external", "provider", "external_provider_event_id"
        ),
        Index(
            "ix_provider_message_events_workspace_message", "workspace_id", "provider_message_id"
        ),
        Index(
            "ix_provider_message_events_workspace_status_received",
            "workspace_id",
            "status",
            "received_at",
        ),
    )

    provider_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    outbound_message_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("outbound_messages.message_id"),
    )
    external_provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_redacted: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OutboxEventModel(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_events_status_available", "status", "available_at"),
        Index(
            "ix_outbox_events_workspace_type_created",
            "workspace_id",
            "event_type",
            "created_at",
        ),
    )

    outbox_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000))


class TemporalSignalOutboxModel(Base):
    __tablename__ = "temporal_signal_outbox"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_temporal_signal_outbox_workspace_idempotency",
        ),
        Index("ix_temporal_signal_outbox_status_available", "status", "available_at"),
        Index(
            "ix_temporal_signal_outbox_workspace_status_created",
            "workspace_id",
            "status",
            "created_at",
        ),
    )

    temporal_signal_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    workflow_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("lead_workflows.workflow_id"),
        nullable=False,
    )
    temporal_workflow_id: Mapped[str] = mapped_column(String(255), nullable=False)
    signal_name: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PreflightDigestModel(Base):
    __tablename__ = "preflight_digests"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "campaign_id",
            "batch_id",
            name="uq_preflight_digests_workspace_campaign_batch",
        ),
        Index("ix_preflight_digests_workspace_status", "workspace_id", "status"),
    )

    digest_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaigns.campaign_id"), nullable=False
    )
    batch_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    veto_window_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entries: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False, default=list)
    notification_records: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PreflightVetoModel(Base):
    __tablename__ = "preflight_vetoes"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "campaign_id",
            "batch_id",
            "lead_id",
            "actor_user_id",
            name="uq_preflight_vetoes_workspace_campaign_batch_lead_actor",
        ),
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_preflight_vetoes_workspace_idempotency"
        ),
        Index("ix_preflight_vetoes_workspace_lead", "workspace_id", "lead_id"),
        Index("ix_preflight_vetoes_digest_id", "digest_id"),
    )

    veto_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaigns.campaign_id"), nullable=False
    )
    batch_id: Mapped[str] = mapped_column(String(255), nullable=False)
    digest_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("preflight_digests.digest_id")
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leads.lead_id"), nullable=False
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConversationModel(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_workspace_lead_updated", "workspace_id", "lead_id", "updated_at"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("leads.lead_id"),
        nullable=False,
    )
    campaign_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaigns.campaign_id")
    )
    workflow_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("lead_workflows.workflow_id")
    )
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
    )

    inbound_message_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.conversation_id"),
        nullable=False,
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("leads.lead_id"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_event_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("external_events.external_event_id")
    )
    from_address_redacted: Mapped[str] = mapped_column(String(255), nullable=False)
    to_address_redacted: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    classification_status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CrmConversationEventModel(Base):
    __tablename__ = "crm_conversation_events"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "crm_provider",
            "crm_activity_id",
            name="uq_crm_conversation_events_workspace_provider_activity",
        ),
        UniqueConstraint(
            "workspace_id",
            "crm_provider",
            "lead_id",
            "canonical_identity",
            name="uq_crm_conversation_events_workspace_provider_lead_identity",
        ),
        Index(
            "ix_crm_conversation_events_workspace_lead_occurred",
            "workspace_id",
            "lead_id",
            "occurred_at",
        ),
    )

    crm_conversation_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("leads.lead_id"),
        nullable=False,
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.conversation_id")
    )
    crm_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    crm_activity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    direction: Mapped[str | None] = mapped_column(String(50))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content: Mapped[str | None] = mapped_column(String)
    actor_agent_id: Mapped[str | None] = mapped_column(String(255))
    actor_name: Mapped[str | None] = mapped_column(String(255))
    details: Mapped[dict[str, str | int | float | bool | None]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    transcript_segments: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    source_payload_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CrmHistoryImportJobModel(Base):
    __tablename__ = "crm_history_import_jobs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "import_job_id",
            name="uq_crm_history_import_jobs_workspace_job",
        ),
        Index(
            "uq_crm_history_import_jobs_workspace_lead_batch",
            "workspace_id",
            "lead_id",
            "batch_fingerprint",
            unique=True,
            postgresql_where=text(
                "batch_fingerprint IS NOT NULL AND status NOT IN ('failed', 'cancelled')"
            ),
        ),
        ForeignKeyConstraint(
            ["workspace_id", "source_device_id"],
            ["extension_devices.workspace_id", "extension_devices.device_id"],
            name="fk_crm_history_import_jobs_workspace_device",
        ),
        Index(
            "uq_crm_history_import_jobs_one_active_lead",
            "workspace_id",
            "lead_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending', 'receiving', 'ready', 'running')"
            ),
        ),
        Index(
            "ix_crm_history_import_jobs_status_created",
            "status",
            "created_at",
        ),
        Index(
            "ix_crm_history_import_jobs_workspace_lead_created",
            "workspace_id",
            "lead_id",
            "created_at",
        ),
    )

    import_job_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leads.lead_id"), nullable=False
    )
    crm_lead_id: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    batch_fingerprint: Mapped[str | None] = mapped_column(String(64))
    source_device_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    upload_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    promoted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    upload_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CrmHistoryImportEventModel(Base):
    __tablename__ = "crm_history_import_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "import_job_id"],
            [
                "crm_history_import_jobs.workspace_id",
                "crm_history_import_jobs.import_job_id",
            ],
            name="fk_crm_history_import_events_workspace_job",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id",
            "import_job_id",
            "fingerprint",
            name="uq_crm_history_import_events_workspace_job_fingerprint",
        ),
        Index(
            "ix_crm_history_import_events_workspace_job_status",
            "workspace_id",
            "import_job_id",
            "status",
        ),
        Index(
            "ix_crm_history_import_events_workspace_lead_occurred",
            "workspace_id",
            "lead_id",
            "occurred_at",
        ),
    )

    import_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    import_job_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leads.lead_id"), nullable=False
    )
    external_activity_id: Mapped[str | None] = mapped_column(String(255))
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    direction: Mapped[str | None] = mapped_column(String(50))
    content: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_agent_id: Mapped[str | None] = mapped_column(String(255))
    actor_name: Mapped[str | None] = mapped_column(String(255))
    details: Mapped[dict[str, str | int | float | bool | None]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConversationSummaryModel(Base):
    __tablename__ = "conversation_summaries"

    summary_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.conversation_id"),
        nullable=False,
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("leads.lead_id"),
        nullable=False,
    )
    summary_text: Mapped[str] = mapped_column(String, nullable=False)
    preferences: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HandoffModel(Base):
    __tablename__ = "handoffs"

    handoff_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("leads.lead_id"),
        nullable=False,
    )
    campaign_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaigns.campaign_id")
    )
    workflow_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("lead_workflows.workflow_id")
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.conversation_id")
    )
    inbound_message_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("inbound_messages.inbound_message_id")
    )
    assigned_agent_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id")
    )
    assigned_agent_crm_id: Mapped[str | None] = mapped_column(String(255))
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    latest_inbound_text: Mapped[str] = mapped_column(String, nullable=False)
    preferences: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HandoffCompletionModel(Base):
    __tablename__ = "handoff_completions"

    handoff_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("handoffs.handoff_id"), primary_key=True
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    notification_idempotency_key: Mapped[str] = mapped_column(String(500), nullable=False)
    notification_recipient_id: Mapped[str | None] = mapped_column(String(255))
    notification_recipient_destination: Mapped[str | None] = mapped_column(String(320))
    notification_provider_reference: Mapped[str | None] = mapped_column(String(255))
    notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crm_note_written_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crm_tag_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crm_custom_fields_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crm_snapshot_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(500))


class InboundMessageCRMCompletionModel(Base):
    __tablename__ = "inbound_message_crm_completions"
    __table_args__ = (
        Index(
            "ix_inbound_message_crm_completions_workspace_completed",
            "workspace_id",
            "completed_at",
        ),
    )

    inbound_message_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("inbound_messages.inbound_message_id"),
        primary_key=True,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    crm_note_idempotency_key: Mapped[str] = mapped_column(String(500), nullable=False)
    crm_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crm_lead_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crm_latest_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crm_updates_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    crm_note_written_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crm_review_tag_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crm_snapshot_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(500))


class OutboundMessageCRMCompletionModel(Base):
    __tablename__ = "outbound_message_crm_completions"
    __table_args__ = (
        Index(
            "ix_outbound_message_crm_completions_workspace_completed",
            "workspace_id",
            "completed_at",
        ),
    )

    outbound_message_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("outbound_messages.message_id"),
        primary_key=True,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        nullable=False,
    )
    crm_note_idempotency_key: Mapped[str] = mapped_column(String(500), nullable=False)
    crm_note_written_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crm_conversation_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crm_snapshot_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(500))


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


class WorkspaceContactPolicyModel(Base):
    __tablename__ = "workspace_contact_policies"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), primary_key=True
    )
    quiet_hours_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quiet_hours_start: Mapped[time] = mapped_column(Time, nullable=False)
    quiet_hours_end: Mapped[time] = mapped_column(Time, nullable=False)
    inbound_email_address: Mapped[str | None] = mapped_column(
        String(320),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceHandoffConfigModel(Base):
    __tablename__ = "workspace_handoff_configs"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), primary_key=True
    )
    fallback_recipient_email: Mapped[str | None] = mapped_column(String(320))
    crm_handoff_tag: Mapped[str | None] = mapped_column(String(255))
    crm_review_tag: Mapped[str | None] = mapped_column(String(255))
    crm_custom_fields: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    lead_acknowledgment_sms_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    lead_acknowledgment_sms_body: Mapped[str | None] = mapped_column(String(4000))
    lead_acknowledgment_email_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    lead_acknowledgment_email_subject: Mapped[str | None] = mapped_column(String(255))
    lead_acknowledgment_email_body: Mapped[str | None] = mapped_column(String(4000))
    lead_acknowledgment_prompt_text: Mapped[str | None] = mapped_column(String(12000))
    crm_snapshot_summary_field: Mapped[str | None] = mapped_column(String(255))
    crm_snapshot_status_field: Mapped[str | None] = mapped_column(String(255))
    crm_snapshot_latest_inbound_field: Mapped[str | None] = mapped_column(String(255))
    crm_snapshot_latest_outbound_field: Mapped[str | None] = mapped_column(String(255))
    crm_snapshot_last_activity_at_field: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceCRMSyncConfigModel(Base):
    __tablename__ = "workspace_crm_sync_configs"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), primary_key=True
    )
    crm_sync_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    crm_sync_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_leads_per_sync_cycle: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceAgentMappingConfigModel(Base):
    __tablename__ = "workspace_agent_mapping_configs"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), primary_key=True
    )
    unmapped_assignment_fallback_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceLLMConfigModel(Base):
    __tablename__ = "workspace_llm_configs"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), primary_key=True
    )
    openrouter_model: Mapped[str] = mapped_column(String(255), nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    openrouter_drafting_model: Mapped[str] = mapped_column(String(255), nullable=False)
    openrouter_classification_model: Mapped[str] = mapped_column(String(255), nullable=False)
    bedrock_drafting_model: Mapped[str] = mapped_column(String(255), nullable=False)
    bedrock_classification_model: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceOutboundDraftingConfigModel(Base):
    __tablename__ = "workspace_outbound_drafting_configs"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sms_template: Mapped[str] = mapped_column(Text, nullable=False)
    email_template: Mapped[str] = mapped_column(Text, nullable=False)
    email_subject_template: Mapped[str] = mapped_column(Text, nullable=False)
    sms_prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    email_prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    enabled_extraction_fields: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceOperationalControlModel(Base):
    __tablename__ = "workspace_operational_controls"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), primary_key=True
    )
    automation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    recurring_paused_search_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AttentionAcknowledgementModel(Base):
    __tablename__ = "attention_acknowledgements"
    __table_args__ = (
        Index(
            "ix_attention_acknowledgements_workspace_user_acknowledged",
            "workspace_id",
            "user_id",
            "acknowledged_at",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        primary_key=True,
    )
    attention_item_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    attention_item_version: Mapped[str] = mapped_column(String(500), nullable=False)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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


class ExtensionPairingCodeModel(Base):
    __tablename__ = "extension_pairing_codes"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "pairing_code_id",
            name="uq_extension_pairing_codes_workspace_code",
        ),
        UniqueConstraint(
            "workspace_id",
            "token_hash",
            name="uq_extension_pairing_codes_workspace_token",
        ),
        Index(
            "ix_extension_pairing_codes_workspace_user_created",
            "workspace_id",
            "user_id",
            "created_at",
        ),
    )

    pairing_code_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExtensionDeviceModel(Base):
    __tablename__ = "extension_devices"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "device_id", name="uq_extension_devices_workspace_device"
        ),
        UniqueConstraint(
            "workspace_id",
            "credential_hash",
            name="uq_extension_devices_workspace_credential",
        ),
        Index(
            "ix_extension_devices_workspace_user_revoked",
            "workspace_id",
            "user_id",
            "revoked_at",
        ),
    )

    device_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    device_name: Mapped[str] = mapped_column(String(100), nullable=False)
    extension_version: Mapped[str | None] = mapped_column(String(32))
    credential_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id")
    )
    revocation_reason: Mapped[str | None] = mapped_column(String(500))
