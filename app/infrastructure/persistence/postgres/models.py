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

from app.domain.lead_assignment import AssignmentResolutionStatus


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
        Index("ix_leads_workspace_primary_email", "workspace_id", "primary_email"),
        Index("ix_leads_workspace_lead_type", "workspace_id", "lead_type"),
        Index("ix_leads_workspace_primary_phone", "workspace_id", "primary_phone"),
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
            postgresql_where=text("status IN ('pending', 'running')"),
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
        Index("ix_outbound_messages_workspace_lead", "workspace_id", "lead_id"),
        Index("ix_outbound_messages_provider_message", "provider_name", "provider_message_id"),
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
    provider_name: Mapped[str | None] = mapped_column(String(50))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    provider_delivery_status: Mapped[str | None] = mapped_column(String(50))
    provider_status_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    sms_compliance_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    preflight_digest_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    crm_enrollment_tag: Mapped[str | None] = mapped_column(String(255))
    allow_assigned_agent_manual_enrollment: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    approved_model: Mapped[str] = mapped_column(String(100), nullable=False)
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
    message_goal: Mapped[str] = mapped_column(String(500), nullable=False)
    template_key: Mapped[str] = mapped_column(String(255), nullable=False)
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


class CRMSyncJobModel(Base):
    __tablename__ = "crm_sync_jobs"
    __table_args__ = (Index("ix_crm_sync_jobs_workspace_created", "workspace_id", "created_at"),)

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
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
    )
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

    mapping_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
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
    activity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    direction: Mapped[str | None] = mapped_column(String(50))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content: Mapped[str | None] = mapped_column(String)
    actor_agent_id: Mapped[str | None] = mapped_column(String(255))
    actor_name: Mapped[str | None] = mapped_column(String(255))
    source_payload_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
    sms_compliance_state: Mapped[str] = mapped_column(String(50), nullable=False)
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
