from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, UniqueConstraint
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
