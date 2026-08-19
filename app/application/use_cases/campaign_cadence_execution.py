from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4

from app.application.ports.crm import CRMClient
from app.application.ports.crm_sync import CanonicalLeadRefreshSource
from app.application.ports.lead_activity import LeadActivityRepository
from app.application.ports.listing_search import ListingSearchClient
from app.application.ports.listing_sources import ListingSnapshotRepository, ListingSourceRepository
from app.application.ports.llm import LLMClient
from app.application.ports.messaging import (
    EmailProvider,
    SMSProvider,
)
from app.application.ports.rejected_draft_review import RejectedDraftReviewRepository
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    CampaignExecutionRepository,
    CRMAgentRepository,
    CrmConversationEventRepository,
    InboundMessageRepository,
    LeadRepository,
    LeadWorkflowRepository,
    OutboundMessageCRMCompletionRepository,
    OutboundMessageRepository,
    OutboundProviderFailureRepository,
    OutboundSendReconciliationRepository,
    OutboundSendRequestRepository,
    PausedSearchAgentReminderRepository,
    PausedSearchOccurrenceRepository,
    PausedSearchReviewRepository,
    PausedSearchTrackRepository,
    TemplateRepository,
    TemporalSignalOutboxRepository,
    UserRepository,
    WorkflowTransitionRepository,
    WorkspaceAgentCRMMappingRepository,
    WorkspaceAgentMappingConfigRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceMembershipRepository,
    WorkspaceOperationalControlRepository,
    WorkspaceOutboundDraftingConfigRepository,
    WorkspaceRepository,
)
from app.application.services.canonical_lead_inputs import lead_has_destination_for_channel
from app.application.services.pre_send_crm_refresh import PreSendCRMRefreshContext
from app.application.services.pre_send_policy import build_pre_send_policy
from app.application.services.provider_fallback import provider_fallback_allowed
from app.application.services.workspace_automation_control import (
    recurring_paused_search_block_reason,
    recurring_paused_search_is_enabled,
    resolve_workspace_operational_control,
    workspace_automation_block_reason,
    workspace_automation_is_active,
)
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionStatus,
    apply_workflow_state_transition,
)
from app.application.use_cases.complete_outbound_message_crm_sync import (
    complete_outbound_message_crm_sync,
)
from app.application.use_cases.paused_search_message_review import (
    PausedSearchMessageReviewGateStatus,
    gate_paused_search_message_for_review,
)
from app.application.use_cases.plan_next_outbound_message import (
    PlanNextOutboundMessageContext,
    plan_next_outbound_message_for_lead,
)
from app.application.use_cases.plan_outbound_message import (
    ChannelEvaluation,
    PlanOutboundMessageReasonCode,
    PlanOutboundMessageResult,
    PlanOutboundMessageStatus,
)
from app.application.use_cases.schedule_next_paused_search_action import (
    PausedSearchNextActionScheduleResult,
    PausedSearchScheduleStatus,
    schedule_next_paused_search_action,
)
from app.application.use_cases.send_outbound_message import (
    OutboundSendContext,
    SendOutboundMessageResult,
    SendOutboundMessageStatus,
    send_outbound_message,
)
from app.domain.campaigns.execution import CampaignCadenceStep
from app.domain.campaigns.paused_search_occurrences import (
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.paused_search_reminders import (
    PausedSearchAgentReminder,
    PausedSearchReminderStatus,
)
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchStepAction,
    PausedSearchTrackStep,
    effective_paused_search_step_action,
)
from app.domain.campaigns.rejected_draft_review import (
    RejectedDraftReview,
    RejectedDraftReviewStatus,
)
from app.domain.campaigns.template_registry import TemplateVersion
from app.domain.common.ids import CampaignVersionId, LeadId, WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    default_workspace_contact_policy,
)
from app.domain.conversations import CrmConversationEventDirection, WorkspaceHandoffConfig
from app.domain.leads import CanonicalLeadRecord
from app.domain.outbound_drafting import (
    OutboundJourneyChange,
    OutboundJourneyKind,
    WorkspaceOutboundDraftingConfig,
    default_workspace_outbound_drafting_config,
)
from app.domain.workflows import LeadWorkflow, WorkflowState, WorkflowTransitionReasonCode


class CadenceStepScheduleStatus(StrEnum):
    SCHEDULED = "scheduled"
    NO_WORKFLOW = "no_workflow"
    MISSING_CAMPAIGN_CONFIG = "missing_campaign_config"
    NO_CADENCE_STEP = "no_cadence_step"
    TERMINAL = "terminal"
    REVIEW = "review"
    HOLD = "hold"


class CadenceStepExecutionStatus(StrEnum):
    SENT = "sent"
    ALREADY_SENT = "already_sent"
    ALREADY_WAITING_FOR_RESPONSE = "already_waiting_for_response"
    DISPATCH_PENDING = "dispatch_pending"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    SKIPPED = "skipped"
    REVIEW = "review"
    NO_WORKFLOW = "no_workflow"
    MISSING_CAMPAIGN_CONFIG = "missing_campaign_config"
    NO_CADENCE_STEP = "no_cadence_step"
    MISSING_WORKSPACE = "missing_workspace"


@dataclass(frozen=True)
class CadenceStepScheduleResult:
    status: CadenceStepScheduleStatus
    workflow: LeadWorkflow | None = None
    cadence_step_id: UUID | None = None
    scheduled_for: datetime | None = None
    skip_reason: str | None = None
    occurrence_id: UUID | None = None


@dataclass(frozen=True)
class CadenceStepExecutionResult:
    status: CadenceStepExecutionStatus
    workflow: LeadWorkflow | None = None
    transition_id: UUID | None = None
    cadence_step_id: UUID | None = None
    outbound_message_id: UUID | None = None
    provider_message_id: str | None = None
    skip_reason: str | None = None
    has_more_steps: bool = False
    occurrence_id: UUID | None = None
    fallback_used: bool = False
    reconciliation_id: UUID | None = None
    provider_failure_id: UUID | None = None
    request_id: UUID | None = None


async def schedule_next_campaign_cadence_step(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    campaign_version_id: CampaignVersionId,
    campaign_execution_repository: CampaignExecutionRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    lead_repository: LeadRepository | None = None,
    paused_search_track_repository: PausedSearchTrackRepository | None = None,
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository | None = None,
    workflow_transition_repository: WorkflowTransitionRepository | None = None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None = None,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None = None,
    recurring_paused_search_pilot_workspace_ids: Collection[WorkspaceId] | None = None,
    now: datetime,
) -> CadenceStepScheduleResult:
    config = await campaign_execution_repository.get_by_version_id(
        workspace_id, campaign_version_id
    )
    if config is None:
        return CadenceStepScheduleResult(
            status=CadenceStepScheduleStatus.MISSING_CAMPAIGN_CONFIG,
        )

    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(workspace_id, lead_id)
    if workflow is None:
        return CadenceStepScheduleResult(status=CadenceStepScheduleStatus.NO_WORKFLOW)

    if workflow.state in {
        WorkflowState.COMPLETED,
        WorkflowState.SUPPRESSED,
        WorkflowState.CLOSED,
    }:
        return CadenceStepScheduleResult(
            status=CadenceStepScheduleStatus.NO_CADENCE_STEP,
            workflow=workflow,
            skip_reason=f"Workflow is not schedulable from state {workflow.state.value}.",
        )

    if _workflow_has_no_remaining_cadence_steps(workflow):
        if workflow.paused_search_track_version_id is None:
            return CadenceStepScheduleResult(
                status=CadenceStepScheduleStatus.NO_CADENCE_STEP,
                workflow=workflow,
                skip_reason="Workflow has no remaining cadence steps.",
            )
        if paused_search_track_repository is None:
            return CadenceStepScheduleResult(
                status=CadenceStepScheduleStatus.NO_CADENCE_STEP,
                workflow=workflow,
                skip_reason="Paused-search schedule dependencies are unavailable.",
            )
        paused_version = await paused_search_track_repository.get_version(
            workspace_id,
            workflow.paused_search_track_version_id,
        )
        if paused_version is None or (
            workflow.logical_touch_count >= paused_version.max_total_touches
        ):
            return CadenceStepScheduleResult(
                status=CadenceStepScheduleStatus.NO_CADENCE_STEP,
                workflow=workflow,
                skip_reason="Workflow has no remaining cadence steps.",
            )

    lead = None
    if lead_repository is not None:
        lead = await lead_repository.get_by_id(workspace_id, lead_id)

    if workflow.paused_search_track_version_id is not None or (
        lead is not None and lead.paused_search_active
    ):
        if lead_repository is None or paused_search_track_repository is None:
            return CadenceStepScheduleResult(
                status=CadenceStepScheduleStatus.NO_CADENCE_STEP,
                workflow=workflow,
                skip_reason="Paused-search schedule dependencies are unavailable.",
            )
        paused_result = await schedule_next_paused_search_action(
            workspace_id=workspace_id,
            lead_id=lead_id,
            lead_repository=lead_repository,
            paused_search_track_repository=paused_search_track_repository,
            occurrence_repository=paused_search_occurrence_repository,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            workspace_operational_control_repository=workspace_operational_control_repository,
            workspace_contact_policy_repository=workspace_contact_policy_repository,
            campaign_enrollment_repository=campaign_enrollment_repository,
            recurring_paused_search_pilot_workspace_ids=recurring_paused_search_pilot_workspace_ids,
            timezone=config.timezone,
            now=now,
        )
        return _paused_search_schedule_result(paused_result)

    step = _scheduled_or_initial_step(config.cadence_steps, workflow.current_step_id)
    if step is None:
        return CadenceStepScheduleResult(status=CadenceStepScheduleStatus.NO_CADENCE_STEP)

    scheduled_for = workflow.next_action_at
    if workflow.current_step_id != step.cadence_step_id or scheduled_for is None:
        scheduled_for = now + timedelta(hours=step.delay_hours)
        workflow = await lead_workflow_repository.save(
            replace(
                workflow,
                current_step_id=step.cadence_step_id,
                next_action_at=scheduled_for,
                updated_at=now,
            )
        )

    return CadenceStepScheduleResult(
        status=CadenceStepScheduleStatus.SCHEDULED,
        workflow=workflow,
        cadence_step_id=step.cadence_step_id,
        scheduled_for=scheduled_for,
    )


async def execute_campaign_cadence_step(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    campaign_version_id: CampaignVersionId,
    cadence_step_id: UUID,
    scheduled_for: datetime,
    campaign_execution_repository: CampaignExecutionRepository,
    paused_search_track_repository: PausedSearchTrackRepository | None = None,
    template_repository: TemplateRepository | None = None,
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository | None = None,
    paused_search_review_repository: PausedSearchReviewRepository | None = None,
    paused_search_reminder_repository: PausedSearchAgentReminderRepository | None = None,
    workspace_repository: WorkspaceRepository,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None = None,
    workspace_outbound_drafting_config_repository: WorkspaceOutboundDraftingConfigRepository
    | None = None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None,
    lead_repository: LeadRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    message_repository: OutboundMessageRepository,
    inbound_message_repository: InboundMessageRepository | None = None,
    outbound_send_reconciliation_repository: OutboundSendReconciliationRepository | None = None,
    rejected_draft_review_repository: RejectedDraftReviewRepository | None = None,
    lead_activity_repository: LeadActivityRepository | None = None,
    crm_conversation_event_repository: CrmConversationEventRepository | None = None,
    listing_source_repository: ListingSourceRepository | None = None,
    listing_snapshot_repository: ListingSnapshotRepository | None = None,
    listing_search_client: ListingSearchClient | None = None,
    listing_enrichment_enabled: bool = False,
    listing_cache_ttl: timedelta = timedelta(hours=1),
    listing_max_results: int = 3,
    llm_client: LLMClient,
    sms_provider: SMSProvider,
    email_provider: EmailProvider,
    crm_client: CRMClient | None = None,
    crm_agent_repository: CRMAgentRepository | None = None,
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository | None = None,
    workspace_agent_mapping_config_repository: WorkspaceAgentMappingConfigRepository | None = None,
    workspace_membership_repository: WorkspaceMembershipRepository | None = None,
    user_repository: UserRepository | None = None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None = None,
    outbound_message_crm_completion_repository: (
        OutboundMessageCRMCompletionRepository | None
    ) = None,
    outbound_provider_failure_repository: OutboundProviderFailureRepository | None = None,
    outbound_send_request_repository: OutboundSendRequestRepository | None = None,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None = None,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None = None,
    now: datetime,
    default_openrouter_model: str = "openai/gpt-4o-mini",
    workspace_automation_defer_interval: timedelta = timedelta(minutes=15),
    recurring_paused_search_pilot_workspace_ids: Collection[WorkspaceId] | None = None,
    before_provider_dispatch: Callable[[], Awaitable[None]] | None = None,
) -> CadenceStepExecutionResult:
    config = await campaign_execution_repository.get_by_version_id(
        workspace_id, campaign_version_id
    )
    if config is None:
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.MISSING_CAMPAIGN_CONFIG,
        )

    # Keep the transaction lock order aligned with CRM/profile mutation paths:
    # lead first, then workflow, then outbound message and occurrence rows.
    lead = await lead_repository.get_by_id_for_update(workspace_id, lead_id)
    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(workspace_id, lead_id)
    if workflow is None:
        return CadenceStepExecutionResult(status=CadenceStepExecutionStatus.NO_WORKFLOW)

    if (
        lead is not None
        and lead.paused_search_active
        and workflow.paused_search_track_version_id is None
    ):
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.NO_CADENCE_STEP,
            workflow=workflow,
            cadence_step_id=cadence_step_id,
            skip_reason=(
                "Lead is paused-search active but no pinned paused-search track is available."
            ),
        )

    cadence_steps = config.cadence_steps
    cursor_step_id = workflow.current_step_id
    journey_kind = OutboundJourneyKind.DORMANT
    is_paused_search_step = workflow.paused_search_track_version_id is not None
    paused_search_occurrence: RecurringOccurrence | None = None
    paused_search_step: PausedSearchTrackStep | None = None
    paused_search_writing_purpose: str | None = None
    if is_paused_search_step:
        if paused_search_track_repository is None:
            return CadenceStepExecutionResult(
                status=CadenceStepExecutionStatus.NO_CADENCE_STEP,
                workflow=workflow,
                cadence_step_id=cadence_step_id,
                skip_reason="Paused-search track repository is unavailable.",
            )
        (
            workflow,
            paused_search_gate_result,
            paused_search_occurrence,
        ) = await _revalidate_paused_search_execution_gate(
            workspace_id=workspace_id,
            lead_id=lead_id,
            cadence_step_id=cadence_step_id,
            timezone=config.timezone,
            lead_repository=lead_repository,
            lead_workflow_repository=lead_workflow_repository,
            paused_search_track_repository=paused_search_track_repository,
            paused_search_occurrence_repository=paused_search_occurrence_repository,
            workspace_operational_control_repository=workspace_operational_control_repository,
            workspace_contact_policy_repository=workspace_contact_policy_repository,
            campaign_enrollment_repository=campaign_enrollment_repository,
            recurring_paused_search_pilot_workspace_ids=recurring_paused_search_pilot_workspace_ids,
            workflow=workflow,
            now=now,
        )
        if paused_search_gate_result is not None:
            return paused_search_gate_result
        paused_search_track_version_id = workflow.paused_search_track_version_id
        assert paused_search_track_version_id is not None
        paused_search_track_version = await paused_search_track_repository.get_version(
            workspace_id,
            paused_search_track_version_id,
        )
        if paused_search_track_version is None:
            return CadenceStepExecutionResult(
                status=CadenceStepExecutionStatus.NO_CADENCE_STEP,
                workflow=workflow,
                cadence_step_id=cadence_step_id,
                skip_reason="Pinned paused-search track version is unavailable.",
            )
        paused_steps = await paused_search_track_repository.get_steps(
            workspace_id,
            paused_search_track_version_id,
        )
        paused_search_step = next(
            (candidate for candidate in paused_steps if candidate.step_id == cadence_step_id),
            None,
        )
        # Step-level message_goal already contains the phase-specific purpose
        # (e.g., "Maintenance SMS purpose: ..." or "Reactivation email purpose: ..."),
        # so we no longer need to populate paused_search_writing_purpose from the
        # track-level fallback email_writing_purpose/sms_writing_purpose.
        cadence_steps = _paused_search_steps_as_cadence_steps(
            paused_steps,
            campaign_version_id=campaign_version_id,
        )
        cursor_step_id = workflow.paused_search_track_step_id
        journey_kind = OutboundJourneyKind.PAUSED_SEARCH

    step = _step_by_id(cadence_steps, cadence_step_id)
    if step is None:
        return CadenceStepExecutionResult(status=CadenceStepExecutionStatus.NO_CADENCE_STEP)

    template_version: TemplateVersion | None = None
    if is_paused_search_step and template_repository is not None:
        if step.template_version_id is None and step.template_profile is None:
            return CadenceStepExecutionResult(
                status=CadenceStepExecutionStatus.NO_CADENCE_STEP,
                workflow=workflow,
                cadence_step_id=cadence_step_id,
                skip_reason="Paused-search step has no immutable template binding.",
            )
        if step.template_version_id is not None:
            template_version = await template_repository.get_by_id(
                workspace_id,
                step.template_version_id,
            )
        if step.template_version_id is not None and template_version is None:
            return CadenceStepExecutionResult(
                status=CadenceStepExecutionStatus.NO_CADENCE_STEP,
                workflow=workflow,
                cadence_step_id=cadence_step_id,
                skip_reason="Paused-search template binding is unavailable.",
            )

    if cursor_step_id not in {None, step.cadence_step_id}:
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.SKIPPED,
            workflow=workflow,
            cadence_step_id=step.cadence_step_id,
            skip_reason="Workflow cursor does not match the scheduled cadence step.",
        )

    if (
        workflow.state == WorkflowState.WAITING_FOR_RESPONSE
        and cursor_step_id == step.cadence_step_id
        and workflow.next_action_at is None
    ):
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.ALREADY_WAITING_FOR_RESPONSE,
            workflow=workflow,
            cadence_step_id=step.cadence_step_id,
        )

    if workflow.state in {
        WorkflowState.PAUSED,
        WorkflowState.HUMAN_HANDOFF,
        WorkflowState.HUMAN_OWNED,
        WorkflowState.COMPLETED,
        WorkflowState.SUPPRESSED,
        WorkflowState.CLOSED,
    }:
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.SKIPPED,
            workflow=workflow,
            cadence_step_id=step.cadence_step_id,
            skip_reason=f"Workflow is not sendable from state {workflow.state.value}.",
        )

    if is_paused_search_step and paused_search_step is not None:
        step_action = effective_paused_search_step_action(paused_search_step)
        if step_action is PausedSearchStepAction.SKIP:
            if (
                paused_search_occurrence is not None
                and paused_search_occurrence_repository is not None
            ):
                await paused_search_occurrence_repository.update_status(
                    workspace_id=workspace_id,
                    occurrence_id=paused_search_occurrence.occurrence_id,
                    status=RecurringOccurrenceStatus.SKIPPED.value,
                    now=now,
                )
            return CadenceStepExecutionResult(
                status=CadenceStepExecutionStatus.SKIPPED,
                workflow=workflow,
                cadence_step_id=step.cadence_step_id,
                occurrence_id=(
                    paused_search_occurrence.occurrence_id
                    if paused_search_occurrence is not None
                    else None
                ),
                skip_reason="Paused-search step is configured to skip.",
                has_more_steps=True,
            )
        if step_action is PausedSearchStepAction.REMINDER:
            if paused_search_occurrence is None:
                return CadenceStepExecutionResult(
                    status=CadenceStepExecutionStatus.NO_CADENCE_STEP,
                    workflow=workflow,
                    cadence_step_id=step.cadence_step_id,
                    skip_reason="Paused-search reminder requires a planned occurrence.",
                )
            if paused_search_reminder_repository is None:
                return CadenceStepExecutionResult(
                    status=CadenceStepExecutionStatus.REVIEW,
                    workflow=workflow,
                    cadence_step_id=step.cadence_step_id,
                    occurrence_id=paused_search_occurrence.occurrence_id,
                    skip_reason="Paused-search reminder dependencies are unavailable.",
                )
            reminder = await paused_search_reminder_repository.create_or_get(
                PausedSearchAgentReminder(
                    reminder_id=uuid4(),
                    workspace_id=workspace_id,
                    lead_id=lead_id,
                    workflow_id=workflow.workflow_id,
                    occurrence_id=paused_search_occurrence.occurrence_id,
                    assigned_user_id=lead.effective_owner_user_id if lead is not None else None,
                    due_at=paused_search_occurrence.due_at,
                    status=PausedSearchReminderStatus.PENDING,
                    title="Paused-search follow-up reminder",
                    body=paused_search_step.message_goal,
                    idempotency_key=(
                        f"paused-search-reminder:{paused_search_occurrence.occurrence_id}"
                    ),
                    created_at=now,
                )
            )
            if paused_search_occurrence_repository is not None:
                await paused_search_occurrence_repository.update_status(
                    workspace_id=workspace_id,
                    occurrence_id=paused_search_occurrence.occurrence_id,
                    status=RecurringOccurrenceStatus.REMINDER_CREATED.value,
                    now=now,
                )
            return CadenceStepExecutionResult(
                status=CadenceStepExecutionStatus.SKIPPED,
                workflow=workflow,
                cadence_step_id=step.cadence_step_id,
                occurrence_id=reminder.occurrence_id,
                skip_reason="Paused-search agent reminder created instead of sending.",
                has_more_steps=True,
            )

    if lead is not None and not lead_has_destination_for_channel(lead, step.channel):
        return await _handle_missing_step_destination(
            workspace_id=workspace_id,
            lead_id=lead_id,
            workflow=workflow,
            lead=lead,
            cadence_steps=cadence_steps,
            cadence_step=step,
            is_paused_search_step=is_paused_search_step,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            now=now,
        )

    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.MISSING_WORKSPACE,
            workflow=workflow,
            cadence_step_id=step.cadence_step_id,
        )

    operational_control = await resolve_workspace_operational_control(
        workspace_id=workspace_id,
        workspace_operational_control_repository=workspace_operational_control_repository,
    )
    if not workspace_automation_is_active(operational_control):
        deferred_until = now + workspace_automation_defer_interval
        workflow = await _save_step_cursor(
            workflow=workflow,
            cadence_step_id=step.cadence_step_id,
            scheduled_for=deferred_until,
            is_paused_search_step=is_paused_search_step,
            lead_workflow_repository=lead_workflow_repository,
            now=now,
        )
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.DEFERRED,
            workflow=workflow,
            cadence_step_id=step.cadence_step_id,
            skip_reason=workspace_automation_block_reason(operational_control),
            has_more_steps=True,
        )

    if (
        is_paused_search_step
        and workspace_operational_control_repository is not None
        and not recurring_paused_search_is_enabled(
        control=operational_control,
        workspace_id=workspace_id,
        pilot_workspace_ids=recurring_paused_search_pilot_workspace_ids,
        )
    ):
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.REVIEW,
            workflow=workflow,
            cadence_step_id=step.cadence_step_id,
            skip_reason=recurring_paused_search_block_reason(
                control=operational_control,
                workspace_id=workspace_id,
                pilot_workspace_ids=recurring_paused_search_pilot_workspace_ids,
            ),
            has_more_steps=True,
        )

    workspace_contact_policy = await workspace_contact_policy_repository.get_by_workspace_id(
        workspace_id,
    )
    if workspace_contact_policy is None:
        workspace_contact_policy = default_workspace_contact_policy(workspace_id)

    pre_send_policy = build_pre_send_policy(
        workspace_contact_policy,
        workspace.default_timezone,
    )

    drafting_config: WorkspaceOutboundDraftingConfig | None = (
        config.outbound_drafting_config
        if journey_kind == OutboundJourneyKind.DORMANT
        else None
    )
    if journey_kind == OutboundJourneyKind.PAUSED_SEARCH:
        if workspace_outbound_drafting_config_repository is not None:
            drafting_config = (
                await workspace_outbound_drafting_config_repository.get_by_workspace_id(
                    workspace_id
                )
            )
        drafting_config = drafting_config or default_workspace_outbound_drafting_config(
            workspace_id
        )

    if cursor_step_id != step.cadence_step_id or (
        not is_paused_search_step and workflow.next_action_at != scheduled_for
    ):
        workflow = await _save_step_cursor(
            workflow=workflow,
            cadence_step_id=step.cadence_step_id,
            scheduled_for=scheduled_for,
            is_paused_search_step=is_paused_search_step,
            lead_workflow_repository=lead_workflow_repository,
            now=now,
        )

    if workflow.state != WorkflowState.ACTIVE_NURTURE:
        active_outcome = await apply_workflow_state_transition(
            workspace_id=workspace_id,
            lead_id=lead_id,
            to_state=WorkflowState.ACTIVE_NURTURE,
            reason_code=WorkflowTransitionReasonCode.CADENCE_STEP_STARTED,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            now=now,
            metadata={"cadence_step_id": str(step.cadence_step_id)},
        )
        if (
            active_outcome.status != WorkflowStateTransitionStatus.UPDATED
            or active_outcome.workflow is None
        ):
            return CadenceStepExecutionResult(
                status=CadenceStepExecutionStatus.SKIPPED,
                workflow=active_outcome.workflow or workflow,
                cadence_step_id=step.cadence_step_id,
                skip_reason=active_outcome.skip_reason,
            )
        workflow = active_outcome.workflow

    enabled_channels = (step.channel,)

    journey_change = await _journey_change_for_workflow(
        workspace_id=workspace_id,
        lead_id=lead_id,
        workflow=workflow,
        journey_kind=journey_kind,
        lead_workflow_repository=lead_workflow_repository,
    )

    planning_context = PlanNextOutboundMessageContext(
        campaign_status=config.campaign_status,
        workflow_state=WorkflowState.ACTIVE_NURTURE,
        enabled_channels=enabled_channels,
        workspace_contact_policy=workspace_contact_policy,
        campaign_goal=step.message_goal,
        brokerage_name=workspace.name,
        cadence_step_id=str(step.cadence_step_id),
        workflow_id=workflow.workflow_id,
        template_key=step.template_key,
        template_version=template_version,
        scheduled_for=scheduled_for,
        message_version=(
            paused_search_occurrence.occurrence_number
            if paused_search_occurrence is not None
            else 1
        ),
        pre_send_policy=pre_send_policy,
        journey_kind=journey_kind,
        journey_change=journey_change,
        drafting_config=drafting_config,
        template_profile=step.template_profile,
        paused_search_writing_purpose=paused_search_writing_purpose,
    )
    plan_result = await plan_next_outbound_message_for_lead(
        workspace_id=workspace_id,
        lead_id=lead_id,
        campaign_id=config.campaign_id,
        context=planning_context,
        lead_repository=lead_repository,
        message_repository=message_repository,
        lead_activity_repository=lead_activity_repository,
        crm_conversation_event_repository=crm_conversation_event_repository,
        llm_client=llm_client,
        now=now,
        workspace_llm_config_repository=workspace_llm_config_repository,
        workspace_outbound_drafting_config_repository=workspace_outbound_drafting_config_repository,
        default_openrouter_model=default_openrouter_model,
        listing_source_repository=listing_source_repository,
        listing_snapshot_repository=listing_snapshot_repository,
        listing_search_client=listing_search_client,
        listing_enrichment_enabled=listing_enrichment_enabled,
        listing_cache_ttl=listing_cache_ttl,
        listing_max_results=listing_max_results,
    )
    if plan_result.status == PlanOutboundMessageStatus.REJECTED or plan_result.message is None:
        block_metadata = _planning_block_metadata(
            cadence_step_id=step.cadence_step_id,
            plan_result=plan_result,
        )
        blocked_result = await _pause_after_block(
            workspace_id=workspace_id,
            lead_id=lead_id,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            cadence_step_id=step.cadence_step_id,
            now=now,
            reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED,
            skip_reason=str(block_metadata.get("explanation", _reason_values(plan_result.reasons))),
            metadata=block_metadata,
            status=CadenceStepExecutionStatus.REJECTED,
        )
        if (
            rejected_draft_review_repository is not None
            and blocked_result.transition_id is not None
            and workflow is not None
            and _should_persist_rejected_draft_review(plan_result)
        ):
            await rejected_draft_review_repository.save(
                _rejected_draft_review(
                    workspace_id=workspace_id,
                    workflow_id=workflow.workflow_id,
                    transition_id=blocked_result.transition_id,
                    campaign_id=config.campaign_id,
                    campaign_version_id=campaign_version_id,
                    lead_id=lead_id,
                    cadence_step_id=step.cadence_step_id,
                    channel=plan_result.selected_channel or step.channel,
                    plan_result=plan_result,
                    now=now,
                )
            )
        return blocked_result

    if (
        is_paused_search_step
        and paused_search_step is not None
        and effective_paused_search_step_action(paused_search_step)
        is PausedSearchStepAction.REVIEW
        and paused_search_occurrence is not None
    ):
        if (
            paused_search_review_repository is None
            or paused_search_occurrence_repository is None
        ):
            return CadenceStepExecutionResult(
                status=CadenceStepExecutionStatus.REVIEW,
                workflow=workflow,
                cadence_step_id=step.cadence_step_id,
                outbound_message_id=plan_result.message.message_id,
                occurrence_id=paused_search_occurrence.occurrence_id,
                skip_reason="Paused-search message review dependencies are unavailable.",
            )
        review_gate = await gate_paused_search_message_for_review(
            review_required=True,
            occurrence=paused_search_occurrence,
            message=plan_result.message,
            review_repository=paused_search_review_repository,
            occurrence_repository=paused_search_occurrence_repository,
            now=now,
        )
        if review_gate.status is not PausedSearchMessageReviewGateStatus.ALLOWED:
            return CadenceStepExecutionResult(
                status=CadenceStepExecutionStatus.REVIEW,
                workflow=workflow,
                cadence_step_id=step.cadence_step_id,
                outbound_message_id=plan_result.message.message_id,
                occurrence_id=paused_search_occurrence.occurrence_id,
                skip_reason=review_gate.reason or "Message is waiting for operator review.",
                has_more_steps=True,
            )

    send_context = OutboundSendContext(
        campaign_status=config.campaign_status,
        workflow_state=WorkflowState.ACTIVE_NURTURE,
        enabled_channels=(step.channel,),
        workspace_contact_policy=workspace_contact_policy,
        current_message_version=plan_result.message.message_version,
        pre_send_policy=pre_send_policy,
    )
    send_result = await send_outbound_message(
        workspace_id=workspace_id,
        idempotency_key=plan_result.message.idempotency_key,
        context=send_context,
        lead_repository=lead_repository,
        message_repository=message_repository,
        sms_provider=sms_provider,
        email_provider=email_provider,
        inbound_message_repository=inbound_message_repository,
        outbound_send_reconciliation_repository=(
            outbound_send_reconciliation_repository if not is_paused_search_step else None
        ),
        outbound_provider_failure_repository=(
            outbound_provider_failure_repository if not is_paused_search_step else None
        ),
        outbound_send_request_repository=(
            outbound_send_request_repository if not is_paused_search_step else None
        ),
        workflow_id=workflow.workflow_id if not is_paused_search_step else None,
        temporal_workflow_id=workflow.temporal_workflow_id if not is_paused_search_step else None,
        workspace_operational_control_repository=workspace_operational_control_repository,
        crm_refresh_context=_pre_send_crm_refresh_context(
            crm_client=crm_client,
            crm_agent_repository=crm_agent_repository,
            workspace_agent_crm_mapping_repository=workspace_agent_crm_mapping_repository,
            workspace_agent_mapping_config_repository=workspace_agent_mapping_config_repository,
            workspace_membership_repository=workspace_membership_repository,
            user_repository=user_repository,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        ),
        now=now,
        before_provider_dispatch=before_provider_dispatch,
    )
    fallback_used = False
    fallback_channel = (
        paused_search_step.fallback_channel
        if paused_search_step is not None
        and paused_search_step.fallback_channel != step.channel
        else None
    )
    if (
        send_result.status is SendOutboundMessageStatus.FAILED
        and provider_fallback_allowed(
            primary_channel=step.channel,
            fallback_channel=fallback_channel,
            failure_kind=send_result.failure_kind,
        )
    ):
        assert fallback_channel is not None
        fallback_plan = await plan_next_outbound_message_for_lead(
            workspace_id=workspace_id,
            lead_id=lead_id,
            campaign_id=config.campaign_id,
            context=replace(planning_context, enabled_channels=(fallback_channel,)),
            lead_repository=lead_repository,
            message_repository=message_repository,
            lead_activity_repository=lead_activity_repository,
            crm_conversation_event_repository=crm_conversation_event_repository,
            llm_client=llm_client,
            now=now,
            workspace_llm_config_repository=workspace_llm_config_repository,
            workspace_outbound_drafting_config_repository=workspace_outbound_drafting_config_repository,
            default_openrouter_model=default_openrouter_model,
            listing_source_repository=listing_source_repository,
            listing_snapshot_repository=listing_snapshot_repository,
            listing_search_client=listing_search_client,
            listing_enrichment_enabled=listing_enrichment_enabled,
            listing_cache_ttl=listing_cache_ttl,
            listing_max_results=listing_max_results,
        )
        if (
            fallback_plan.message is not None
            and fallback_plan.status is not PlanOutboundMessageStatus.REJECTED
        ):
            send_result = await send_outbound_message(
                workspace_id=workspace_id,
                idempotency_key=fallback_plan.message.idempotency_key,
                context=replace(send_context, enabled_channels=(fallback_channel,)),
                lead_repository=lead_repository,
                message_repository=message_repository,
                inbound_message_repository=inbound_message_repository,
                outbound_send_reconciliation_repository=(
                    outbound_send_reconciliation_repository if not is_paused_search_step else None
                ),
                outbound_send_request_repository=(
                    outbound_send_request_repository if not is_paused_search_step else None
                ),
                outbound_provider_failure_repository=(
                    outbound_provider_failure_repository if not is_paused_search_step else None
                ),
                workflow_id=workflow.workflow_id if not is_paused_search_step else None,
                temporal_workflow_id=(
                    workflow.temporal_workflow_id if not is_paused_search_step else None
                ),
                sms_provider=sms_provider,
                email_provider=email_provider,
                workspace_operational_control_repository=workspace_operational_control_repository,
                crm_refresh_context=_pre_send_crm_refresh_context(
                    crm_client=crm_client,
                    crm_agent_repository=crm_agent_repository,
                    workspace_agent_crm_mapping_repository=workspace_agent_crm_mapping_repository,
                    workspace_agent_mapping_config_repository=workspace_agent_mapping_config_repository,
                    workspace_membership_repository=workspace_membership_repository,
                    user_repository=user_repository,
                    lead_workflow_repository=lead_workflow_repository,
                    workflow_transition_repository=workflow_transition_repository,
                    temporal_signal_outbox_repository=temporal_signal_outbox_repository,
                ),
                now=now,
                before_provider_dispatch=before_provider_dispatch,
            )
            fallback_used = True
    if send_result.status is SendOutboundMessageStatus.DISPATCH_PENDING:
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.DISPATCH_PENDING,
            workflow=workflow,
            cadence_step_id=step.cadence_step_id,
            outbound_message_id=(send_result.message.message_id if send_result.message else None),
            reconciliation_id=send_result.reconciliation_id,
            request_id=send_result.request_id,
            has_more_steps=True,
        )
    if is_paused_search_step and paused_search_occurrence is not None:
        workflow = await _record_paused_search_occurrence_outcome(
            workspace_id=workspace_id,
            workflow=workflow,
            occurrence=paused_search_occurrence,
            authored_channel=step.channel,
            send_result=send_result,
            occurrence_repository=paused_search_occurrence_repository,
            lead_workflow_repository=lead_workflow_repository,
            now=now,
        )
    if send_result.status in {
        SendOutboundMessageStatus.SENT,
        SendOutboundMessageStatus.ALREADY_SENT,
    }:
        if (
            send_result.message is not None
            and crm_client is not None
            and outbound_message_crm_completion_repository is not None
        ):
            lead = await lead_repository.get_by_id(workspace_id, lead_id)
            handoff_config = await _load_workspace_handoff_config(
                workspace_id=workspace_id,
                workspace_handoff_config_repository=workspace_handoff_config_repository,
            )
            if lead is not None:
                await complete_outbound_message_crm_sync(
                    lead=lead,
                    outbound_message=send_result.message,
                    crm_sync_completion_repository=outbound_message_crm_completion_repository,
                    crm_client=crm_client,
                    now=now,
                    summary_text=_summary_text_for_outbound_conversation(send_result.message),
                    latest_inbound_text=await _latest_inbound_conversation_text(
                        workspace_id=workspace_id,
                        lead_id=lead_id,
                        crm_conversation_event_repository=crm_conversation_event_repository,
                    ),
                    workspace_handoff_config=handoff_config,
                    snapshot_status="waiting_for_response",
                )
        if is_paused_search_step:
            result = await advance_paused_search_workflow_after_outbound_send(
                workspace_id=workspace_id,
                lead_id=lead_id,
                workflow=workflow,
                lead_workflow_repository=lead_workflow_repository,
                workflow_transition_repository=workflow_transition_repository,
                cadence_steps=cadence_steps,
                cadence_step_id=step.cadence_step_id,
                send_result=send_result,
                now=now,
            )
            return replace(
                result,
                occurrence_id=(
                    paused_search_occurrence.occurrence_id
                    if paused_search_occurrence is not None
                    else None
                ),
                fallback_used=fallback_used,
            )
        return await advance_workflow_after_outbound_send(
            workspace_id=workspace_id,
            lead_id=lead_id,
            workflow=workflow,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            cadence_steps=cadence_steps,
            cadence_step_id=step.cadence_step_id,
            send_result=send_result,
            now=now,
        )

    block_metadata = _send_block_metadata(
        cadence_step_id=step.cadence_step_id,
        send_result=send_result,
    )
    result = await _pause_after_block(
        workspace_id=workspace_id,
        lead_id=lead_id,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        cadence_step_id=step.cadence_step_id,
        now=now,
        reason_code=(
            WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED
            if send_result.status == SendOutboundMessageStatus.REJECTED
            else WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_FAILED
        ),
        skip_reason=str(block_metadata.get("explanation", _reason_values(send_result.reasons))),
        metadata=block_metadata,
        pause_reason=(
            "provider_failure_exhausted"
            if send_result.provider_failure_id is not None
            else "cadence_step_blocked"
        ),
        status={
            SendOutboundMessageStatus.REJECTED: CadenceStepExecutionStatus.REJECTED,
            SendOutboundMessageStatus.FAILED: CadenceStepExecutionStatus.FAILED,
            SendOutboundMessageStatus.UNCERTAIN: CadenceStepExecutionStatus.UNCERTAIN,
        }.get(send_result.status, CadenceStepExecutionStatus.FAILED),
        reconciliation_id=send_result.reconciliation_id,
        provider_failure_id=send_result.provider_failure_id,
    )
    return replace(
        result,
        occurrence_id=(
            paused_search_occurrence.occurrence_id if paused_search_occurrence is not None else None
        ),
    )


async def _journey_change_for_workflow(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    workflow: LeadWorkflow,
    journey_kind: OutboundJourneyKind,
    lead_workflow_repository: LeadWorkflowRepository,
) -> OutboundJourneyChange | None:
    """Detect whether earlier outreach was written for a different journey or track.

    Looks at the lead's most recent prior workflow (the one before the current
    one) so the drafting prompt can tell the LLM that copy from that journey's
    messages no longer applies.
    """
    previous_workflows = await lead_workflow_repository.list_recent_for_lead(
        workspace_id,
        lead_id,
        limit=5,
    )
    previous = next(
        (
            candidate
            for candidate in previous_workflows
            if candidate.workflow_id != workflow.workflow_id
        ),
        None,
    )
    if previous is None:
        return None
    previous_journey_kind = (
        OutboundJourneyKind.PAUSED_SEARCH
        if previous.paused_search_track_version_id is not None
        else OutboundJourneyKind.DORMANT
    )
    track_changed = (
        previous_journey_kind == OutboundJourneyKind.PAUSED_SEARCH
        and journey_kind == OutboundJourneyKind.PAUSED_SEARCH
        and previous.paused_search_track_version_id != workflow.paused_search_track_version_id
    )
    if previous_journey_kind == journey_kind and not track_changed:
        return None
    return OutboundJourneyChange(
        previous_journey_kind=previous_journey_kind,
        track_changed=track_changed,
    )


async def _pause_after_block(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    cadence_step_id: UUID,
    now: datetime,
    reason_code: WorkflowTransitionReasonCode,
    skip_reason: str,
    metadata: Mapping[str, object] | None = None,
    status: CadenceStepExecutionStatus,
    reconciliation_id: UUID | None = None,
    provider_failure_id: UUID | None = None,
    pause_reason: str = "cadence_step_blocked",
) -> CadenceStepExecutionResult:
    transition_metadata: dict[str, object] = {
        "cadence_step_id": str(cadence_step_id),
        "reason": skip_reason,
    }
    if metadata is not None:
        transition_metadata.update(metadata)

    outcome = await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=lead_id,
        to_state=WorkflowState.PAUSED,
        reason_code=reason_code,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=now,
        metadata=transition_metadata,
        pause_reason=pause_reason,
    )
    return CadenceStepExecutionResult(
        status=status,
        workflow=outcome.workflow,
        transition_id=outcome.transition_id,
        cadence_step_id=cadence_step_id,
        skip_reason=skip_reason or outcome.skip_reason,
        reconciliation_id=reconciliation_id,
        provider_failure_id=provider_failure_id,
    )


async def _save_step_cursor(
    *,
    workflow: LeadWorkflow,
    cadence_step_id: UUID,
    scheduled_for: datetime,
    is_paused_search_step: bool,
    lead_workflow_repository: LeadWorkflowRepository,
    now: datetime,
) -> LeadWorkflow:
    if is_paused_search_step:
        return await lead_workflow_repository.save(
            replace(
                workflow,
                current_step_id=None,
                paused_search_track_step_id=cadence_step_id,
                next_action_at=scheduled_for,
                updated_at=now,
            )
        )
    return await lead_workflow_repository.save(
        replace(
            workflow,
            current_step_id=cadence_step_id,
            next_action_at=scheduled_for,
            updated_at=now,
        )
    )


async def _save_next_step_cursor_after_skip(
    *,
    workflow: LeadWorkflow,
    cadence_step_id: UUID,
    is_paused_search_step: bool,
    lead_workflow_repository: LeadWorkflowRepository,
    now: datetime,
) -> LeadWorkflow:
    if is_paused_search_step:
        return await lead_workflow_repository.save(
            replace(
                workflow,
                current_step_id=None,
                paused_search_track_step_id=cadence_step_id,
                next_action_at=None,
                updated_at=now,
            )
        )
    return await lead_workflow_repository.save(
        replace(
            workflow,
            current_step_id=cadence_step_id,
            next_action_at=None,
            updated_at=now,
        )
    )


async def _clear_step_cursor(
    *,
    workflow: LeadWorkflow,
    is_paused_search_step: bool,
    lead_workflow_repository: LeadWorkflowRepository,
    now: datetime,
) -> LeadWorkflow:
    if is_paused_search_step:
        return await lead_workflow_repository.save(
            replace(
                workflow,
                current_step_id=None,
                paused_search_track_step_id=None,
                next_action_at=None,
                updated_at=now,
            )
        )
    return await lead_workflow_repository.save(
        replace(
            workflow,
            current_step_id=None,
            next_action_at=None,
            updated_at=now,
        )
    )


async def _handle_missing_step_destination(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    workflow: LeadWorkflow,
    lead: CanonicalLeadRecord,
    cadence_steps: tuple[CampaignCadenceStep, ...],
    cadence_step: CampaignCadenceStep,
    is_paused_search_step: bool,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    now: datetime,
) -> CadenceStepExecutionResult:
    if not any(lead_has_destination_for_channel(lead, step.channel) for step in cadence_steps):
        return await _pause_after_block(
            workspace_id=workspace_id,
            lead_id=lead_id,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            cadence_step_id=cadence_step.cadence_step_id,
            now=now,
            reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED,
            skip_reason="Planning blocked: no contact information found.",
            metadata={
                "cadence_step_id": str(cadence_step.cadence_step_id),
                "block_stage": "planning",
                "reason": PlanOutboundMessageReasonCode.NO_ENABLED_CHANNELS.value,
                "reason_codes": [PlanOutboundMessageReasonCode.NO_ENABLED_CHANNELS.value],
                "explanation": "Planning blocked: no contact information found.",
            },
            status=CadenceStepExecutionStatus.REJECTED,
        )

    next_step = _next_step(cadence_steps, cadence_step.cadence_step_id)
    skip_reason = (
        f"Skipped cadence step: no {cadence_step.channel.value} destination found for this lead."
    )
    if next_step is None:
        workflow = await _clear_step_cursor(
            workflow=workflow,
            is_paused_search_step=is_paused_search_step,
            lead_workflow_repository=lead_workflow_repository,
            now=now,
        )
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.SKIPPED,
            workflow=workflow,
            cadence_step_id=cadence_step.cadence_step_id,
            skip_reason=skip_reason,
        )

    workflow = await _save_next_step_cursor_after_skip(
        workflow=workflow,
        cadence_step_id=next_step.cadence_step_id,
        is_paused_search_step=is_paused_search_step,
        lead_workflow_repository=lead_workflow_repository,
        now=now,
    )
    return CadenceStepExecutionResult(
        status=CadenceStepExecutionStatus.SKIPPED,
        workflow=workflow,
        cadence_step_id=cadence_step.cadence_step_id,
        skip_reason=skip_reason,
        has_more_steps=True,
    )


async def _revalidate_paused_search_execution_gate(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    cadence_step_id: UUID,
    timezone: str,
    lead_repository: LeadRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    paused_search_track_repository: PausedSearchTrackRepository,
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository | None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None,
    recurring_paused_search_pilot_workspace_ids: Collection[WorkspaceId] | None,
    workflow: LeadWorkflow,
    now: datetime,
) -> tuple[LeadWorkflow, CadenceStepExecutionResult | None, RecurringOccurrence | None]:
    revalidated = await schedule_next_paused_search_action(
        workspace_id=workspace_id,
        lead_id=lead_id,
        lead_repository=lead_repository,
        paused_search_track_repository=paused_search_track_repository,
        occurrence_repository=paused_search_occurrence_repository,
        workspace_operational_control_repository=workspace_operational_control_repository,
        workspace_contact_policy_repository=workspace_contact_policy_repository,
        campaign_enrollment_repository=campaign_enrollment_repository,
        recurring_paused_search_pilot_workspace_ids=recurring_paused_search_pilot_workspace_ids,
        lead_workflow_repository=lead_workflow_repository,
        timezone=timezone,
        now=now,
    )
    refreshed_workflow = revalidated.workflow or workflow
    if revalidated.status != PausedSearchScheduleStatus.SCHEDULED:
        return (
            refreshed_workflow,
            CadenceStepExecutionResult(
                status=CadenceStepExecutionStatus.NO_CADENCE_STEP,
                workflow=refreshed_workflow,
                cadence_step_id=cadence_step_id,
                skip_reason=_paused_search_execution_skip_reason(revalidated),
            ),
            revalidated.occurrence,
        )

    if revalidated.step_id != cadence_step_id:
        return (
            refreshed_workflow,
            CadenceStepExecutionResult(
                status=CadenceStepExecutionStatus.SKIPPED,
                workflow=refreshed_workflow,
                cadence_step_id=cadence_step_id,
                skip_reason=(
                    "Paused-search timing changed before execution and a different "
                    "track step is now due."
                ),
            ),
            revalidated.occurrence,
        )

    if revalidated.next_action_at is None or revalidated.next_action_at > now:
        return (
            refreshed_workflow,
            CadenceStepExecutionResult(
                status=CadenceStepExecutionStatus.SKIPPED,
                workflow=refreshed_workflow,
                cadence_step_id=cadence_step_id,
                skip_reason=(
                    "Paused-search timing changed before execution and this action "
                    "is no longer due yet."
                ),
            ),
            revalidated.occurrence,
        )

    return refreshed_workflow, None, revalidated.occurrence


async def _record_paused_search_occurrence_outcome(
    *,
    workspace_id: WorkspaceId,
    workflow: LeadWorkflow,
    occurrence: RecurringOccurrence,
    authored_channel: ContactChannel,
    send_result: SendOutboundMessageResult,
    occurrence_repository: PausedSearchOccurrenceRepository | None,
    lead_workflow_repository: LeadWorkflowRepository,
    now: datetime,
) -> LeadWorkflow:
    if occurrence_repository is None:
        return workflow

    # A pre-send REJECTED result is a policy block ("not now"), not an
    # abandoned touch: the message never reached the lead, so the occurrence
    # must stay open (PLANNED) for the same slot to be retried after a resume.
    # Closing it as CANCELLED would consume the step's occurrence cap and
    # terminalize the workflow on the next scheduling pass.
    status_by_send_status = {
        SendOutboundMessageStatus.SENT: RecurringOccurrenceStatus.SENT,
        SendOutboundMessageStatus.ALREADY_SENT: RecurringOccurrenceStatus.SENT,
        SendOutboundMessageStatus.FAILED: RecurringOccurrenceStatus.FAILED,
        SendOutboundMessageStatus.UNCERTAIN: RecurringOccurrenceStatus.UNCERTAIN,
    }
    occurrence_status = status_by_send_status.get(send_result.status)
    if occurrence_status is None:
        return workflow

    message = send_result.message
    updated = await occurrence_repository.update_status(
        workspace_id=workspace_id,
        occurrence_id=occurrence.occurrence_id,
        status=occurrence_status.value,
        now=now,
        provider_message_id=message.provider_message_id if message is not None else None,
        provider_delivery_status=(
            message.provider_delivery_status if message is not None else None
        ),
        failure_reason=(
            message.failure_reason
            if message is not None and message.failure_reason is not None
            else ",".join(reason.value for reason in send_result.reasons) or None
        ),
        fallback_used=(message is not None and message.channel is not authored_channel),
    )
    if (
        updated is not None
        and occurrence.logical_touch_count == 0
        and updated.logical_touch_count == 1
    ):
        return await lead_workflow_repository.save(
            replace(
                workflow,
                logical_touch_count=workflow.logical_touch_count + 1,
                updated_at=now,
            )
        )
    return workflow


def _paused_search_execution_skip_reason(
    result: PausedSearchNextActionScheduleResult,
) -> str:
    return result.reason_detail or (
        result.reason_code.value
        if result.reason_code is not None
        else "paused-search action not sendable"
    )


async def advance_workflow_after_outbound_send(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    workflow: LeadWorkflow,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    cadence_steps: tuple[CampaignCadenceStep, ...],
    cadence_step_id: UUID,
    send_result: SendOutboundMessageResult,
    now: datetime,
) -> CadenceStepExecutionResult:
    waiting_outcome = await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=lead_id,
        to_state=WorkflowState.WAITING_FOR_RESPONSE,
        reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_SENT,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=now,
        metadata={
            "cadence_step_id": str(cadence_step_id),
            "outbound_message_id": (
                str(send_result.message.message_id) if send_result.message else None
            ),
        },
    )
    if (
        waiting_outcome.status != WorkflowStateTransitionStatus.UPDATED
        or waiting_outcome.workflow is None
    ):
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.SKIPPED,
            workflow=waiting_outcome.workflow or workflow,
            transition_id=waiting_outcome.transition_id,
            cadence_step_id=cadence_step_id,
            outbound_message_id=send_result.message.message_id if send_result.message else None,
            provider_message_id=(
                send_result.message.provider_message_id if send_result.message else None
            ),
            skip_reason=waiting_outcome.skip_reason,
        )

    next_step = _next_step(cadence_steps, cadence_step_id)
    workflow_outcome = await lead_workflow_repository.save(
        replace(
            waiting_outcome.workflow,
            current_step_id=next_step.cadence_step_id if next_step is not None else None,
            next_action_at=None,
            updated_at=now,
        )
    )
    return CadenceStepExecutionResult(
        status=(
            CadenceStepExecutionStatus.SENT
            if send_result.status == SendOutboundMessageStatus.SENT
            else CadenceStepExecutionStatus.ALREADY_SENT
        ),
        workflow=workflow_outcome,
        transition_id=waiting_outcome.transition_id,
        cadence_step_id=cadence_step_id,
        outbound_message_id=send_result.message.message_id if send_result.message else None,
        provider_message_id=(
            send_result.message.provider_message_id if send_result.message else None
        ),
        has_more_steps=next_step is not None,
    )


async def advance_paused_search_workflow_after_outbound_send(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    workflow: LeadWorkflow,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    cadence_steps: tuple[CampaignCadenceStep, ...],
    cadence_step_id: UUID,
    send_result: SendOutboundMessageResult,
    now: datetime,
) -> CadenceStepExecutionResult:
    waiting_outcome = await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=lead_id,
        to_state=WorkflowState.WAITING_FOR_RESPONSE,
        reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_SENT,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=now,
        metadata={
            "paused_search_track_step_id": str(cadence_step_id),
            "outbound_message_id": (
                str(send_result.message.message_id) if send_result.message else None
            ),
        },
    )
    if (
        waiting_outcome.status != WorkflowStateTransitionStatus.UPDATED
        or waiting_outcome.workflow is None
    ):
        return CadenceStepExecutionResult(
            status=CadenceStepExecutionStatus.SKIPPED,
            workflow=waiting_outcome.workflow or workflow,
            transition_id=waiting_outcome.transition_id,
            cadence_step_id=cadence_step_id,
            outbound_message_id=send_result.message.message_id if send_result.message else None,
            provider_message_id=(
                send_result.message.provider_message_id if send_result.message else None
            ),
            skip_reason=waiting_outcome.skip_reason,
        )

    next_step = _next_step(cadence_steps, cadence_step_id)
    workflow_outcome = await lead_workflow_repository.save(
        replace(
            waiting_outcome.workflow,
            current_step_id=None,
            paused_search_track_step_id=(
                next_step.cadence_step_id if next_step is not None else None
            ),
            next_action_at=None,
            updated_at=now,
        )
    )
    return CadenceStepExecutionResult(
        status=(
            CadenceStepExecutionStatus.SENT
            if send_result.status == SendOutboundMessageStatus.SENT
            else CadenceStepExecutionStatus.ALREADY_SENT
        ),
        workflow=workflow_outcome,
        transition_id=waiting_outcome.transition_id,
        cadence_step_id=cadence_step_id,
        outbound_message_id=send_result.message.message_id if send_result.message else None,
        provider_message_id=(
            send_result.message.provider_message_id if send_result.message else None
        ),
        has_more_steps=next_step is not None,
    )


def _scheduled_or_initial_step(
    steps: tuple[CampaignCadenceStep, ...],
    current_step_id: UUID | None,
) -> CampaignCadenceStep | None:
    if not steps:
        return None
    if current_step_id is None:
        return steps[0]
    return _step_by_id(steps, current_step_id)


async def _load_workspace_handoff_config(
    *,
    workspace_id: WorkspaceId,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None,
) -> WorkspaceHandoffConfig | None:
    if workspace_handoff_config_repository is None:
        return None
    return await workspace_handoff_config_repository.get_by_workspace_id(workspace_id)


async def _latest_inbound_conversation_text(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    crm_conversation_event_repository: CrmConversationEventRepository | None,
) -> str | None:
    if crm_conversation_event_repository is None:
        return None
    events = await crm_conversation_event_repository.list_for_lead(
        workspace_id,
        lead_id,
        limit=24,
    )
    for event in events:
        if event.direction != CrmConversationEventDirection.INBOUND or event.content is None:
            continue
        content = event.content.strip()
        if content:
            return content
    return None


def _summary_text_for_outbound_conversation(message: object) -> str | None:
    notes = getattr(message, "draft_personalization_notes", ())
    if not isinstance(notes, tuple):
        return None
    normalized_notes = [note.strip() for note in notes if isinstance(note, str) and note.strip()]
    if not normalized_notes:
        return None
    return "\n".join(normalized_notes)


def _step_by_id(
    steps: tuple[CampaignCadenceStep, ...],
    cadence_step_id: UUID,
) -> CampaignCadenceStep | None:
    for step in steps:
        if step.cadence_step_id == cadence_step_id:
            return step
    return None


def _paused_search_steps_as_cadence_steps(
    steps: tuple[PausedSearchTrackStep, ...],
    *,
    campaign_version_id: CampaignVersionId,
) -> tuple[CampaignCadenceStep, ...]:
    return tuple(
        CampaignCadenceStep(
            cadence_step_id=step.step_id,
            workspace_id=step.workspace_id,
            campaign_version_id=campaign_version_id,
            step_order=step.step_order,
            channel=step.channel,
            delay_hours=step.delay_hours,
            message_goal=step.message_goal,
            template_key=step.template_key,
            max_attempts=step.max_attempts,
            created_at=step.created_at,
            template_version_id=step.template_version_id,
            template_profile=step.template_profile,
        )
        for step in steps
    )


def _paused_search_schedule_result(
    result: PausedSearchNextActionScheduleResult,
) -> CadenceStepScheduleResult:
    if result.status == PausedSearchScheduleStatus.SCHEDULED:
        return CadenceStepScheduleResult(
            status=CadenceStepScheduleStatus.SCHEDULED,
            workflow=result.workflow,
            cadence_step_id=result.step_id,
            scheduled_for=result.next_action_at,
            skip_reason=result.reason_detail,
            occurrence_id=result.occurrence.occurrence_id if result.occurrence else None,
        )
    if result.status == PausedSearchScheduleStatus.NO_WORKFLOW:
        status = CadenceStepScheduleStatus.NO_WORKFLOW
    elif result.status == PausedSearchScheduleStatus.TERMINAL:
        status = CadenceStepScheduleStatus.TERMINAL
    elif result.status == PausedSearchScheduleStatus.REVIEW:
        status = CadenceStepScheduleStatus.REVIEW
    elif result.status == PausedSearchScheduleStatus.HOLD:
        status = CadenceStepScheduleStatus.HOLD
    else:
        status = CadenceStepScheduleStatus.NO_CADENCE_STEP
    return CadenceStepScheduleResult(
        status=status,
        workflow=result.workflow,
        cadence_step_id=result.step_id,
        scheduled_for=result.next_action_at,
        skip_reason=(
            result.reason_detail or (result.reason_code.value if result.reason_code else None)
        ),
        occurrence_id=result.occurrence.occurrence_id if result.occurrence else None,
    )


def _workflow_has_no_remaining_cadence_steps(workflow: LeadWorkflow) -> bool:
    return (
        workflow.state == WorkflowState.WAITING_FOR_RESPONSE
        and workflow.next_action_at is None
        and workflow.current_step_id is None
        and workflow.paused_search_track_step_id is None
    )


def _next_step(
    steps: tuple[CampaignCadenceStep, ...],
    current_step_id: UUID,
) -> CampaignCadenceStep | None:
    for index, step in enumerate(steps):
        if step.cadence_step_id == current_step_id:
            next_index = index + 1
            return steps[next_index] if next_index < len(steps) else None
    return None


def _reason_values(reasons: tuple[StrEnum, ...]) -> str:
    return ", ".join(reason.value for reason in reasons)


def _reason_value_list(reasons: tuple[StrEnum, ...]) -> list[str]:
    return [reason.value for reason in reasons]


def _planning_block_metadata(
    *,
    cadence_step_id: UUID,
    plan_result: PlanOutboundMessageResult,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "cadence_step_id": str(cadence_step_id),
        "block_stage": "planning",
        "reason": _reason_values(plan_result.reasons),
        "reason_codes": _reason_value_list(plan_result.reasons),
    }
    if plan_result.selected_channel is not None:
        metadata["selected_channel"] = plan_result.selected_channel.value
    if plan_result.channel_evaluations:
        metadata["evaluated_channels"] = [
            evaluation.channel.value for evaluation in plan_result.channel_evaluations
        ]
        blocked_outcomes = [
            evaluation.outcome.value
            for evaluation in plan_result.channel_evaluations
            if evaluation.outcome.value != "selected"
        ]
        if blocked_outcomes:
            metadata["channel_block_outcomes"] = blocked_outcomes
    if plan_result.pre_send_decision is not None:
        metadata["pre_send_reasons"] = _reason_value_list(plan_result.pre_send_decision.reasons)
        if plan_result.pre_send_decision.next_allowed_at is not None:
            metadata["next_allowed_at"] = plan_result.pre_send_decision.next_allowed_at.isoformat()
    elif plan_result.channel_evaluations:
        pre_send_reasons = _planning_pre_send_reasons(plan_result.channel_evaluations)
        if pre_send_reasons:
            metadata["pre_send_reasons"] = pre_send_reasons
        next_allowed_at = _planning_next_allowed_at(plan_result.channel_evaluations)
        if next_allowed_at is not None:
            metadata["next_allowed_at"] = next_allowed_at.isoformat()
    if plan_result.draft_result is not None:
        metadata["draft_status"] = plan_result.draft_result.status.value
        metadata["draft_reasons"] = _reason_value_list(plan_result.draft_reasons)
        metadata["draft_safety_flags"] = list(plan_result.draft_result.safety_flags)
        if plan_result.draft_result.confidence is not None:
            metadata["draft_confidence"] = plan_result.draft_result.confidence
        if plan_result.draft_result.model is not None:
            metadata["draft_model"] = plan_result.draft_result.model
        metadata["draft_prompt_version"] = plan_result.draft_result.prompt_version
    metadata["explanation"] = _planning_block_explanation(plan_result)
    return _compact_metadata(metadata)


def _send_block_metadata(
    *,
    cadence_step_id: UUID,
    send_result: SendOutboundMessageResult,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "cadence_step_id": str(cadence_step_id),
        "block_stage": "sending",
        "reason": _reason_values(send_result.reasons),
        "reason_codes": _reason_value_list(send_result.reasons),
    }
    if send_result.message is not None:
        metadata["selected_channel"] = send_result.message.channel.value
        metadata["message_status"] = send_result.message.status.value
        metadata["provider_send_status"] = send_result.message.provider_send_status.value
    if send_result.provider_failure_id is not None:
        metadata["provider_failure_id"] = str(send_result.provider_failure_id)
        metadata["provider_failure_surface"] = "operator_review_required"
    if send_result.pre_send_decision is not None:
        metadata["pre_send_reasons"] = _reason_value_list(send_result.pre_send_decision.reasons)
        if send_result.pre_send_decision.next_allowed_at is not None:
            metadata["next_allowed_at"] = send_result.pre_send_decision.next_allowed_at.isoformat()
    metadata["explanation"] = _send_block_explanation(send_result)
    return _compact_metadata(metadata)


def _planning_block_explanation(plan_result: PlanOutboundMessageResult) -> str:
    if plan_result.reasons == (PlanOutboundMessageReasonCode.NO_ENABLED_CHANNELS,):
        parts = ["Planning blocked: no contact information found."]
    else:
        parts = [f"Planning blocked: {_humanized_reason_values(plan_result.reasons)}."]
    if plan_result.channel_evaluations:
        considered_channels = _humanized_strings(
            evaluation.channel.value for evaluation in plan_result.channel_evaluations
        )
        parts.append(f"Channels considered: {considered_channels}.")
    if plan_result.draft_reasons:
        parts.append(
            f"Draft validation failed: {_humanized_reason_values(plan_result.draft_reasons)}."
        )
    if plan_result.draft_result is not None and plan_result.draft_result.safety_flags:
        parts.append(f"Safety flags: {_humanized_strings(plan_result.draft_result.safety_flags)}.")
    planning_pre_send_reasons = (
        _reason_value_list(plan_result.pre_send_decision.reasons)
        if plan_result.pre_send_decision is not None
        else _planning_pre_send_reasons(plan_result.channel_evaluations)
    )
    if planning_pre_send_reasons:
        parts.append(
            f"Pre-send checks blocked the message: {_humanized_strings(planning_pre_send_reasons)}."
        )
    next_allowed_at = (
        plan_result.pre_send_decision.next_allowed_at
        if plan_result.pre_send_decision is not None
        else _planning_next_allowed_at(plan_result.channel_evaluations)
    )
    if next_allowed_at is not None:
        parts.append(f"Next eligible send time: {next_allowed_at.isoformat()}.")
    return " ".join(parts)


def _send_block_explanation(send_result: SendOutboundMessageResult) -> str:
    parts = [f"Sending blocked: {_humanized_reason_values(send_result.reasons)}."]
    if send_result.pre_send_decision is not None and send_result.pre_send_decision.reasons:
        parts.append(
            "Pre-send checks blocked delivery: "
            f"{_humanized_reason_values(send_result.pre_send_decision.reasons)}."
        )
    if send_result.pre_send_decision is not None and send_result.pre_send_decision.next_allowed_at:
        parts.append(
            f"Next eligible send time: {send_result.pre_send_decision.next_allowed_at.isoformat()}."
        )
    return " ".join(parts)


def _humanized_reason_values(reasons: tuple[StrEnum, ...]) -> str:
    return _humanized_strings(reason.value for reason in reasons)


def _planning_pre_send_reasons(channel_evaluations: tuple[ChannelEvaluation, ...]) -> list[str]:
    return list(
        dict.fromkeys(
            reason.value
            for evaluation in channel_evaluations
            for reason in evaluation.pre_send_reasons
        )
    )


def _pre_send_crm_refresh_context(
    *,
    crm_client: CRMClient | None,
    crm_agent_repository: CRMAgentRepository | None,
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository | None,
    workspace_agent_mapping_config_repository: WorkspaceAgentMappingConfigRepository | None,
    workspace_membership_repository: WorkspaceMembershipRepository | None,
    user_repository: UserRepository | None,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None,
) -> PreSendCRMRefreshContext | None:
    if not all(
        dependency is not None
        for dependency in (
            crm_client,
            crm_agent_repository,
            workspace_agent_crm_mapping_repository,
            workspace_agent_mapping_config_repository,
            workspace_membership_repository,
            user_repository,
        )
    ):
        return None
    assert crm_client is not None
    assert crm_agent_repository is not None
    assert workspace_agent_crm_mapping_repository is not None
    assert workspace_agent_mapping_config_repository is not None
    assert workspace_membership_repository is not None
    assert user_repository is not None
    return PreSendCRMRefreshContext(
        lead_refresh_source=cast(CanonicalLeadRefreshSource, crm_client),
        crm_activity_source=crm_client,
        crm_agent_repository=crm_agent_repository,
        workspace_agent_crm_mapping_repository=workspace_agent_crm_mapping_repository,
        workspace_agent_mapping_config_repository=workspace_agent_mapping_config_repository,
        workspace_membership_repository=workspace_membership_repository,
        user_repository=user_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
    )


def _planning_next_allowed_at(
    channel_evaluations: tuple[ChannelEvaluation, ...],
) -> datetime | None:
    for evaluation in channel_evaluations:
        if evaluation.next_allowed_at is not None:
            return evaluation.next_allowed_at
    return None


def _should_persist_rejected_draft_review(plan_result: PlanOutboundMessageResult) -> bool:
    return plan_result.draft_result is not None and any(
        reason.value == "draft_rejected" for reason in plan_result.reasons
    )


def _rejected_draft_review(
    *,
    workspace_id: WorkspaceId,
    workflow_id: UUID,
    transition_id: UUID,
    campaign_id: UUID,
    campaign_version_id: UUID,
    lead_id: LeadId,
    cadence_step_id: UUID,
    channel: ContactChannel,
    plan_result: PlanOutboundMessageResult,
    now: datetime,
) -> RejectedDraftReview:
    assert plan_result.draft_result is not None
    review_blockers = _review_blockers(plan_result)
    return RejectedDraftReview(
        review_id=uuid4(),
        workspace_id=workspace_id,
        lead_id=lead_id,
        workflow_id=workflow_id,
        workflow_transition_id=transition_id,
        campaign_id=campaign_id,
        campaign_version_id=campaign_version_id,
        cadence_step_id=cadence_step_id,
        channel=channel,
        status=RejectedDraftReviewStatus.PENDING_REVIEW,
        reason_codes=tuple(reason.value for reason in plan_result.reasons),
        draft_reason_codes=tuple(reason.value for reason in plan_result.draft_reasons),
        review_blockers=review_blockers,
        draft_safety_flags=tuple(plan_result.draft_result.safety_flags),
        draft_personalization_notes=tuple(plan_result.draft_result.personalization_notes),
        draft_body=plan_result.draft_result.body,
        draft_subject=plan_result.draft_result.subject,
        raw_llm_response_text=plan_result.draft_result.raw_llm_response_text,
        validation_error=plan_result.draft_result.validation_error,
        explanation=_planning_block_explanation(plan_result),
        draft_confidence=plan_result.draft_result.confidence,
        draft_model=plan_result.draft_result.model,
        draft_prompt_version=plan_result.draft_result.prompt_version,
        draft_latency_ms=plan_result.draft_result.latency_ms,
        draft_usage_tokens=plan_result.draft_result.usage_tokens,
        message_version=1,
        can_approve_send=not review_blockers,
        created_at=now,
        updated_at=now,
    )


def _review_blockers(plan_result: PlanOutboundMessageResult) -> tuple[str, ...]:
    blockers: list[str] = []
    draft_result = plan_result.draft_result
    if draft_result is None:
        blockers.append("missing_draft_result")
    else:
        if draft_result.body is None:
            blockers.append("missing_draft_body")
        if draft_result.reasons:
            blockers.extend(
                reason.value for reason in draft_result.reasons if reason.value != "low_confidence"
            )
        if draft_result.safety_flags:
            blockers.append("safety_flags_present")
    return tuple(dict.fromkeys(blockers))


def _humanized_strings(values: Iterable[str]) -> str:
    return ", ".join(str(value).replace("_", " ") for value in values)


def _compact_metadata(metadata: dict[str, object]) -> dict[str, object]:
    compacted: dict[str, object] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        if isinstance(value, (list, tuple)) and len(value) == 0:
            continue
        compacted[key] = value
    return compacted
