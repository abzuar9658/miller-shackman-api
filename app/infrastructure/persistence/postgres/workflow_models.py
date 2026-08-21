from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.postgres.models import Base


class CampaignEnrollmentModel(Base):
    __tablename__ = "campaign_enrollments"
    __table_args__ = (
        Index(
            "ix_campaign_enrollments_workspace_status_created",
            "workspace_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_campaign_enrollments_workspace_lead_created",
            "workspace_id",
            "lead_id",
            "created_at",
        ),
        Index(
            "uq_campaign_enrollments_active_lead_campaign",
            "workspace_id",
            "campaign_id",
            "lead_id",
            unique=True,
            postgresql_where=text(
                "status IN ('candidate', 'queued', 'active', 'paused', 'handoff')"
            ),
        ),
    )

    campaign_enrollment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaigns.campaign_id"), nullable=False
    )
    campaign_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaign_versions.campaign_version_id"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leads.lead_id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    eligible_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id")
    )
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
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
        Index(
            "ix_lead_workflows_workspace_state_next",
            "workspace_id",
            "state",
            "next_action_at",
        ),
        Index(
            "ix_lead_workflows_workspace_lead_transition",
            "workspace_id",
            "lead_id",
            "last_transition_at",
        ),
        Index(
            "uq_lead_workflows_active_paused_search_lead",
            "workspace_id",
            "lead_id",
            unique=True,
            postgresql_where=text(
                "paused_search_track_version_id IS NOT NULL "
                "AND state IN "
                "('queued', 'active_nurture', 'waiting_for_response', 'response_processing')"
            ),
        ),
        Index(
            "uq_lead_workflows_non_terminal_lead",
            "workspace_id",
            "lead_id",
            unique=True,
            postgresql_where=text("state NOT IN ('completed', 'suppressed', 'closed')"),
        ),
    )

    workflow_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    temporal_workflow_id: Mapped[str] = mapped_column(String(255), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    campaign_enrollment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("campaign_enrollments.campaign_enrollment_id"),
        nullable=False,
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaigns.campaign_id"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leads.lead_id"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    current_step_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaign_cadence_steps.cadence_step_id")
    )
    paused_search_track_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("paused_search_track_versions.track_version_id"),
    )
    paused_search_track_step_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("paused_search_track_steps.step_id"),
    )
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_transition_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pause_reason: Mapped[str | None] = mapped_column(String(255))
    resume_reason: Mapped[str | None] = mapped_column(String(500))
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    logical_touch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_interaction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False
    )
    workflow_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("lead_workflows.workflow_id"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leads.lead_id"), nullable=False
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaigns.campaign_id"), nullable=False
    )
    from_state: Mapped[str | None] = mapped_column(String(50))
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id")
    )
    external_event_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("external_events.external_event_id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )


class RejectedDraftReviewModel(Base):
    __tablename__ = "rejected_draft_reviews"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "workflow_transition_id",
            name="uq_rejected_draft_reviews_workspace_transition",
        ),
        Index(
            "ix_rejected_draft_reviews_workspace_lead_created",
            "workspace_id",
            "lead_id",
            "created_at",
        ),
        Index(
            "ix_rejected_draft_reviews_workspace_status_created",
            "workspace_id",
            "status",
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
    workflow_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("lead_workflows.workflow_id"), nullable=False
    )
    workflow_transition_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workflow_transitions.transition_id"), nullable=False
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaigns.campaign_id"), nullable=False
    )
    campaign_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaign_versions.campaign_version_id"), nullable=False
    )
    cadence_step_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaign_cadence_steps.cadence_step_id"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    draft_reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    review_blockers: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    draft_safety_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    draft_personalization_notes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    draft_body: Mapped[str | None] = mapped_column(String())
    draft_subject: Mapped[str | None] = mapped_column(String(255))
    raw_llm_response_text: Mapped[str | None] = mapped_column(String())
    validation_error: Mapped[str | None] = mapped_column(String())
    explanation: Mapped[str | None] = mapped_column(String())
    draft_confidence: Mapped[float | None] = mapped_column(Float)
    draft_model: Mapped[str | None] = mapped_column(String(100))
    draft_prompt_version: Mapped[str | None] = mapped_column(String(100))
    draft_latency_ms: Mapped[int | None] = mapped_column(Integer)
    draft_usage_tokens: Mapped[int | None] = mapped_column(Integer)
    message_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    can_approve_send: Mapped[bool] = mapped_column(nullable=False, default=False)
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(String())
    outbound_message_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("outbound_messages.message_id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
