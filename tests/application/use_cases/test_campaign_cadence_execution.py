from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from app.application.services.llm.outbound_query_extraction import (
    OUTBOUND_QUERY_EXTRACTION_PROMPT_VERSION,
)
from app.application.use_cases.campaign_cadence_execution import (
    CadenceStepExecutionResult,
    CadenceStepExecutionStatus,
    CadenceStepScheduleResult,
    CadenceStepScheduleStatus,
    _record_paused_search_occurrence_outcome,
    execute_campaign_cadence_step,
    schedule_next_campaign_cadence_step,
)
from app.application.use_cases.process_inbound_message_event import (
    InboundMessageEvent,
    ProcessInboundMessageEventStatus,
    process_inbound_message_event,
)
from app.application.use_cases.send_outbound_message import (
    SendOutboundMessageResult,
    SendOutboundMessageStatus,
)
from app.domain.campaigns import (
    CampaignStatus,
    CampaignVersionStatus,
    PausedSearchFallbackTimingPolicy,
    PausedSearchInterimContactPolicy,
    PausedSearchStepAction,
    PausedSearchTimingBasis,
    PausedSearchTrackMode,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.execution import CampaignCadenceStep, CampaignExecutionConfig
from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageStatus,
    ProviderDeliveryStatus,
)
from app.domain.campaigns.paused_search_occurrences import (
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SmsComplianceState,
    SuppressionType,
    WorkspaceContactPolicy,
)
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.identity import Workspace, WorkspaceStatus
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
    PausedSearchSource,
)
from app.domain.outbound_drafting import (
    WorkspaceOutboundDraftingConfig,
    default_workspace_outbound_drafting_config,
)
from app.domain.workflows import LeadWorkflow, WorkflowState, WorkflowTransitionReasonCode
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCampaignExecutionRepository,
    FakeCrmConversationEventRepository,
    FakeEmailProvider,
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeLLMClient,
    FakeOutboundMessageRepository,
    FakePausedSearchAgentReminderRepository,
    FakePausedSearchOccurrenceRepository,
    FakePausedSearchReviewRepository,
    FakeRejectedDraftReviewRepository,
    FakeSMSProvider,
    FakeWorkflowTransitionRepository,
    FakeWorkspaceContactPolicyRepository,
    FakeWorkspaceOutboundDraftingConfigRepository,
    FakeWorkspaceRepository,
)
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
)
from tests.application.use_cases.test_process_inbound_message_event import (
    FakeConversationRepository,
    FakeConversationSummaryRepository,
    FakeCRMClient,
    FakeExternalEventRepository,
    FakeHandoffRepository,
    FakeInboundMessageRepository,
    FakeOutboundMessageCRMCompletionRepository,
    FakeWorkspaceHandoffConfigRepository,
    _workspace_handoff_config_with_snapshot_fields,
)
from tests.application.use_cases.test_process_inbound_message_event import (
    FakeLLMClient as FakeInboundLLMClient,
)
from tests.application.use_cases.test_process_inbound_message_event import (
    _classification_json as _inbound_classification_json,
)

NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000003")
CAMPAIGN_VERSION_ID = UUID("00000000-0000-0000-0000-000000000004")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000005")
ENROLLMENT_ID = UUID("00000000-0000-0000-0000-000000000006")
STEP_ONE_ID = UUID("00000000-0000-0000-0000-000000000007")
STEP_TWO_ID = UUID("00000000-0000-0000-0000-000000000008")
PAUSED_SEARCH_TRACK_ID = UUID("00000000-0000-0000-0000-000000000009")
PAUSED_SEARCH_TRACK_VERSION_ID = UUID("00000000-0000-0000-0000-00000000000a")
PAUSED_SEARCH_STEP_ONE_ID = UUID("00000000-0000-0000-0000-00000000000b")
PAUSED_SEARCH_STEP_TWO_ID = UUID("00000000-0000-0000-0000-00000000000c")
PAUSED_SEARCH_STEP_THREE_ID = UUID("00000000-0000-0000-0000-00000000000d")


class _Phase4OccurrenceRepository:
    def __init__(self) -> None:
        self.occurrences: list[RecurringOccurrence] = []

    async def get_latest_for_step(
        self,
        workspace_id: UUID,
        workflow_id: UUID,
        track_version_id: UUID,
        step_id: UUID,
    ) -> RecurringOccurrence | None:
        matches = [
            occurrence
            for occurrence in self.occurrences
            if occurrence.workspace_id == workspace_id
            and occurrence.workflow_id == workflow_id
            and occurrence.track_version_id == track_version_id
            and occurrence.step_id == step_id
        ]
        return max(matches, key=lambda occurrence: occurrence.occurrence_number, default=None)

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
                occurrence
                for occurrence in self.occurrences
                if occurrence.workspace_id == workspace_id
                and occurrence.workflow_id == workflow_id
                and occurrence.track_version_id == track_version_id
                and occurrence.step_id == step_id
                and occurrence.occurrence_number == occurrence_number
                and occurrence.scheduled_for == scheduled_for
            ),
            None,
        )

    async def get_by_idempotency_key(
        self,
        workspace_id: UUID,
        idempotency_key: str,
    ) -> RecurringOccurrence | None:
        return next(
            (
                occurrence
                for occurrence in self.occurrences
                if occurrence.workspace_id == workspace_id
                and occurrence.idempotency_key == idempotency_key
            ),
            None,
        )

    async def create_or_get(self, occurrence: RecurringOccurrence) -> RecurringOccurrence:
        existing = await self.get_by_idempotency_key(
            occurrence.workspace_id,
            occurrence.idempotency_key,
        )
        if existing is not None:
            return existing
        self.occurrences.append(occurrence)
        return occurrence

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
        del provider_delivery_status
        for index, occurrence in enumerate(self.occurrences):
            if occurrence.workspace_id != workspace_id or occurrence.occurrence_id != occurrence_id:
                continue
            updated = replace(
                occurrence,
                status=RecurringOccurrenceStatus(status),
                logical_touch_count=(
                    occurrence.logical_touch_count
                    + int(
                        status == RecurringOccurrenceStatus.SENT.value
                        and occurrence.status != RecurringOccurrenceStatus.SENT
                    )
                ),
                provider_message_id=provider_message_id or occurrence.provider_message_id,
                failure_reason=failure_reason or occurrence.failure_reason,
                fallback_used=(
                    fallback_used if fallback_used is not None else occurrence.fallback_used
                ),
                closed_at=(
                    now
                    if status != RecurringOccurrenceStatus.PLANNED.value
                    else occurrence.closed_at
                ),
            )
            self.occurrences[index] = updated
            return updated
        return None

    async def get_by_provider_message_id_for_update(
        self,
        workspace_id: UUID,
        provider_message_id: str,
    ) -> RecurringOccurrence | None:
        return next(
            (
                occurrence
                for occurrence in self.occurrences
                if occurrence.workspace_id == workspace_id
                and occurrence.provider_message_id == provider_message_id
            ),
            None,
        )

    async def cancel_open_for_workflow(
        self,
        *,
        workspace_id: UUID,
        workflow_id: UUID,
        now: datetime,
        reason: str,
    ) -> int:
        count = 0
        for index, occurrence in enumerate(self.occurrences):
            if (
                occurrence.workspace_id != workspace_id
                or occurrence.workflow_id != workflow_id
                or occurrence.status
                not in {
                    RecurringOccurrenceStatus.PLANNED,
                    RecurringOccurrenceStatus.DEFERRED,
                    RecurringOccurrenceStatus.REVIEW_REQUESTED,
                    RecurringOccurrenceStatus.APPROVED,
                }
            ):
                continue
            self.occurrences[index] = replace(
                occurrence,
                status=RecurringOccurrenceStatus.CANCELLED,
                closed_at=now,
                failure_reason=reason,
            )
            count += 1
        return count

    async def resolve_uncertain(
        self,
        *,
        workspace_id: UUID,
        occurrence_id: UUID,
        status: str,
        now: datetime,
        reason: str,
    ) -> RecurringOccurrence | None:
        for index, occurrence in enumerate(self.occurrences):
            if (
                occurrence.workspace_id != workspace_id
                or occurrence.occurrence_id != occurrence_id
                or occurrence.status != RecurringOccurrenceStatus.UNCERTAIN
            ):
                continue
            updated = replace(
                occurrence,
                status=RecurringOccurrenceStatus(status),
                closed_at=now,
                failure_reason=reason,
            )
            self.occurrences[index] = updated
            return updated
        return None

    async def get_by_id_for_update(
        self,
        workspace_id: UUID,
        occurrence_id: UUID,
    ) -> RecurringOccurrence | None:
        return next(
            (
                occurrence
                for occurrence in self.occurrences
                if occurrence.workspace_id == workspace_id
                and occurrence.occurrence_id == occurrence_id
            ),
            None,
        )


def _crm_event(
    *,
    crm_activity_id: str,
    content: str,
    direction: CrmConversationEventDirection,
) -> CrmConversationEvent:
    return CrmConversationEvent(
        crm_conversation_event_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        crm_activity_id=crm_activity_id,
        activity_type="Note",
        direction=direction,
        occurred_at=NOW,
        content=content,
        created_at=NOW,
        updated_at=NOW,
    )


async def test_schedule_next_campaign_cadence_step_sets_due_time_and_current_step() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    await workflow_repository.save(_workflow())

    result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(outbound_drafting_config=_dormant_drafting_config())
        ),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )

    assert result.status == CadenceStepScheduleStatus.SCHEDULED
    assert result.cadence_step_id == STEP_ONE_ID
    assert result.scheduled_for == NOW + timedelta(hours=24)
    saved_workflow = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert saved_workflow.current_step_id == STEP_ONE_ID
    assert saved_workflow.next_action_at == NOW + timedelta(hours=24)


async def test_execute_campaign_cadence_step_sends_first_step_and_advances_cursor() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    llm_client = FakeLLMClient()
    await workflow_repository.save(_workflow())
    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )

    message_repository = FakeOutboundMessageRepository()
    email_provider = FakeEmailProvider("email-123")
    crm_client = FakeCRMClient()
    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ONE_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(outbound_drafting_config=_dormant_drafting_config())
        ),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=message_repository,
        crm_conversation_event_repository=FakeCrmConversationEventRepository(
            (
                _crm_event(
                    crm_activity_id="act-1",
                    content="Sent a check-in email last week.",
                    direction=CrmConversationEventDirection.OUTBOUND,
                ),
                _crm_event(
                    crm_activity_id="act-2",
                    content="We are hoping to move before school starts.",
                    direction=CrmConversationEventDirection.INBOUND,
                ),
            )
        ),
        llm_client=llm_client,
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        crm_client=crm_client,
        outbound_message_crm_completion_repository=FakeOutboundMessageCRMCompletionRepository(),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            _workspace_handoff_config_with_snapshot_fields()
        ),
        now=datetime(2026, 7, 10, 15, 0, tzinfo=UTC),
    )

    assert result.status == CadenceStepExecutionStatus.SENT
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.WAITING_FOR_RESPONSE
    assert result.workflow.current_step_id == STEP_TWO_ID
    assert result.workflow.next_action_at is None
    assert result.cadence_step_id == STEP_ONE_ID
    assert result.has_more_steps is True
    assert len(email_provider.messages) == 1
    assert message_repository.saved[-1].provider_message_id == "email-123"
    assert message_repository.saved[-1].status.value == "sent"
    assert len(crm_client.notes) == 1
    assert crm_client.note_subjects == ["AI OUTBOUND · EMAIL"]
    assert "AI OUTBOUND · EMAIL" in crm_client.notes[0]
    assert "Latest inbound:\nWe are hoping to move before school starts." in crm_client.notes[0]
    assert crm_client.custom_field_updates == [
        {
            "ai_summary": "Used safe canonical context.",
            "ai_status": "waiting_for_response",
            "ai_latest_inbound": "We are hoping to move before school starts.",
            "ai_latest_outbound": message_repository.saved[-1].body,
            "ai_last_activity_at": datetime(2026, 7, 10, 15, 0, tzinfo=UTC).isoformat(),
        }
    ]
    assert [
        transition.reason_code for transition in transition_repository.transitions.values()
    ] == [
        WorkflowTransitionReasonCode.CADENCE_STEP_STARTED,
        WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_SENT,
    ]
    draft_requests = _draft_requests(llm_client)
    assert len(draft_requests) == 1
    assert "Recent CRM conversation history:" in draft_requests[0].prompt
    assert "We are hoping to move before school starts." in draft_requests[0].prompt
    assert "Use the campaign version's dormant drafting voice." in draft_requests[0].prompt


async def test_schedule_next_campaign_cadence_step_schedules_second_step_after_first_send() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    await workflow_repository.save(_workflow())
    await _send_first_step(
        workflow_repository=workflow_repository,
        transition_repository=transition_repository,
    )

    result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(outbound_drafting_config=_dormant_drafting_config())
        ),
        lead_workflow_repository=workflow_repository,
        now=NOW + timedelta(days=1),
    )

    assert result.status == CadenceStepScheduleStatus.SCHEDULED
    assert result.cadence_step_id == STEP_TWO_ID
    assert result.scheduled_for == NOW + timedelta(days=1, hours=48)
    saved_workflow = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert saved_workflow.current_step_id == STEP_TWO_ID
    assert saved_workflow.next_action_at == NOW + timedelta(days=1, hours=48)


async def test_execute_campaign_cadence_step_skips_unreachable_email_step_and_keeps_sms_timing(
) -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    await workflow_repository.save(_workflow())
    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(channels=(ContactChannel.EMAIL, ContactChannel.SMS))
        ),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )

    email_provider = FakeEmailProvider("should-not-send")
    sms_provider = FakeSMSProvider("sms-after-skip")
    skipped = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ONE_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(channels=(ContactChannel.EMAIL, ContactChannel.SMS))
        ),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(_lead(has_email=False, has_phone=True)),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=sms_provider,
        email_provider=email_provider,
        now=datetime(2026, 7, 10, 15, 0, tzinfo=UTC),
    )

    assert skipped.status == CadenceStepExecutionStatus.SKIPPED
    assert skipped.workflow is not None
    assert skipped.workflow.current_step_id == STEP_TWO_ID
    assert skipped.workflow.next_action_at is None
    assert email_provider.messages == []
    assert sms_provider.messages == []

    second_schedule = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(channels=(ContactChannel.EMAIL, ContactChannel.SMS))
        ),
        lead_workflow_repository=workflow_repository,
        now=NOW + timedelta(days=1),
    )

    assert second_schedule.status == CadenceStepScheduleStatus.SCHEDULED
    assert second_schedule.cadence_step_id == STEP_TWO_ID
    assert second_schedule.scheduled_for == NOW + timedelta(days=3)

    sent = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_TWO_ID,
        scheduled_for=second_schedule.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(channels=(ContactChannel.EMAIL, ContactChannel.SMS))
        ),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(_lead(has_email=False, has_phone=True)),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=sms_provider,
        email_provider=email_provider,
        now=datetime(2026, 7, 12, 15, 0, tzinfo=UTC),
    )

    assert sent.status == CadenceStepExecutionStatus.SENT
    assert sent.workflow is not None
    assert sent.workflow.state == WorkflowState.WAITING_FOR_RESPONSE
    assert len(sms_provider.messages) == 1


async def test_schedule_next_campaign_cadence_step_uses_paused_search_track_cursor() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    await workflow_repository.save(_paused_search_workflow())

    result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        lead_repository=FakeLeadRepository(_paused_search_lead()),
        paused_search_track_repository=_paused_search_track_repository(),
        now=NOW,
    )

    assert result.status == CadenceStepScheduleStatus.SCHEDULED
    assert result.cadence_step_id == PAUSED_SEARCH_STEP_ONE_ID
    saved_workflow = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert saved_workflow.current_step_id is None
    assert saved_workflow.paused_search_track_step_id == PAUSED_SEARCH_STEP_ONE_ID
    assert saved_workflow.next_action_at == result.scheduled_for


async def test_schedule_next_campaign_cadence_step_does_not_fallback_to_dormant() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    await workflow_repository.save(_workflow())

    result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        lead_repository=FakeLeadRepository(_paused_search_lead()),
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        now=NOW,
    )

    assert result.status == CadenceStepScheduleStatus.NO_CADENCE_STEP
    assert result.skip_reason == "workflow has no pinned paused-search track version"
    saved_workflow = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert saved_workflow.current_step_id is None
    assert saved_workflow.next_action_at is None


async def test_execute_campaign_cadence_step_sends_paused_search_step_and_advances_cursor() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    send_now = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
    await workflow_repository.save(
        replace(
            _paused_search_workflow(),
            paused_search_track_step_id=PAUSED_SEARCH_STEP_ONE_ID,
            next_action_at=send_now,
        )
    )
    message_repository = FakeOutboundMessageRepository()
    llm_client = FakeLLMClient()
    email_provider = FakeEmailProvider("paused-email-1")
    occurrence_repository = FakePausedSearchOccurrenceRepository()

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=PAUSED_SEARCH_STEP_ONE_ID,
        scheduled_for=send_now,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        paused_search_track_repository=_paused_search_track_repository(),
        paused_search_occurrence_repository=occurrence_repository,
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        workspace_outbound_drafting_config_repository=(
            FakeWorkspaceOutboundDraftingConfigRepository(
                default_workspace_outbound_drafting_config(WORKSPACE_ID)
            )
        ),
        lead_repository=FakeLeadRepository(_paused_search_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=message_repository,
        llm_client=llm_client,
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=send_now,
    )

    assert result.status == CadenceStepExecutionStatus.SENT
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.WAITING_FOR_RESPONSE
    assert result.workflow.current_step_id is None
    assert result.workflow.paused_search_track_step_id == PAUSED_SEARCH_STEP_TWO_ID
    assert result.has_more_steps is True
    assert len(email_provider.messages) == 1
    assert message_repository.saved[-1].cadence_step_id == str(PAUSED_SEARCH_STEP_ONE_ID)
    assert message_repository.saved[-1].provider_message_id == "paused-email-1"
    assert occurrence_repository.occurrence is not None
    assert occurrence_repository.occurrence.status == RecurringOccurrenceStatus.SENT
    assert occurrence_repository.occurrence.logical_touch_count == 1
    assert workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)].logical_touch_count == 1
    assert message_repository.saved[-1].subject == "Still planning to wait on rates for now?"
    assert "Hi there," in message_repository.saved[-1].body
    assert "waiting on rates before reopening your search" in message_repository.saved[-1].body
    assert "just checking in." in message_repository.saved[-1].body
    draft_requests = _draft_requests(llm_client)
    assert len(draft_requests) == 1
    assert '"journey_kind": "paused_search"' in draft_requests[0].prompt
    assert "For paused-search outreach" in draft_requests[0].prompt
    assert "Use the campaign version's dormant drafting voice." not in draft_requests[0].prompt

    duplicate_result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=PAUSED_SEARCH_STEP_ONE_ID,
        scheduled_for=send_now,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        paused_search_track_repository=_paused_search_track_repository(),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        workspace_outbound_drafting_config_repository=(
            FakeWorkspaceOutboundDraftingConfigRepository(_dormant_drafting_config())
        ),
        lead_repository=FakeLeadRepository(_paused_search_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=message_repository,
        llm_client=llm_client,
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=send_now,
    )

    assert duplicate_result.status == CadenceStepExecutionStatus.SKIPPED
    assert len(email_provider.messages) == 1


async def test_execute_campaign_cadence_step_holds_review_required_message() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    send_now = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
    await workflow_repository.save(
        replace(
            _paused_search_workflow(),
            paused_search_track_step_id=PAUSED_SEARCH_STEP_ONE_ID,
            next_action_at=send_now,
        )
    )
    occurrence_repository = FakePausedSearchOccurrenceRepository()
    review_repository = FakePausedSearchReviewRepository()
    message_repository = FakeOutboundMessageRepository()
    email_provider = FakeEmailProvider("must-not-send")
    track_repository = FakePausedSearchTrackAdminRepository(
        versions=(_paused_search_track_version(),),
        steps=(replace(_paused_search_steps()[0], review_required=True),),
    )

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=PAUSED_SEARCH_STEP_ONE_ID,
        scheduled_for=send_now,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        paused_search_track_repository=track_repository,
        paused_search_occurrence_repository=occurrence_repository,
        paused_search_review_repository=review_repository,
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        workspace_outbound_drafting_config_repository=(
            FakeWorkspaceOutboundDraftingConfigRepository(
                default_workspace_outbound_drafting_config(WORKSPACE_ID)
            )
        ),
        lead_repository=FakeLeadRepository(_paused_search_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        message_repository=message_repository,
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=send_now,
    )

    assert result.status is CadenceStepExecutionStatus.REVIEW
    assert email_provider.messages == []
    assert occurrence_repository.occurrence is not None
    assert occurrence_repository.occurrence.status is RecurringOccurrenceStatus.REVIEW_REQUESTED
    assert len(review_repository.reviews) == 1
    review = next(iter(review_repository.reviews.values()))
    assert review.outbound_message_id == message_repository.saved[-1].message_id


async def test_execute_campaign_cadence_step_skips_explicit_skip_action_without_sending() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    send_now = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
    await workflow_repository.save(
        replace(
            _paused_search_workflow(),
            paused_search_track_step_id=PAUSED_SEARCH_STEP_ONE_ID,
            next_action_at=send_now,
        )
    )
    occurrence_repository = FakePausedSearchOccurrenceRepository()
    track_repository = FakePausedSearchTrackAdminRepository(
        versions=(_paused_search_track_version(),),
        steps=(replace(_paused_search_steps()[0], action=PausedSearchStepAction.SKIP),),
    )

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=PAUSED_SEARCH_STEP_ONE_ID,
        scheduled_for=send_now,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        paused_search_track_repository=track_repository,
        paused_search_occurrence_repository=occurrence_repository,
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(_paused_search_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider("should-not-send"),
        now=send_now,
    )

    assert result.status is CadenceStepExecutionStatus.SKIPPED
    assert result.skip_reason == "Paused-search step is configured to skip."
    assert occurrence_repository.updated[-1].status is RecurringOccurrenceStatus.SKIPPED


async def test_execute_campaign_cadence_step_creates_idempotent_reminder_instead_of_sending(
) -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    send_now = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
    await workflow_repository.save(
        replace(
            _paused_search_workflow(),
            paused_search_track_step_id=PAUSED_SEARCH_STEP_ONE_ID,
            next_action_at=send_now,
        )
    )
    occurrence_repository = FakePausedSearchOccurrenceRepository()
    reminder_repository = FakePausedSearchAgentReminderRepository()
    track_repository = FakePausedSearchTrackAdminRepository(
        versions=(_paused_search_track_version(),),
        steps=(replace(_paused_search_steps()[0], action=PausedSearchStepAction.REMINDER),),
    )
    email_provider = FakeEmailProvider("should-not-send")

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=PAUSED_SEARCH_STEP_ONE_ID,
        scheduled_for=send_now,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        paused_search_track_repository=track_repository,
        paused_search_occurrence_repository=occurrence_repository,
        paused_search_reminder_repository=reminder_repository,
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(_paused_search_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=send_now,
    )

    assert result.status is CadenceStepExecutionStatus.SKIPPED
    assert result.skip_reason == "Paused-search agent reminder created instead of sending."
    assert len(reminder_repository.reminders) == 1
    reminder = next(iter(reminder_repository.reminders.values()))
    assert reminder.body == _paused_search_steps()[0].message_goal
    assert occurrence_repository.updated[-1].status is RecurringOccurrenceStatus.REMINDER_CREATED
    assert email_provider.messages == []


async def test_paused_search_occurrence_outcome_updates_status_and_touch_once() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    workflow = _paused_search_workflow()
    await workflow_repository.save(workflow)
    occurrence = RecurringOccurrence(
        occurrence_id=UUID("00000000-0000-0000-0000-00000000000e"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        track_version_id=PAUSED_SEARCH_TRACK_VERSION_ID,
        step_id=PAUSED_SEARCH_STEP_ONE_ID,
        phase=PausedSearchTrackStepPhase.MAINTENANCE,
        occurrence_number=1,
        scheduled_for=NOW,
        due_at=NOW,
        status=RecurringOccurrenceStatus.PLANNED,
        idempotency_key="occurrence-test",
        created_at=NOW,
    )
    occurrence_repository = FakePausedSearchOccurrenceRepository(occurrence)

    updated_workflow = await _record_paused_search_occurrence_outcome(
        workspace_id=WORKSPACE_ID,
        workflow=workflow,
        occurrence=occurrence,
        authored_channel=ContactChannel.SMS,
        send_result=SendOutboundMessageResult(status=SendOutboundMessageStatus.SENT),
        occurrence_repository=occurrence_repository,
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )

    assert updated_workflow.logical_touch_count == 1
    assert occurrence_repository.occurrence is not None
    assert occurrence_repository.occurrence.status == RecurringOccurrenceStatus.SENT
    assert occurrence_repository.occurrence.logical_touch_count == 1

    duplicate_workflow = await _record_paused_search_occurrence_outcome(
        workspace_id=WORKSPACE_ID,
        workflow=updated_workflow,
        occurrence=occurrence_repository.occurrence,
        authored_channel=ContactChannel.SMS,
        send_result=SendOutboundMessageResult(status=SendOutboundMessageStatus.ALREADY_SENT),
        occurrence_repository=occurrence_repository,
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )
    assert duplicate_workflow.logical_touch_count == 1


async def test_execute_campaign_cadence_step_skips_paused_search_email_step_until_sms_step() -> (
    None
):
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    send_now = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
    await workflow_repository.save(
        replace(
            _paused_search_workflow(),
            paused_search_track_step_id=PAUSED_SEARCH_STEP_ONE_ID,
            next_action_at=send_now,
        )
    )
    message_repository = FakeOutboundMessageRepository()
    llm_client = FakeLLMClient()
    paused_search_repository = FakePausedSearchTrackAdminRepository(
        versions=(
            replace(
                _paused_search_track_version(),
                allowed_channels=(ContactChannel.EMAIL, ContactChannel.SMS),
            ),
        ),
        steps=(
            _paused_search_step(
                step_id=PAUSED_SEARCH_STEP_ONE_ID,
                step_order=1,
                delay_hours=0,
                message_goal="Check whether the lead's paused search timing has changed.",
                template_key="paused-search-maintenance-email-1",
            ),
            replace(
                _paused_search_step(
                    step_id=PAUSED_SEARCH_STEP_TWO_ID,
                    step_order=2,
                    delay_hours=24,
                    message_goal="Follow up once more on the paused search timing.",
                    template_key="paused-search-maintenance-sms-1",
                ),
                channel=ContactChannel.SMS,
            ),
        ),
    )
    sms_provider = FakeSMSProvider("paused-sms-1")
    email_provider = FakeEmailProvider("should-not-send")

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=PAUSED_SEARCH_STEP_ONE_ID,
        scheduled_for=send_now,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        paused_search_track_repository=paused_search_repository,
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(_paused_search_lead(has_email=False, has_phone=True)),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=message_repository,
        llm_client=llm_client,
        sms_provider=sms_provider,
        email_provider=email_provider,
        now=send_now,
    )

    assert result.status == CadenceStepExecutionStatus.SKIPPED
    assert result.workflow is not None
    assert result.workflow.paused_search_track_step_id == PAUSED_SEARCH_STEP_TWO_ID
    assert email_provider.messages == []
    assert sms_provider.messages == []
    assert message_repository.saved == []


async def test_phase4_paused_search_lifecycle_is_bounded_and_sequential() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    occurrence_repository = _Phase4OccurrenceRepository()
    message_repository = FakeOutboundMessageRepository()
    email_provider = FakeEmailProvider("phase4-email")
    sms_provider = FakeSMSProvider("phase4-sms")
    track_repository = FakePausedSearchTrackAdminRepository(
        versions=(
            replace(
                _paused_search_track_version(),
                allowed_channels=(ContactChannel.EMAIL, ContactChannel.SMS),
                maintenance_interval_days=30,
                reactivation_window_days=30,
                max_total_touches=4,
                track_mode=PausedSearchTrackMode.PERMISSION_BASED_INTERIM_CONTACT,
                interim_contact_policy=(
                    PausedSearchInterimContactPolicy.REQUIRES_EXPLICIT_LEAD_PERMISSION
                ),
            ),
        ),
        steps=(
            replace(
                _paused_search_step(
                    step_id=PAUSED_SEARCH_STEP_ONE_ID,
                    step_order=1,
                    delay_hours=0,
                    message_goal="Initial paused-search check-in.",
                    template_key="phase4-maintenance-email-1",
                ),
                interval_days=30,
                max_occurrences=2,
                timing_basis=PausedSearchTimingBasis.PREVIOUS_OCCURRENCE,
            ),
            replace(
                _paused_search_step(
                    step_id=PAUSED_SEARCH_STEP_TWO_ID,
                    step_order=2,
                    delay_hours=0,
                    message_goal="Reactivation email after the paused search boundary.",
                    template_key="phase4-reactivation-email",
                    phase=PausedSearchTrackStepPhase.REACTIVATION,
                ),
                timing_basis=PausedSearchTimingBasis.CUSTOMER_REENGAGEMENT_DATE,
            ),
            replace(
                _paused_search_step(
                    step_id=PAUSED_SEARCH_STEP_THREE_ID,
                    step_order=3,
                    delay_hours=24,
                    message_goal="Sequential reactivation SMS.",
                    template_key="phase4-reactivation-sms",
                    phase=PausedSearchTrackStepPhase.REACTIVATION,
                ),
                channel=ContactChannel.SMS,
                timing_basis=PausedSearchTimingBasis.CUSTOMER_REENGAGEMENT_DATE,
            ),
        ),
    )
    lead_repository = FakeLeadRepository(
        replace(
            _paused_search_lead(has_email=True, has_phone=True),
            reengagement_not_before=datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
        )
    )
    await workflow_repository.save(_paused_search_workflow())

    async def schedule(now: datetime) -> CadenceStepScheduleResult:
        return await schedule_next_campaign_cadence_step(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
            campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
            lead_workflow_repository=workflow_repository,
            lead_repository=lead_repository,
            paused_search_track_repository=track_repository,
            paused_search_occurrence_repository=occurrence_repository,
            now=now,
        )

    async def execute(
        result: CadenceStepScheduleResult,
        now: datetime,
    ) -> CadenceStepExecutionResult:
        assert result.cadence_step_id is not None
        assert result.scheduled_for is not None
        return await execute_campaign_cadence_step(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
            cadence_step_id=result.cadence_step_id,
            scheduled_for=result.scheduled_for,
            campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
            paused_search_track_repository=track_repository,
            paused_search_occurrence_repository=occurrence_repository,
            workspace_repository=FakeWorkspaceRepository(_workspace()),
            workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
                _workspace_contact_policy()
            ),
            lead_repository=lead_repository,
            lead_workflow_repository=workflow_repository,
            workflow_transition_repository=transition_repository,
            message_repository=message_repository,
            llm_client=FakeLLMClient(),
            sms_provider=sms_provider,
            email_provider=email_provider,
            now=now,
        )

    first_now = datetime(2026, 7, 9, 15, 0, tzinfo=UTC)
    first_schedule = await schedule(first_now)
    assert first_schedule.cadence_step_id == PAUSED_SEARCH_STEP_ONE_ID
    first_send = await execute(first_schedule, first_now)
    assert first_send.status is CadenceStepExecutionStatus.SENT
    assert first_send.workflow is not None
    assert first_send.workflow.state is WorkflowState.WAITING_FOR_RESPONSE
    assert first_send.workflow.logical_touch_count == 1

    second_now = datetime(2026, 8, 8, 15, 0, tzinfo=UTC)
    second_schedule = await schedule(second_now)
    assert second_schedule.cadence_step_id == PAUSED_SEARCH_STEP_ONE_ID
    second_send = await execute(second_schedule, second_now)
    assert second_send.status is CadenceStepExecutionStatus.SENT
    assert second_send.workflow is not None
    assert second_send.workflow.logical_touch_count == 2

    reactivation_now = datetime(2026, 8, 31, 15, 0, tzinfo=UTC)
    reactivation_schedule = await schedule(reactivation_now)
    assert reactivation_schedule.cadence_step_id == PAUSED_SEARCH_STEP_TWO_ID
    reactivation_email = await execute(
        reactivation_schedule,
        reactivation_now,
    )
    assert reactivation_email.status is CadenceStepExecutionStatus.SENT
    assert reactivation_email.workflow is not None
    assert reactivation_email.workflow.paused_search_track_step_id == PAUSED_SEARCH_STEP_THREE_ID
    assert reactivation_email.workflow.logical_touch_count == 3

    sms_schedule = await schedule(reactivation_now)
    assert sms_schedule.cadence_step_id == PAUSED_SEARCH_STEP_THREE_ID
    sms_now = datetime(2026, 9, 3, 15, 0, tzinfo=UTC)
    reactivation_sms = await execute(sms_schedule, sms_now)
    assert reactivation_sms.status is CadenceStepExecutionStatus.SENT
    assert reactivation_sms.workflow is not None
    assert reactivation_sms.workflow.state is WorkflowState.WAITING_FOR_RESPONSE
    assert reactivation_sms.workflow.paused_search_track_step_id is None
    assert reactivation_sms.workflow.next_action_at is None
    assert reactivation_sms.workflow.logical_touch_count == 4
    assert reactivation_sms.has_more_steps is False

    final_schedule = await schedule(datetime(2026, 9, 4, 15, 0, tzinfo=UTC))
    assert final_schedule.status is CadenceStepScheduleStatus.NO_CADENCE_STEP
    assert final_schedule.skip_reason == "Workflow has no remaining cadence steps."
    assert len(email_provider.messages) == 3
    assert len(sms_provider.messages) == 1
    assert [occurrence.status for occurrence in occurrence_repository.occurrences] == [
        RecurringOccurrenceStatus.SENT,
        RecurringOccurrenceStatus.SENT,
        RecurringOccurrenceStatus.SENT,
        RecurringOccurrenceStatus.SENT,
    ]
    assert [occurrence.logical_touch_count for occurrence in occurrence_repository.occurrences] == [
        1,
        1,
        1,
        1,
    ]


async def test_execute_campaign_cadence_step_skips_unpinned_paused_search_lead() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    await workflow_repository.save(
        replace(
            _workflow(),
            current_step_id=STEP_ONE_ID,
            next_action_at=NOW,
        )
    )

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ONE_ID,
        scheduled_for=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(_paused_search_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider("should-not-send"),
        now=NOW,
    )

    assert result.status == CadenceStepExecutionStatus.NO_CADENCE_STEP
    assert result.skip_reason is not None
    assert "no pinned paused-search track" in result.skip_reason


async def test_execute_campaign_cadence_step_blocks_suppressed_paused_search_lead() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    send_now = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
    await workflow_repository.save(
        replace(
            _paused_search_workflow(),
            paused_search_track_step_id=PAUSED_SEARCH_STEP_ONE_ID,
            next_action_at=send_now,
        )
    )

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=PAUSED_SEARCH_STEP_ONE_ID,
        scheduled_for=send_now,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        paused_search_track_repository=_paused_search_track_repository(),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(replace(_paused_search_lead(), do_not_contact=True)),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider("should-not-send"),
        now=send_now,
    )

    assert result.status == CadenceStepExecutionStatus.REJECTED
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.PAUSED
    assert result.workflow.next_action_at is None
    last_transition = list(transition_repository.transitions.values())[-1]
    assert last_transition.reason_code == WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED
    assert last_transition.metadata["block_stage"] == "planning"


async def test_execute_campaign_cadence_step_blocks_paused_search_when_email_is_unsubscribed() -> (
    None
):
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    send_now = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
    await workflow_repository.save(
        replace(
            _paused_search_workflow(),
            paused_search_track_step_id=PAUSED_SEARCH_STEP_ONE_ID,
            next_action_at=send_now,
        )
    )
    email_provider = FakeEmailProvider("should-not-send")

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=PAUSED_SEARCH_STEP_ONE_ID,
        scheduled_for=send_now,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        paused_search_track_repository=_paused_search_track_repository(),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(
            replace(
                _paused_search_lead(),
                suppression_types=frozenset({SuppressionType.EMAIL_UNSUBSCRIBED}),
                email_unsubscribed=True,
            )
        ),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=send_now,
    )

    assert result.status == CadenceStepExecutionStatus.REJECTED
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.PAUSED
    assert email_provider.messages == []
    last_transition = list(transition_repository.transitions.values())[-1]
    assert last_transition.reason_code == WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED
    assert last_transition.metadata["reason_codes"] == ["channel_not_contactable"]
    assert last_transition.metadata["channel_block_outcomes"] == ["not_contactable"]


async def test_execute_campaign_cadence_step_skips_paused_search_step_when_reengagement_moves_later(
) -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    send_now = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
    await workflow_repository.save(
        replace(
            _paused_search_workflow(),
            paused_search_track_step_id=PAUSED_SEARCH_STEP_TWO_ID,
            next_action_at=send_now,
        )
    )
    lead = replace(
        _paused_search_lead(),
        reengagement_not_before=send_now + timedelta(days=90),
    )
    paused_search_repository = FakePausedSearchTrackAdminRepository(
        versions=(_paused_search_track_version(),),
        steps=(
            _paused_search_step(
                step_id=PAUSED_SEARCH_STEP_ONE_ID,
                step_order=1,
                delay_hours=0,
                message_goal="Maintenance follow-up while the lead keeps waiting.",
            ),
            _paused_search_step(
                step_id=PAUSED_SEARCH_STEP_TWO_ID,
                step_order=2,
                delay_hours=0,
                message_goal="Reactivation follow-up once the lead is near return.",
                phase=PausedSearchTrackStepPhase.REACTIVATION,
            ),
        ),
    )
    email_provider = FakeEmailProvider("should-not-send")

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=PAUSED_SEARCH_STEP_TWO_ID,
        scheduled_for=send_now,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        paused_search_track_repository=paused_search_repository,
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(lead),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=send_now,
    )

    assert result.status == CadenceStepExecutionStatus.SKIPPED
    assert result.workflow is not None
    assert result.workflow.next_action_at == send_now
    assert result.workflow.paused_search_track_step_id == PAUSED_SEARCH_STEP_ONE_ID
    assert email_provider.messages == []


async def test_execute_campaign_cadence_step_skips_paused_search_step_when_profile_is_inactive(
) -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    send_now = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
    await workflow_repository.save(
        replace(
            _paused_search_workflow(),
            paused_search_track_step_id=PAUSED_SEARCH_STEP_ONE_ID,
            next_action_at=send_now,
        )
    )
    email_provider = FakeEmailProvider("should-not-send")

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=PAUSED_SEARCH_STEP_ONE_ID,
        scheduled_for=send_now,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        paused_search_track_repository=_paused_search_track_repository(),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(
            replace(_paused_search_lead(), paused_search_active=False)
        ),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=send_now,
    )

    assert result.status == CadenceStepExecutionStatus.NO_CADENCE_STEP
    assert result.workflow is not None
    assert result.workflow.next_action_at is None
    assert result.workflow.paused_search_track_step_id is None
    assert email_provider.messages == []


async def test_execute_campaign_cadence_step_sends_final_step_without_advancing_cursor() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    await workflow_repository.save(_workflow())
    await _send_first_step(
        workflow_repository=workflow_repository,
        transition_repository=transition_repository,
    )
    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW + timedelta(days=1),
    )

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_TWO_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider("email-456"),
        now=datetime(2026, 7, 12, 15, 0, tzinfo=UTC),
    )

    assert result.status == CadenceStepExecutionStatus.SENT
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.WAITING_FOR_RESPONSE
    assert result.workflow.current_step_id is None
    assert result.workflow.next_action_at is None
    assert result.has_more_steps is False

    final_schedule = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW + timedelta(days=3),
    )

    assert final_schedule.status == CadenceStepScheduleStatus.NO_CADENCE_STEP
    assert final_schedule.skip_reason == "Workflow has no remaining cadence steps."


async def test_execute_campaign_cadence_step_pauses_when_planning_is_blocked() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    await workflow_repository.save(_workflow())
    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )

    email_provider = FakeEmailProvider("email-123")
    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ONE_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(_lead(has_email=False, has_phone=False)),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=datetime(2026, 7, 10, 15, 0, tzinfo=UTC),
    )

    assert result.status == CadenceStepExecutionStatus.REJECTED
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.PAUSED
    assert result.workflow.current_step_id == STEP_ONE_ID
    assert result.workflow.next_action_at is None
    assert email_provider.messages == []
    last_transition = list(transition_repository.transitions.values())[-1]
    assert last_transition.reason_code == (WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED)
    assert last_transition.metadata["block_stage"] == "planning"
    assert last_transition.metadata["reason_codes"] == ["no_enabled_channels"]
    explanation = cast(str, last_transition.metadata["explanation"])
    assert explanation == "Planning blocked: no contact information found."


async def test_execute_campaign_cadence_step_retries_failed_outbound_with_new_version() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    message_repository = FakeOutboundMessageRepository()
    send_now = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
    await workflow_repository.save(
        replace(
            _workflow(),
            state=WorkflowState.ACTIVE_NURTURE,
            current_step_id=STEP_ONE_ID,
            next_action_at=send_now,
        )
    )
    await message_repository.save(
        OutboundMessage(
            message_id=UUID("00000000-0000-0000-0000-000000000099"),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            campaign_id=CAMPAIGN_ID,
            cadence_step_id=str(STEP_ONE_ID),
            channel=ContactChannel.EMAIL,
            status=OutboundMessageStatus.FAILED,
            idempotency_key=(
                f"outbound:{WORKSPACE_ID}:{CAMPAIGN_ID}:{LEAD_ID}:{STEP_ONE_ID}:email:v1"
            ),
            body="Failed first attempt",
            subject="Quick check-in",
            created_at=NOW,
            updated_at=NOW,
            planned_at=NOW,
            scheduled_for=send_now,
            message_version=1,
            provider_send_status=ProviderSendStatus.NOT_ATTEMPTED,
            provider_name="mailgun",
            failure_reason="HTTP 400",
        )
    )

    email_provider = FakeEmailProvider("email-456")
    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ONE_ID,
        scheduled_for=send_now,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=message_repository,
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=send_now,
    )

    assert result.status == CadenceStepExecutionStatus.SENT
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.WAITING_FOR_RESPONSE
    assert len(email_provider.messages) == 1
    assert email_provider.messages[0].idempotency_key.endswith(":email:v2")
    assert message_repository.saved[-1].message_version == 2
    assert message_repository.saved[-1].status == OutboundMessageStatus.SENT
    assert message_repository.saved[-1].provider_message_id == "email-456"


async def test_execute_campaign_cadence_step_persists_rich_draft_rejection_details() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    review_repository = FakeRejectedDraftReviewRepository()
    await workflow_repository.save(_workflow())
    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ONE_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        rejected_draft_review_repository=review_repository,
        llm_client=FakeLLMClient(
            safety_flags=("property_advice_requested", "tour_request_detected"),
        ),
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider(),
        now=datetime(2026, 7, 10, 15, 0, tzinfo=UTC),
    )

    assert result.status == CadenceStepExecutionStatus.REJECTED
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.PAUSED
    last_transition = list(transition_repository.transitions.values())[-1]
    assert last_transition.reason_code == (WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED)
    assert last_transition.metadata["block_stage"] == "planning"
    assert last_transition.metadata["reason_codes"] == ["draft_rejected"]
    assert last_transition.metadata["draft_reasons"] == ["safety_flags_present"]
    assert last_transition.metadata["draft_safety_flags"] == [
        "property_advice_requested",
        "tour_request_detected",
    ]
    assert last_transition.metadata["draft_confidence"] == 0.91
    assert last_transition.metadata["draft_model"] == "openai/gpt-4o-mini"
    assert last_transition.metadata["draft_prompt_version"] == "outbound_message_draft:v10:r3"
    assert last_transition.metadata["selected_channel"] == "email"
    explanation = cast(str, last_transition.metadata["explanation"])
    assert "Draft validation failed: safety flags present." in explanation
    assert "Safety flags: property advice requested, tour request detected." in explanation
    assert len(review_repository.saved) == 1
    assert (
        review_repository.saved[0].draft_body
        == "Hi there,\n\njust checking in.\n\nBest,\nMiller Schackman"
    )
    assert review_repository.saved[0].review_blockers == ("safety_flags_present",)
    assert review_repository.saved[0].can_approve_send is False


async def test_execute_campaign_cadence_step_respects_authored_sms_step_when_both_channels_exist(
) -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    await workflow_repository.save(_workflow())
    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(channels=(ContactChannel.SMS,))
        ),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )
    sms_provider = FakeSMSProvider()
    email_provider = FakeEmailProvider()
    message_repository = FakeOutboundMessageRepository()

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ONE_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(channels=(ContactChannel.SMS,))
        ),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy(sms_compliance_state=SmsComplianceState.NOT_APPROVED)
        ),
        lead_repository=FakeLeadRepository(_lead(has_phone=True)),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=message_repository,
        llm_client=FakeLLMClient(),
        sms_provider=sms_provider,
        email_provider=email_provider,
        now=datetime(2026, 7, 10, 15, 0, tzinfo=UTC),
    )

    assert result.status == CadenceStepExecutionStatus.SENT
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.WAITING_FOR_RESPONSE
    assert len(sms_provider.messages) == 1
    assert email_provider.messages == []
    assert message_repository.saved[-1].status == OutboundMessageStatus.SENT
    assert message_repository.saved[-1].channel == ContactChannel.SMS


async def test_execute_campaign_cadence_step_respects_persisted_quiet_hours() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    await workflow_repository.save(_workflow())
    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ONE_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy(
                quiet_hours_start=time(10, 0),
                quiet_hours_end=time(17, 0),
            )
        ),
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider(),
        now=datetime(2026, 7, 10, 13, 0, tzinfo=UTC),
    )

    assert result.status == CadenceStepExecutionStatus.REJECTED
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.PAUSED
    last_transition = list(transition_repository.transitions.values())[-1]
    assert last_transition.metadata["block_stage"] == "planning"
    assert last_transition.metadata["reason_codes"] == ["pre_send_blocked"]
    assert last_transition.metadata["evaluated_channels"] == ["email"]
    assert last_transition.metadata["channel_block_outcomes"] == ["pre_send_blocked"]
    assert last_transition.metadata["pre_send_reasons"] == ["outside_allowed_hours"]
    assert last_transition.metadata["next_allowed_at"] == "2026-07-10T15:00:00+00:00"


async def test_execute_campaign_cadence_step_ignores_quiet_hour_window_when_disabled() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    await workflow_repository.save(_workflow())
    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ONE_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy(
                quiet_hours_enabled=False,
                quiet_hours_start=time(10, 0),
                quiet_hours_end=time(17, 0),
            )
        ),
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider(),
        now=datetime(2026, 7, 10, 13, 0, tzinfo=UTC),
    )

    assert result.status == CadenceStepExecutionStatus.SENT
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.WAITING_FOR_RESPONSE


async def test_execute_campaign_cadence_step_rejects_when_inbound_opt_out_arrives_before_send() -> (
    None
):
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    lead_repository = FakeLeadRepository(_lead())
    await workflow_repository.save(_workflow())
    await _send_first_step(
        workflow_repository=workflow_repository,
        transition_repository=transition_repository,
    )

    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW + timedelta(days=1),
    )
    assert schedule_result.status == CadenceStepScheduleStatus.SCHEDULED

    inbound_result = await process_inbound_message_event(
        event=InboundMessageEvent(
            workspace_id=WORKSPACE_ID,
            provider=CRMProvider.FOLLOW_UP_BOSS.value,
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            provider_event_id="evt-inbound-before-step-two",
            provider_message_id="msg-inbound-before-step-two",
            crm_lead_id="123",
            channel=ContactChannel.EMAIL,
            body="Please unsubscribe me from future emails.",
            received_at=NOW + timedelta(hours=12),
            payload_redacted={"event": "redacted"},
        ),
        lead_repository=lead_repository,
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeInboundLLMClient(
            _inbound_classification_json(
                intent="opt_out",
                opt_out_detected=True,
                summary_text="Lead opted out of automated outreach.",
            )
        ),
        now=NOW + timedelta(hours=12),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
    )

    assert inbound_result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert inbound_result.opt_out_detected is True

    email_provider = FakeEmailProvider("email-456")
    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_TWO_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy(
                quiet_hours_start=time(10, 0),
                quiet_hours_end=time(17, 0),
            )
        ),
        lead_repository=lead_repository,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=schedule_result.scheduled_for or NOW,
    )

    assert result.status == CadenceStepExecutionStatus.SKIPPED
    assert email_provider.messages == []
    final_workflow = await workflow_repository.get_latest_for_lead(WORKSPACE_ID, LEAD_ID)
    assert final_workflow is not None
    assert final_workflow.state == WorkflowState.SUPPRESSED
    assert final_workflow.current_step_id is None
    assert final_workflow.pause_reason == "opt_out_detected"


async def _send_first_step(
    *,
    workflow_repository: FakeLeadWorkflowRepository,
    transition_repository: FakeWorkflowTransitionRepository,
) -> None:
    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )
    await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ONE_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider("email-123"),
        now=datetime(2026, 7, 10, 15, 0, tzinfo=UTC),
    )


def _workflow() -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture:test",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=WorkflowState.QUEUED,
        current_step_id=None,
        next_action_at=None,
        last_transition_at=NOW,
        pause_reason=None,
        resume_reason=None,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _paused_search_workflow() -> LeadWorkflow:
    return replace(
        _workflow(),
        state=WorkflowState.ACTIVE_NURTURE,
        current_step_id=None,
        next_action_at=None,
        paused_search_track_version_id=PAUSED_SEARCH_TRACK_VERSION_ID,
        paused_search_track_step_id=None,
    )


def _workspace() -> Workspace:
    return Workspace(
        workspace_id=WORKSPACE_ID,
        name="Miller Schackman",
        status=WorkspaceStatus.ACTIVE,
        default_timezone="America/Chicago",
        created_at=NOW,
        updated_at=NOW,
    )


def _workspace_contact_policy(
    *,
    sms_compliance_state: SmsComplianceState = SmsComplianceState.APPROVED,
    quiet_hours_enabled: bool = True,
    quiet_hours_start: time = time(10, 0),
    quiet_hours_end: time = time(17, 0),
) -> WorkspaceContactPolicy:
    return WorkspaceContactPolicy(
        workspace_id=WORKSPACE_ID,
        sms_compliance_state=sms_compliance_state,
        quiet_hours_enabled=quiet_hours_enabled,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
    )


def _lead(*, has_email: bool = True, has_phone: bool = False) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="long_term_nurture",
        mapped_custom_fields={"assigned_agent_name": "Alex Agent"},
        primary_email="lead@example.com" if has_email else None,
        has_email=has_email,
        email_count=1 if has_email else 0,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        primary_phone="+15551234567" if has_phone else None,
        has_phone=has_phone,
        has_sms_capable_phone=has_phone,
        phone_count=1 if has_phone else 0,
        sms_permission_status=ContactPermissionStatus.CONFIRMED,
        do_not_contact=False,
    )


def _paused_search_lead(
    *,
    has_email: bool = True,
    has_phone: bool = False,
) -> CanonicalLeadRecord:
    return replace(
        _lead(has_email=has_email, has_phone=has_phone),
        paused_search_active=True,
        paused_search_track_key="waiting-for-rates",
        paused_search_track_version_id=PAUSED_SEARCH_TRACK_VERSION_ID,
        pause_reason_note="Waiting for mortgage rates to improve.",
        reengagement_not_before=NOW + timedelta(days=90),
        reengagement_window_label="fall check-in",
        paused_search_source=PausedSearchSource.AI_CONVERSATION_CLASSIFICATION,
        paused_search_recorded_at=NOW,
        paused_search_last_confirmed_at=NOW,
    )


def _config(
    *,
    channels: tuple[ContactChannel, ...] = (ContactChannel.EMAIL,),
    outbound_drafting_config: WorkspaceOutboundDraftingConfig | None = None,
) -> CampaignExecutionConfig:
    return CampaignExecutionConfig(
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        workspace_id=WORKSPACE_ID,
        campaign_name="Dormant Buyers",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=channels,
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="America/Chicago",
        sms_compliance_required=True,
        preflight_digest_enabled=False,
        crm_enrollment_tag=None,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=_steps(channels=channels),
        created_at=NOW,
        published_at=NOW,
        outbound_drafting_config=outbound_drafting_config or _dormant_drafting_config(),
    )


def _dormant_drafting_config() -> WorkspaceOutboundDraftingConfig:
    return WorkspaceOutboundDraftingConfig(
        workspace_id=WORKSPACE_ID,
        revision=3,
        prompt_text="Use the campaign version's dormant drafting voice.",
        enabled_extraction_fields=("location", "max_price"),
    )


def _steps(
    *,
    channels: tuple[ContactChannel, ...],
) -> tuple[CampaignCadenceStep, ...]:
    first_channel = channels[0]
    second_channel = channels[-1]
    return (
        _step(
            cadence_step_id=STEP_ONE_ID,
            step_order=1,
            channel=first_channel,
            delay_hours=24,
            template_key="dormant-step-1",
        ),
        _step(
            cadence_step_id=STEP_TWO_ID,
            step_order=2,
            channel=second_channel,
            delay_hours=48,
            template_key="dormant-step-2",
        ),
    )


def _step(
    *,
    cadence_step_id: UUID,
    step_order: int,
    channel: ContactChannel,
    delay_hours: int,
    template_key: str,
) -> CampaignCadenceStep:
    return CampaignCadenceStep(
        cadence_step_id=cadence_step_id,
        workspace_id=WORKSPACE_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        step_order=step_order,
        channel=channel,
        delay_hours=delay_hours,
        message_goal="Check whether the lead is still considering a move.",
        template_key=template_key,
        max_attempts=1,
        created_at=NOW,
    )


def _paused_search_track_version() -> PausedSearchTrackVersion:
    return PausedSearchTrackVersion(
        track_version_id=PAUSED_SEARCH_TRACK_VERSION_ID,
        workspace_id=WORKSPACE_ID,
        track_id=PAUSED_SEARCH_TRACK_ID,
        version_number=1,
        status=CampaignVersionStatus.PUBLISHED,
        selection_guidance="Select when a paused lead needs periodic follow-up.",
        enabled=True,
        allowed_channels=(ContactChannel.EMAIL,),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL,
        maintenance_interval_days=60,
        reactivation_window_days=30,
        max_total_touches=4,
        created_by_user_id=UUID("00000000-0000-0000-0000-00000000000d"),
        created_at=NOW,
        published_at=NOW,
    )


def _paused_search_steps() -> tuple[PausedSearchTrackStep, ...]:
    return (
        _paused_search_step(
            step_id=PAUSED_SEARCH_STEP_ONE_ID,
            step_order=1,
            delay_hours=0,
            message_goal="Check whether the lead's paused search timing has changed.",
            template_key="paused-search-waiting-for-rates-maintenance-email-1",
        ),
        _paused_search_step(
            step_id=PAUSED_SEARCH_STEP_TWO_ID,
            step_order=2,
            delay_hours=24 * 30,
            message_goal="Follow up once more on the paused search timing.",
        ),
    )


def _paused_search_step(
    *,
    step_id: UUID,
    step_order: int,
    delay_hours: int,
    message_goal: str,
    phase: PausedSearchTrackStepPhase = PausedSearchTrackStepPhase.MAINTENANCE,
    template_key: str | None = None,
) -> PausedSearchTrackStep:
    return PausedSearchTrackStep(
        step_id=step_id,
        workspace_id=WORKSPACE_ID,
        track_version_id=PAUSED_SEARCH_TRACK_VERSION_ID,
        step_order=step_order,
        phase=phase,
        channel=ContactChannel.EMAIL,
        delay_hours=delay_hours,
        message_goal=message_goal,
        template_key=template_key or f"paused-search-{step_order}",
        max_attempts=1,
        review_required=False,
        created_at=NOW,
    )


def _paused_search_track_repository() -> FakePausedSearchTrackAdminRepository:
    return FakePausedSearchTrackAdminRepository(
        versions=(_paused_search_track_version(),),
        steps=_paused_search_steps(),
    )


def _draft_requests(llm_client: FakeLLMClient) -> list[Any]:
    return [
        request
        for request in llm_client.requests
        if request.prompt_version != OUTBOUND_QUERY_EXTRACTION_PROMPT_VERSION
    ]
