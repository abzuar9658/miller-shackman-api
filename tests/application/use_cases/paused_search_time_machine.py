from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from uuid import UUID

from app.application.use_cases.campaign_cadence_execution import (
    CadenceStepExecutionResult,
    CadenceStepScheduleResult,
    execute_campaign_cadence_step,
    schedule_next_campaign_cadence_step,
)
from app.domain.campaigns import (
    CampaignStatus,
    CampaignVersionStatus,
    PausedSearchTrackStep,
    PausedSearchTrackVersion,
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.execution import CampaignExecutionConfig
from app.domain.campaigns.outbound_message import ProviderDeliveryStatus
from app.domain.compliance.contactability import WorkspaceContactPolicy
from app.domain.conversations import CrmConversationEvent
from app.domain.identity import Workspace, WorkspaceStatus
from app.domain.leads import CanonicalLeadRecord
from app.domain.workflows import LeadWorkflow
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCampaignExecutionRepository,
    FakeCrmConversationEventRepository,
    FakeEmailProvider,
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeLLMClient,
    FakeOutboundMessageRepository,
    FakePausedSearchAgentReminderRepository,
    FakeSMSProvider,
    FakeWorkflowTransitionRepository,
    FakeWorkspaceContactPolicyRepository,
    FakeWorkspaceRepository,
)
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
)


@dataclass(frozen=True)
class PausedSearchTimeMachineSnapshot:
    now: datetime
    workflow: LeadWorkflow
    schedule_statuses: tuple[str, ...]
    execution_statuses: tuple[str, ...]
    sent_channels: tuple[str, ...]
    occurrence_statuses: tuple[str, ...]
    occurrence_times: tuple[datetime, ...]
    reminder_count: int
    transition_count: int


class PausedSearchTimeMachineOccurrenceRepository:
    def __init__(self) -> None:
        self.occurrences: list[RecurringOccurrence] = []

    async def get_latest_for_step(
        self, workspace_id: UUID, workflow_id: UUID, track_version_id: UUID, step_id: UUID
    ) -> RecurringOccurrence | None:
        matches = [
            item
            for item in self.occurrences
            if item.workspace_id == workspace_id
            and item.workflow_id == workflow_id
            and item.track_version_id == track_version_id
            and item.step_id == step_id
        ]
        return max(matches, key=lambda item: item.occurrence_number, default=None)

    async def get_by_identity(
        self,
        workspace_id: UUID,
        workflow_id: UUID,
        track_version_id: UUID,
        step_id: UUID,
        occurrence_number: int,
        scheduled_for: datetime,
    ) -> RecurringOccurrence | None:
        return next(
            (
                item
                for item in self.occurrences
                if item.workspace_id == workspace_id
                and item.workflow_id == workflow_id
                and item.track_version_id == track_version_id
                and item.step_id == step_id
                and item.occurrence_number == occurrence_number
                and item.scheduled_for == scheduled_for
            ),
            None,
        )

    async def get_by_idempotency_key(
        self, workspace_id: UUID, idempotency_key: str
    ) -> RecurringOccurrence | None:
        return next(
            (
                item
                for item in self.occurrences
                if item.workspace_id == workspace_id and item.idempotency_key == idempotency_key
            ),
            None,
        )

    async def create_or_get(self, occurrence: RecurringOccurrence) -> RecurringOccurrence:
        existing = await self.get_by_idempotency_key(
            occurrence.workspace_id, occurrence.idempotency_key
        )
        if existing is not None:
            return existing
        self.occurrences.append(occurrence)
        return occurrence

    async def get_by_provider_message_id_for_update(
        self, workspace_id: UUID, provider_message_id: str
    ) -> RecurringOccurrence | None:
        return next(
            (
                item
                for item in self.occurrences
                if item.workspace_id == workspace_id
                and item.provider_message_id == provider_message_id
            ),
            None,
        )

    async def update_status(
        self,
        *,
        workspace_id: UUID,
        occurrence_id: UUID,
        status: str,
        now: datetime,
        provider_message_id: str | None = None,
        provider_delivery_status: ProviderDeliveryStatus | None = None,
        failure_reason: str | None = None,
        fallback_used: bool | None = None,
    ) -> RecurringOccurrence | None:
        for index, item in enumerate(self.occurrences):
            if item.workspace_id != workspace_id or item.occurrence_id != occurrence_id:
                continue
            updated = replace(
                item,
                status=RecurringOccurrenceStatus(status),
                logical_touch_count=item.logical_touch_count
                + int(
                    status == RecurringOccurrenceStatus.SENT.value
                    and item.status is not RecurringOccurrenceStatus.SENT
                ),
                provider_message_id=provider_message_id or item.provider_message_id,
                provider_delivery_status=provider_delivery_status or item.provider_delivery_status,
                failure_reason=failure_reason or item.failure_reason,
                fallback_used=fallback_used if fallback_used is not None else item.fallback_used,
                closed_at=(
                    now
                    if status != RecurringOccurrenceStatus.PLANNED.value
                    else item.closed_at
                ),
            )
            self.occurrences[index] = updated
            return updated
        return None

    async def cancel_open_for_workflow(
        self, *, workspace_id: UUID, workflow_id: UUID, now: datetime, reason: str
    ) -> int:
        open_statuses = {
            RecurringOccurrenceStatus.PLANNED,
            RecurringOccurrenceStatus.DEFERRED,
            RecurringOccurrenceStatus.REVIEW_REQUESTED,
            RecurringOccurrenceStatus.APPROVED,
        }
        count = 0
        for index, item in enumerate(self.occurrences):
            if (
                item.workspace_id == workspace_id
                and item.workflow_id == workflow_id
                and item.status in open_statuses
            ):
                self.occurrences[index] = replace(
                    item,
                    status=RecurringOccurrenceStatus.CANCELLED,
                    closed_at=now,
                    failure_reason=reason,
                )
                count += 1
        return count

    async def resolve_uncertain(self, **_: object) -> RecurringOccurrence | None:
        return None

    async def get_by_id(
        self, workspace_id: UUID, occurrence_id: UUID
    ) -> RecurringOccurrence | None:
        return next(
            (
                item
                for item in self.occurrences
                if item.workspace_id == workspace_id and item.occurrence_id == occurrence_id
            ),
            None,
        )

    async def get_by_id_for_update(
        self, workspace_id: UUID, occurrence_id: UUID
    ) -> RecurringOccurrence | None:
        return await self.get_by_id(workspace_id, occurrence_id)


class PausedSearchTimeMachine:
    def __init__(
        self,
        *,
        now: datetime,
        timezone: str,
        lead: CanonicalLeadRecord,
        workflow: LeadWorkflow,
        track_version: PausedSearchTrackVersion,
        steps: tuple[PausedSearchTrackStep, ...],
        email_result: str | Exception = "time-machine-email",
        sms_result: str | Exception = "time-machine-sms",
        contact_policy: WorkspaceContactPolicy | None = None,
        conversation_events: tuple[CrmConversationEvent, ...] = (),
    ) -> None:
        self.now = now
        self.timezone = timezone
        self.workspace_id = lead.workspace_id
        self.lead_id = lead.lead_id
        self.lead = lead
        self.campaign_version_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        self.workflow_repository = FakeLeadWorkflowRepository()
        self.lead_repository = FakeLeadRepository(lead)
        self.track_repository = FakePausedSearchTrackAdminRepository(
            versions=(track_version,), steps=steps
        )
        self.occurrence_repository = PausedSearchTimeMachineOccurrenceRepository()
        self.transition_repository = FakeWorkflowTransitionRepository()
        self.message_repository = FakeOutboundMessageRepository()
        self.crm_conversation_event_repository = FakeCrmConversationEventRepository(
            conversation_events
        )
        self.reminder_repository = FakePausedSearchAgentReminderRepository()
        self.email_provider = FakeEmailProvider(email_result)
        self.sms_provider = FakeSMSProvider(sms_result)
        self.config_repository = FakeCampaignExecutionRepository(self._config(track_version))
        self.track_version = track_version
        self.steps = steps
        self.workspace_repository = FakeWorkspaceRepository(
            Workspace(
                workspace_id=lead.workspace_id,
                name="Time Machine Brokerage",
                status=WorkspaceStatus.ACTIVE,
                default_timezone=timezone,
                created_at=now,
                updated_at=now,
            )
        )
        self.contact_policy_repository = FakeWorkspaceContactPolicyRepository(
            contact_policy
            or WorkspaceContactPolicy(
                workspace_id=lead.workspace_id,
                quiet_hours_start=time(10, 0),
                quiet_hours_end=time(17, 0),
            )
        )
        self.llm_client = FakeLLMClient()
        self.schedules: list[CadenceStepScheduleResult] = []
        self.executions: list[CadenceStepExecutionResult] = []
        self.workflow_repository.workflows[workflow.workflow_id] = workflow
        self.workflow_repository.latest_by_lead[
            (workflow.workspace_id, workflow.lead_id)
        ] = workflow

    async def schedule(self) -> CadenceStepScheduleResult:
        result = await schedule_next_campaign_cadence_step(
            workspace_id=self.workspace_id,
            lead_id=self.lead_id,
            campaign_version_id=self.campaign_version_id,
            campaign_execution_repository=self.config_repository,
            lead_workflow_repository=self.workflow_repository,
            lead_repository=self.lead_repository,
            paused_search_track_repository=self.track_repository,
            paused_search_occurrence_repository=self.occurrence_repository,
            now=self.now,
        )
        self.schedules.append(result)
        return result

    async def execute(self, scheduled: CadenceStepScheduleResult) -> CadenceStepExecutionResult:
        assert scheduled.cadence_step_id is not None
        assert scheduled.scheduled_for is not None
        result = await execute_campaign_cadence_step(
            workspace_id=self.workspace_id,
            lead_id=self.lead_id,
            campaign_version_id=self.campaign_version_id,
            cadence_step_id=scheduled.cadence_step_id,
            scheduled_for=scheduled.scheduled_for,
            campaign_execution_repository=self.config_repository,
            paused_search_track_repository=self.track_repository,
            paused_search_occurrence_repository=self.occurrence_repository,
            paused_search_reminder_repository=self.reminder_repository,
            workspace_repository=self.workspace_repository,
            workspace_contact_policy_repository=self.contact_policy_repository,
            lead_repository=self.lead_repository,
            lead_workflow_repository=self.workflow_repository,
            workflow_transition_repository=self.transition_repository,
            message_repository=self.message_repository,
            crm_conversation_event_repository=self.crm_conversation_event_repository,
            llm_client=self.llm_client,
            sms_provider=self.sms_provider,
            email_provider=self.email_provider,
            now=self.now,
        )
        self.executions.append(result)
        return result

    async def run_until_quiescent(self, *, max_steps: int = 16) -> None:
        for _ in range(max_steps):
            scheduled = await self.schedule()
            if scheduled.status.value != "scheduled" or scheduled.scheduled_for is None:
                if (
                    scheduled.status.value == "terminal"
                    and scheduled.skip_reason != "track logical-touch limit has been reached"
                    and self.lead.reengagement_not_before is not None
                ):
                    boundary = self.lead.reengagement_not_before - timedelta(
                        days=self.track_version.reactivation_window_days
                    )
                    if self.now < boundary:
                        self.now = boundary
                        continue
                return
            self.now = max(self.now, scheduled.scheduled_for)
            executed = await self.execute(scheduled)
            if executed.status.value not in {"sent", "already_sent", "skipped"}:
                return
            if not executed.has_more_steps:
                return
            if (
                executed.workflow is not None
                and executed.workflow.logical_touch_count < self.track_version.max_total_touches
                and self.lead.reengagement_not_before is not None
                and any(
                    occurrence.occurrence_number >= step.max_occurrences
                    and occurrence.step_id == step.step_id
                    and occurrence.status is RecurringOccurrenceStatus.SENT
                    for step in self.steps
                    for occurrence in self.occurrence_repository.occurrences
                )
            ):
                boundary = self.lead.reengagement_not_before - timedelta(
                    days=self.track_version.reactivation_window_days
                )
                if self.now < boundary:
                    self.now = boundary
        raise AssertionError("time-machine did not reach a quiescent state")

    def snapshot(self) -> PausedSearchTimeMachineSnapshot:
        workflow = self.workflow_repository.latest_by_lead[(self.workspace_id, self.lead_id)]
        sent_channels = tuple(
            message.channel.value
            for message in self.message_repository.saved
            if message.status.value in {"sent", "accepted"}
        )
        return PausedSearchTimeMachineSnapshot(
            now=self.now,
            workflow=workflow,
            schedule_statuses=tuple(result.status.value for result in self.schedules),
            execution_statuses=tuple(result.status.value for result in self.executions),
            sent_channels=sent_channels,
            occurrence_statuses=tuple(
                item.status.value for item in self.occurrence_repository.occurrences
            ),
            occurrence_times=tuple(
                item.scheduled_for for item in self.occurrence_repository.occurrences
            ),
            reminder_count=len(self.reminder_repository.reminders),
            transition_count=len(self.transition_repository.transitions),
        )

    def _config(self, version: PausedSearchTrackVersion) -> CampaignExecutionConfig:
        return CampaignExecutionConfig(
            campaign_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            campaign_version_id=self.campaign_version_id,
            workspace_id=self.workspace_id,
            campaign_name="Paused Search Time Machine",
            campaign_status=CampaignStatus.ACTIVE,
            version_status=CampaignVersionStatus.PUBLISHED,
            enabled_channels=version.allowed_channels,
            daily_start_cap=50,
            dormant_threshold_days=60,
            quiet_hours_start=time(10, 0),
            quiet_hours_end=time(17, 0),
            timezone=self.timezone,
            sms_compliance_required=True,
            preflight_digest_enabled=False,
            crm_enrollment_tag=None,
            prompt_version="time-machine",
            approved_model="openai/gpt-4o-mini",
            cadence_steps=(),
            created_at=self.now,
        )