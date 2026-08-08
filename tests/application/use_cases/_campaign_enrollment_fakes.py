from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from app.application.ports.temporal import (
    InboundProcessedLeadNurtureWorkflowSignal,
    PauseLeadNurtureWorkflowSignal,
    RescheduleLeadNurtureWorkflowSignal,
    ResumeLeadNurtureWorkflowSignal,
    TemporalWorkflowExecutionMode,
    UnblockLeadNurtureWorkflowSignal,
)
from app.domain.campaigns.enrollment import CampaignEnrollment
from app.domain.common.ids import CampaignVersionId, LeadId, WorkspaceId
from app.domain.workflows import (
    LeadWorkflow,
    TemporalSignalOutboxEntry,
    TemporalSignalOutboxStatus,
    WorkflowState,
    WorkflowTransition,
)


class FakeCampaignEnrollmentRepository:
    def __init__(self) -> None:
        self.enrollments: dict[tuple[WorkspaceId, LeadId, UUID], CampaignEnrollment] = {}

    async def get_by_lead_and_campaign(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        campaign_id: UUID,
    ) -> CampaignEnrollment | None:
        return self.enrollments.get((workspace_id, lead_id, campaign_id))

    async def save(self, enrollment: CampaignEnrollment) -> CampaignEnrollment:
        self.enrollments[(enrollment.workspace_id, enrollment.lead_id, enrollment.campaign_id)] = (
            enrollment
        )
        return enrollment

    async def count_started_today(
        self,
        workspace_id: WorkspaceId,
        campaign_id: UUID,
        started_since: object,
    ) -> int:
        today_start = (
            started_since.replace(hour=0, minute=0, second=0, microsecond=0)
            if isinstance(started_since, datetime)
            else datetime.min.replace(tzinfo=UTC)
        )
        tomorrow_start = today_start + timedelta(days=1)
        return sum(
            1
            for enrollment in self.enrollments.values()
            if enrollment.workspace_id == workspace_id
            and enrollment.campaign_id == campaign_id
            and enrollment.started_at is not None
            and today_start <= enrollment.started_at < tomorrow_start
        )


class FakeLeadWorkflowRepository:
    def __init__(self) -> None:
        self.workflows: dict[UUID, LeadWorkflow] = {}
        self.latest_by_lead: dict[tuple[WorkspaceId, LeadId], LeadWorkflow] = {}

    async def get_latest_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> LeadWorkflow | None:
        return self.latest_by_lead.get((workspace_id, lead_id))

    async def get_latest_for_lead_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> LeadWorkflow | None:
        return self.latest_by_lead.get((workspace_id, lead_id))

    async def list_active_paused_search_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> tuple[LeadWorkflow, ...]:
        return self._active_paused_search_for_lead(workspace_id, lead_id)

    async def list_active_paused_search_for_lead_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> tuple[LeadWorkflow, ...]:
        return self._active_paused_search_for_lead(workspace_id, lead_id)

    def _active_paused_search_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> tuple[LeadWorkflow, ...]:
        active_states = {
            WorkflowState.QUEUED,
            WorkflowState.ACTIVE_NURTURE,
            WorkflowState.WAITING_FOR_RESPONSE,
            WorkflowState.RESPONSE_PROCESSING,
        }
        return tuple(
            workflow
            for workflow in self.workflows.values()
            if workflow.workspace_id == workspace_id
            and workflow.lead_id == lead_id
            and workflow.paused_search_track_version_id is not None
            and workflow.state in active_states
        )

    async def list_paused_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[LeadWorkflow, ...]:
        matches = tuple(
            workflow
            for workflow in self.latest_by_lead.values()
            if workflow.workspace_id == workspace_id and workflow.state == WorkflowState.PAUSED
        )
        return matches[:limit]

    async def list_latest_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[LeadWorkflow, ...]:
        matches = tuple(
            workflow
            for workflow in self.latest_by_lead.values()
            if workflow.workspace_id == workspace_id
        )
        return matches[:limit]

    async def save(self, workflow: LeadWorkflow) -> LeadWorkflow:
        self.workflows[workflow.workflow_id] = workflow
        self.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow
        return workflow


class FakeWorkflowTransitionRepository:
    def __init__(self) -> None:
        self.transitions: dict[UUID, WorkflowTransition] = {}

    async def append(self, transition: WorkflowTransition) -> WorkflowTransition:
        self.transitions[transition.transition_id] = transition
        return transition

    async def list_for_workflow(
        self,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        limit: int = 100,
    ) -> tuple[WorkflowTransition, ...]:
        return tuple(
            transition
            for transition in self.transitions.values()
            if transition.workspace_id == workspace_id and transition.workflow_id == workflow_id
        )


class FakeTemporalWorkflowStarter:
    def __init__(self, *, always_fail: bool = False) -> None:
        self.calls: list[dict[str, object]] = []
        self.always_fail = always_fail

    async def start_lead_nurture_workflow(
        self,
        *,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        campaign_version_id: CampaignVersionId,
        temporal_workflow_id: str,
        workflow_id: UUID | None = None,
        execution_mode: TemporalWorkflowExecutionMode = (
            TemporalWorkflowExecutionMode.STANDARD_CADENCE
        ),
        paused_search_track_version_id: UUID | None = None,
    ) -> None:
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "lead_id": lead_id,
                "campaign_version_id": campaign_version_id,
                "temporal_workflow_id": temporal_workflow_id,
                "workflow_id": workflow_id,
                "execution_mode": execution_mode,
                "paused_search_track_version_id": paused_search_track_version_id,
            }
        )
        if self.always_fail:
            raise RuntimeError("Temporal start failed")

    async def configure_paused_search_workflow(
        self,
        *,
        temporal_workflow_id: str,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        workflow_id: UUID,
        paused_search_track_version_id: UUID,
        occurred_at: datetime,
        reason: str,
    ) -> None:
        self.calls.append(
            {
                "temporal_workflow_id": temporal_workflow_id,
                "workspace_id": workspace_id,
                "lead_id": lead_id,
                "workflow_id": workflow_id,
                "paused_search_track_version_id": paused_search_track_version_id,
                "occurred_at": occurred_at,
                "reason": reason,
                "operation": "configure_paused_search_workflow",
            }
        )


class FakeLeadNurtureWorkflowSignaler:
    def __init__(self, *, always_fail: bool = False) -> None:
        self.calls: list[dict[str, object]] = []
        self.always_fail = always_fail

    async def signal_pause_lead_nurture_workflow(
        self,
        *,
        temporal_workflow_id: str,
        signal: PauseLeadNurtureWorkflowSignal,
    ) -> None:
        self.calls.append(
            {
                "temporal_workflow_id": temporal_workflow_id,
                "signal": signal,
            }
        )
        if self.always_fail:
            raise RuntimeError("Temporal pause signal failed")

    async def signal_resume_lead_nurture_workflow(
        self,
        *,
        temporal_workflow_id: str,
        signal: ResumeLeadNurtureWorkflowSignal,
    ) -> None:
        self.calls.append(
            {
                "temporal_workflow_id": temporal_workflow_id,
                "signal": signal,
            }
        )
        if self.always_fail:
            raise RuntimeError("Temporal resume signal failed")

    async def signal_unblock_lead_nurture_workflow(
        self,
        *,
        temporal_workflow_id: str,
        signal: UnblockLeadNurtureWorkflowSignal,
    ) -> None:
        self.calls.append({"temporal_workflow_id": temporal_workflow_id, "signal": signal})
        if self.always_fail:
            raise RuntimeError("Temporal unblock signal failed")

    async def signal_inbound_processed_lead_nurture_workflow(
        self,
        *,
        temporal_workflow_id: str,
        signal: InboundProcessedLeadNurtureWorkflowSignal,
    ) -> None:
        self.calls.append({"temporal_workflow_id": temporal_workflow_id, "signal": signal})
        if self.always_fail:
            raise RuntimeError("Temporal inbound processed signal failed")

    async def signal_reschedule_lead_nurture_workflow(
        self,
        *,
        temporal_workflow_id: str,
        signal: RescheduleLeadNurtureWorkflowSignal,
    ) -> None:
        self.calls.append({"temporal_workflow_id": temporal_workflow_id, "signal": signal})
        if self.always_fail:
            raise RuntimeError("Temporal reschedule signal failed")


NOW = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


class FakeTemporalSignalOutboxRepository:
    def __init__(self) -> None:
        self.entries: dict[tuple[UUID, str], TemporalSignalOutboxEntry] = {}

    async def append(self, entry: TemporalSignalOutboxEntry) -> TemporalSignalOutboxEntry:
        key = (entry.workspace_id, entry.idempotency_key)
        existing = self.entries.get(key)
        if existing is not None:
            return existing
        self.entries[key] = entry
        return entry

    async def claim_available_batch(
        self,
        *,
        now: datetime,
        limit: int,
        lease_duration: timedelta,
        max_attempts: int,
    ) -> tuple[TemporalSignalOutboxEntry, ...]:
        claimed: list[TemporalSignalOutboxEntry] = []
        for key, entry in sorted(self.entries.items(), key=lambda item: item[1].created_at or NOW):
            if len(claimed) >= limit:
                break
            ready = (
                entry.status
                in {
                    TemporalSignalOutboxStatus.PENDING,
                    TemporalSignalOutboxStatus.FAILED,
                }
                and entry.available_at is not None
                and entry.available_at <= now
            ) or (
                entry.status == TemporalSignalOutboxStatus.DISPATCHING
                and entry.claimed_until is not None
                and entry.claimed_until <= now
            )
            if not ready or entry.attempt_count >= max_attempts:
                continue
            updated = replace(
                entry,
                status=TemporalSignalOutboxStatus.DISPATCHING,
                attempt_count=entry.attempt_count + 1,
                claimed_until=now + lease_duration,
                last_error=None,
                updated_at=now,
            )
            self.entries[key] = updated
            claimed.append(updated)
        return tuple(claimed)

    async def mark_sent(
        self,
        temporal_signal_id: UUID,
        *,
        now: datetime,
    ) -> TemporalSignalOutboxEntry:
        return self._replace_by_id(
            temporal_signal_id,
            status=TemporalSignalOutboxStatus.SENT,
            sent_at=now,
            claimed_until=None,
            available_at=now,
            last_error=None,
            updated_at=now,
        )

    async def mark_failed(
        self,
        temporal_signal_id: UUID,
        *,
        error: str,
        available_at: datetime,
        now: datetime,
    ) -> TemporalSignalOutboxEntry:
        return self._replace_by_id(
            temporal_signal_id,
            status=TemporalSignalOutboxStatus.FAILED,
            claimed_until=None,
            available_at=available_at,
            last_error=error,
            updated_at=now,
        )

    async def mark_terminal_failure(
        self,
        temporal_signal_id: UUID,
        *,
        error: str,
        now: datetime,
    ) -> TemporalSignalOutboxEntry:
        return self._replace_by_id(
            temporal_signal_id,
            status=TemporalSignalOutboxStatus.TERMINAL_FAILURE,
            claimed_until=None,
            available_at=now,
            last_error=error,
            updated_at=now,
        )

    def _replace_by_id(
        self,
        temporal_signal_id: UUID,
        **changes: object,
    ) -> TemporalSignalOutboxEntry:
        for key, entry in self.entries.items():
            if entry.temporal_signal_id == temporal_signal_id:
                updated = replace(entry, **cast(Any, changes))
                self.entries[key] = updated
                return updated
        raise KeyError(temporal_signal_id)
