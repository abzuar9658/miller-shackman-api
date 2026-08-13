from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from app.application.ports.crm import CRMActivity
from app.application.ports.crm_sync import CanonicalLeadRefreshSource
from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    CRMAgentRepository,
    LeadRepository,
    LeadWorkflowRepository,
    TemporalSignalOutboxRepository,
    UserRepository,
    WorkflowTransitionRepository,
    WorkspaceAgentCRMMappingRepository,
    WorkspaceAgentMappingConfigRepository,
    WorkspaceMembershipRepository,
)
from app.application.services.lead_assignment_resolution import (
    apply_lead_assignment_resolution,
    load_workspace_lead_assignment_context,
)
from app.application.use_cases.reconcile_lead_assignment import (
    LeadAssignmentMessageRepository,
    LeadAssignmentReconciliationResult,
    reconcile_lead_assignment_change,
)
from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.common.ids import WorkspaceId
from app.domain.leads import CanonicalLeadRecord, preserve_app_owned_lead_state


class CRMActivitySource(Protocol):
    async def get_recent_activity(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
        limit: int = 50,
    ) -> list[CRMActivity]:
        raise NotImplementedError


@dataclass(frozen=True)
class PreSendCRMRefreshContext:
    lead_refresh_source: CanonicalLeadRefreshSource
    crm_activity_source: CRMActivitySource
    crm_agent_repository: CRMAgentRepository
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository
    workspace_agent_mapping_config_repository: WorkspaceAgentMappingConfigRepository
    workspace_membership_repository: WorkspaceMembershipRepository
    user_repository: UserRepository
    lead_workflow_repository: LeadWorkflowRepository | None = None
    workflow_transition_repository: WorkflowTransitionRepository | None = None
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None = None
    activity_limit: int = 20


class PreSendCRMRefreshStatus(StrEnum):
    REFRESHED = "refreshed"
    FAILED = "failed"
    LEAD_NOT_FOUND = "lead_not_found"


@dataclass(frozen=True)
class PreSendCRMRefreshResult:
    status: PreSendCRMRefreshStatus
    lead: CanonicalLeadRecord | None = None
    recent_human_activity: bool = False
    assignment_reconciliation: LeadAssignmentReconciliationResult | None = None
    failure_reason: str | None = None


async def refresh_lead_for_pre_send(
    *,
    lead: CanonicalLeadRecord,
    message: OutboundMessage,
    lead_repository: LeadRepository,
    message_repository: LeadAssignmentMessageRepository,
    crm_refresh_context: PreSendCRMRefreshContext,
    event_bus: EventBus | None,
    now: datetime,
) -> PreSendCRMRefreshResult:
    try:
        refreshed_lead = await crm_refresh_context.lead_refresh_source.get_lead_snapshot(
            workspace_id=lead.workspace_id,
            crm_lead_id=lead.crm_lead_id,
            mapped_custom_field_keys=tuple(lead.mapped_custom_fields.keys()),
        )
        activities = await crm_refresh_context.crm_activity_source.get_recent_activity(
            lead.workspace_id,
            lead.crm_lead_id,
            limit=crm_refresh_context.activity_limit,
        )
        if refreshed_lead is None:
            return PreSendCRMRefreshResult(status=PreSendCRMRefreshStatus.LEAD_NOT_FOUND)

        assignment_context = await load_workspace_lead_assignment_context(
            workspace_id=lead.workspace_id,
            crm_agent_repository=crm_refresh_context.crm_agent_repository,
            workspace_agent_crm_mapping_repository=(
                crm_refresh_context.workspace_agent_crm_mapping_repository
            ),
            workspace_agent_mapping_config_repository=(
                crm_refresh_context.workspace_agent_mapping_config_repository
            ),
            workspace_membership_repository=crm_refresh_context.workspace_membership_repository,
            user_repository=crm_refresh_context.user_repository,
        )
        resolved_lead = apply_lead_assignment_resolution(
            preserve_app_owned_lead_state(refreshed_lead, lead),
            context=assignment_context,
            now=now,
        )
        saved_lead = await lead_repository.upsert(resolved_lead)
        reconciliation = await reconcile_lead_assignment_change(
            previous_lead=lead,
            current_lead=saved_lead,
            lead_workflow_repository=crm_refresh_context.lead_workflow_repository,
            workflow_transition_repository=crm_refresh_context.workflow_transition_repository,
            temporal_signal_outbox_repository=crm_refresh_context.temporal_signal_outbox_repository,
            outbound_message_repository=message_repository,
            event_bus=event_bus,
            now=now,
        )
    except Exception as exc:
        return PreSendCRMRefreshResult(
            status=PreSendCRMRefreshStatus.FAILED,
            failure_reason=str(exc) or exc.__class__.__name__,
        )

    return PreSendCRMRefreshResult(
        status=PreSendCRMRefreshStatus.REFRESHED,
        lead=saved_lead,
        recent_human_activity=_recent_human_activity_detected(
            lead=lead,
            refreshed_lead=saved_lead,
            activities=activities,
            message=message,
        ),
        assignment_reconciliation=reconciliation,
    )


def _recent_human_activity_detected(
    *,
    lead: CanonicalLeadRecord,
    refreshed_lead: CanonicalLeadRecord,
    activities: list[CRMActivity],
    message: OutboundMessage,
) -> bool:
    if (
        refreshed_lead.last_agent_activity_at is not None
        and refreshed_lead.last_agent_activity_at > message.created_at
        and refreshed_lead.last_agent_activity_at != lead.last_agent_activity_at
    ):
        return True
    return any(
        activity.agent_id is not None and activity.timestamp > message.created_at
        for activity in activities
    )