from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from app.application.ports.crm import CRMAgent, CRMClient
from app.application.ports.notifications import NotificationProvider, ReviewNotification
from app.application.ports.repositories import (
    LeadRepository,
    WorkspaceHandoffConfigRepository,
)
from app.application.use_cases.resolve_uncertain_paused_search_occurrence import (
    UncertainOccurrenceResolution,
    UncertainOccurrenceResolutionStatus,
    resolve_uncertain_paused_search_occurrence,
)
from app.application.use_cases.timeout_uncertain_paused_search_occurrence import (
    timeout_uncertain_paused_search_occurrence,
)
from app.domain.campaigns.paused_search_notifications import (
    PausedSearchNotification,
    PausedSearchNotificationStatus,
)
from app.domain.campaigns.paused_search_occurrences import (
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.paused_search_tracks import PausedSearchTrackStepPhase
from app.domain.conversations import WorkspaceHandoffConfig
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import TemporalSignalName, WorkflowState, WorkflowTransitionReasonCode
from tests.application.use_cases._campaign_cadence_fakes import (
    FakePausedSearchOccurrenceRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeLeadWorkflowRepository,
    FakeTemporalSignalOutboxRepository,
    FakeWorkflowTransitionRepository,
)

NOW = datetime(2026, 7, 13, 15, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000003")
TRACK_VERSION_ID = UUID("00000000-0000-0000-0000-000000000004")
STEP_ID = UUID("00000000-0000-0000-0000-000000000005")
OCCURRENCE_ID = UUID("00000000-0000-0000-0000-000000000006")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000007")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000008")


@pytest.mark.parametrize(
    ("resolution", "expected_status", "expected_touches", "expected_workflow_state"),
    [
        (
            UncertainOccurrenceResolution.SENT,
            RecurringOccurrenceStatus.SENT,
            1,
            WorkflowState.ACTIVE_NURTURE,
        ),
        (
            UncertainOccurrenceResolution.FAILED,
            RecurringOccurrenceStatus.FAILED,
            0,
            WorkflowState.CLOSED,
        ),
        (
            UncertainOccurrenceResolution.SKIPPED,
            RecurringOccurrenceStatus.SKIPPED,
            0,
            WorkflowState.CLOSED,
        ),
    ],
)
async def test_operator_resolution_closes_occurrence_and_wakes_workflow(
    resolution: UncertainOccurrenceResolution,
    expected_status: RecurringOccurrenceStatus,
    expected_touches: int,
    expected_workflow_state: WorkflowState,
) -> None:
    occurrence_repository = FakePausedSearchOccurrenceRepository(_occurrence())
    workflow_repository = _workflow_repository(WorkflowState.PAUSED)
    outbox = FakeTemporalSignalOutboxRepository()

    result = await resolve_uncertain_paused_search_occurrence(
        workspace_id=WORKSPACE_ID,
        occurrence_id=OCCURRENCE_ID,
        resolution=resolution,
        reason="operator confirmed provider outcome",
        occurrence_repository=occurrence_repository,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_signal_outbox_repository=outbox,
        now=NOW,
        actor_user_id=ACTOR_ID,
    )

    assert result.status is UncertainOccurrenceResolutionStatus.RESOLVED
    assert result.occurrence is not None
    assert result.occurrence.status is expected_status
    assert result.occurrence.logical_touch_count == expected_touches
    assert result.occurrence.closed_at == NOW
    assert result.occurrence.failure_reason == "operator confirmed provider outcome"
    assert result.workflow_state is expected_workflow_state
    entry = next(iter(outbox.entries.values()))
    assert entry.signal_name is TemporalSignalName.BLOCKED_REVIEW_COMPLETED
    assert entry.payload["lead_id"] == str(LEAD_ID)
    assert entry.payload["actor_user_id"] == str(ACTOR_ID)

    duplicate = await resolve_uncertain_paused_search_occurrence(
        workspace_id=WORKSPACE_ID,
        occurrence_id=OCCURRENCE_ID,
        resolution=resolution,
        reason="duplicate operator action",
        occurrence_repository=occurrence_repository,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_signal_outbox_repository=outbox,
        now=NOW,
        actor_user_id=ACTOR_ID,
    )
    assert duplicate.status is UncertainOccurrenceResolutionStatus.ALREADY_RESOLVED
    assert len(outbox.entries) == 1


async def test_uncertain_timeout_fails_occurrence_pauses_workflow_and_is_idempotent() -> None:
    occurrence_repository = FakePausedSearchOccurrenceRepository(_occurrence())
    workflow_repository = _workflow_repository(WorkflowState.ACTIVE_NURTURE)
    outbox = FakeTemporalSignalOutboxRepository()
    transition_repository = FakeWorkflowTransitionRepository()

    result = await timeout_uncertain_paused_search_occurrence(
        workspace_id=WORKSPACE_ID,
        occurrence_id=OCCURRENCE_ID,
        now=NOW,
        occurrence_repository=occurrence_repository,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        temporal_signal_outbox_repository=outbox,
    )

    assert result.timed_out is True
    assert result.occurrence is not None
    assert result.occurrence.status is RecurringOccurrenceStatus.FAILED
    assert result.occurrence.logical_touch_count == 0
    assert result.occurrence.closed_at == NOW
    assert (
        result.occurrence.failure_reason
        == WorkflowTransitionReasonCode.UNCERTAIN_SEND_TIMEOUT.value
    )
    assert result.workflow_state is WorkflowState.PAUSED
    assert len(outbox.entries) == 1
    assert next(iter(outbox.entries.values())).signal_name is TemporalSignalName.PAUSE_REQUESTED

    duplicate = await timeout_uncertain_paused_search_occurrence(
        workspace_id=WORKSPACE_ID,
        occurrence_id=OCCURRENCE_ID,
        now=NOW,
        occurrence_repository=occurrence_repository,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        temporal_signal_outbox_repository=outbox,
    )
    assert duplicate.timed_out is False
    assert len(outbox.entries) == 1


async def test_uncertain_timeout_notifies_assigned_agent_for_review() -> None:
    occurrence_repository = FakePausedSearchOccurrenceRepository(_occurrence())
    workflow_repository = _workflow_repository(WorkflowState.ACTIVE_NURTURE)
    outbox = FakeTemporalSignalOutboxRepository()
    notifications = _FakeNotificationProvider()
    notification_repository = _FakeNotificationRepository()

    result = await timeout_uncertain_paused_search_occurrence(
        workspace_id=WORKSPACE_ID,
        occurrence_id=OCCURRENCE_ID,
        now=NOW,
        occurrence_repository=occurrence_repository,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_signal_outbox_repository=outbox,
        lead_repository=cast(LeadRepository, _FakeLeadRepository()),
        workspace_handoff_config_repository=cast(
            WorkspaceHandoffConfigRepository,
            _FakeHandoffConfigRepository(),
        ),
        crm_client=cast(CRMClient, _FakeCRMClient()),
        notification_provider=cast(NotificationProvider, notifications),
        notification_repository=notification_repository,
    )

    assert result.timed_out is True
    assert len(notifications.sent) == 1
    assert notifications.sent[0].recipient_destination == "agent@example.com"
    assert notifications.sent[0].review_reason == "uncertain_send_timeout"
    assert len(notification_repository.saved) == 2
    assert notification_repository.saved[-1].status is PausedSearchNotificationStatus.ACCEPTED


async def test_uncertain_resolution_rejects_unauthorized_assigned_agent() -> None:
    result = await resolve_uncertain_paused_search_occurrence(
        workspace_id=WORKSPACE_ID,
        occurrence_id=OCCURRENCE_ID,
        resolution=UncertainOccurrenceResolution.SENT,
        reason="operator action",
        occurrence_repository=FakePausedSearchOccurrenceRepository(_occurrence()),
        lead_workflow_repository=_workflow_repository(WorkflowState.PAUSED),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_signal_outbox_repository=FakeTemporalSignalOutboxRepository(),
        now=NOW,
        actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
        lead_repository=cast(LeadRepository, _FakeLeadRepository()),
    )

    assert result.status is UncertainOccurrenceResolutionStatus.REJECTED


def _actor(role: WorkspaceMembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=UUID("00000000-0000-0000-0000-000000000010"),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


class _FakeLeadRepository:
    async def get_by_id(self, workspace_id: UUID, lead_id: UUID) -> CanonicalLeadRecord:
        return CanonicalLeadRecord(
            workspace_id=workspace_id,
            lead_id=lead_id,
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            crm_lead_id="crm-lead-1",
            facts_derived_at=NOW,
            source_payload_version="test:v1",
            primary_email="lead@example.com",
            primary_phone="+15555550123",
            mapped_custom_fields={"display_name": "Jordan Seller"},
        )


class _FakeHandoffConfigRepository:
    async def get_by_workspace_id(self, workspace_id: UUID) -> WorkspaceHandoffConfig:
        return WorkspaceHandoffConfig(
            workspace_id=workspace_id,
            fallback_recipient_email="fallback@example.com",
        )


class _FakeCRMClient:
    async def get_assigned_agent(self, workspace_id: UUID, crm_lead_id: str) -> CRMAgent:
        return CRMAgent(crm_agent_id="agent-1", name="Assigned Agent", email="agent@example.com")


class _FakeNotificationProvider:
    def __init__(self) -> None:
        self.sent: list[ReviewNotification] = []

    async def send_review_notification(self, notification: ReviewNotification) -> object:
        self.sent.append(notification)
        return object()


class _FakeNotificationRepository:
    def __init__(self) -> None:
        self.saved: list[PausedSearchNotification] = []

    async def get_by_idempotency_key(
        self,
        workspace_id: UUID,
        idempotency_key: str,
    ) -> PausedSearchNotification | None:
        return next(
            (
                notification
                for notification in self.saved
                if notification.workspace_id == workspace_id
                and notification.idempotency_key == idempotency_key
            ),
            None,
        )

    async def save(self, notification: PausedSearchNotification) -> PausedSearchNotification:
        self.saved.append(notification)
        return notification


def _occurrence() -> RecurringOccurrence:
    return RecurringOccurrence(
        occurrence_id=OCCURRENCE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        track_version_id=TRACK_VERSION_ID,
        step_id=STEP_ID,
        phase=PausedSearchTrackStepPhase.MAINTENANCE,
        occurrence_number=1,
        scheduled_for=NOW,
        due_at=NOW,
        status=RecurringOccurrenceStatus.UNCERTAIN,
        idempotency_key="uncertain:test",
        created_at=NOW,
    )


def _workflow_repository(state: WorkflowState) -> FakeLeadWorkflowRepository:
    repository = FakeLeadWorkflowRepository()
    from app.domain.workflows import LeadWorkflow

    workflow = LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture-test",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=UUID("00000000-0000-0000-0000-000000000009"),
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=state,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)] = workflow
    repository.workflows[WORKFLOW_ID] = workflow
    return repository
