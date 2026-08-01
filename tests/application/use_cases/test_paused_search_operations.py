from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from app.application.ports.lead_read import LeadReadLeadRepository, LeadReadWorkflowRepository
from app.application.ports.repositories import (
    OutboundMessageRepository,
    PausedSearchOccurrenceOperationsRepository,
    PausedSearchReviewRepository,
    TemporalSignalOutboxRepository,
)
from app.application.use_cases.paused_search_operations import (
    PausedSearchOperationsStatus,
    apply_paused_search_review_action,
    edit_paused_search_message_review,
    list_paused_search_occurrences,
    list_paused_search_reviews,
)
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.paused_search_occurrences import (
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.paused_search_reviews import (
    PausedSearchReview,
    PausedSearchReviewAction,
    PausedSearchReviewKind,
    PausedSearchReviewStatus,
)
from app.domain.campaigns.paused_search_tracks import PausedSearchTrackStepPhase
from app.domain.compliance.contactability import ContactChannel
from app.domain.crm_sync import ExternalEvent
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import (
    LeadWorkflow,
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    WorkflowState,
)

NOW = datetime(2026, 7, 30, 15, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000003")
TRACK_VERSION_ID = UUID("00000000-0000-0000-0000-000000000004")
STEP_ID = UUID("00000000-0000-0000-0000-000000000005")
OCCURRENCE_ID = UUID("00000000-0000-0000-0000-000000000006")
REVIEW_ID = UUID("00000000-0000-0000-0000-000000000007")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000008")
MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000010")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000011")


async def test_assigned_agent_sees_only_owned_occurrences_and_reviews() -> None:
    occurrence = _occurrence()
    review = _review()
    occurrence_repository = cast(
        PausedSearchOccurrenceOperationsRepository,
        _OccurrenceRepository(occurrence),
    )
    review_repository = cast(PausedSearchReviewRepository, _ReviewRepository(review))
    lead_repository = cast(LeadReadLeadRepository, _LeadRepository(_lead()))

    occurrence_result = await list_paused_search_occurrences(
        actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
        workspace_id=WORKSPACE_ID,
        occurrence_repository=occurrence_repository,
        lead_repository=lead_repository,
    )
    review_result = await list_paused_search_reviews(
        actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
        workspace_id=WORKSPACE_ID,
        review_repository=review_repository,
        lead_repository=lead_repository,
    )

    assert occurrence_result.status is PausedSearchOperationsStatus.OK
    assert len(occurrence_result.occurrences) == 1
    assert review_result.status is PausedSearchOperationsStatus.OK
    assert len(review_result.reviews) == 1


async def test_review_approval_is_state_guarded_and_updates_occurrence() -> None:
    occurrence = _occurrence(status=RecurringOccurrenceStatus.REVIEW_REQUESTED)
    review = _review()
    occurrence_repository = cast(
        PausedSearchOccurrenceOperationsRepository,
        _OccurrenceRepository(occurrence),
    )
    review_repository = cast(PausedSearchReviewRepository, _ReviewRepository(review))
    message_repository = cast(OutboundMessageRepository, _MessageRepository(_message()))
    events = _ExternalEventRepository()
    signals = _SignalOutboxRepository()

    result = await apply_paused_search_review_action(
        actor=_actor(WorkspaceMembershipRole.MANAGER),
        workspace_id=WORKSPACE_ID,
        review_id=REVIEW_ID,
        action=PausedSearchReviewAction.APPROVE,
        reason="Provider content approved after operator review",
        review_repository=review_repository,
        occurrence_repository=occurrence_repository,
        lead_repository=cast(LeadReadLeadRepository, _LeadRepository(_lead())),
        message_repository=message_repository,
        workflow_repository=cast(LeadReadWorkflowRepository, _WorkflowRepository()),
        external_event_repository=events,
        temporal_signal_outbox_repository=cast(TemporalSignalOutboxRepository, signals),
        idempotency_key="approve-review-1",
        now=NOW,
    )

    assert result.status is PausedSearchOperationsStatus.OK
    assert result.review is not None
    assert result.review.status is PausedSearchReviewStatus.APPROVED
    assert result.occurrence is not None
    assert result.occurrence.status is RecurringOccurrenceStatus.APPROVED
    assert len(events.events) == 1
    assert len(signals.entries) == 1
    assert signals.entries[0].signal_name is TemporalSignalName.BLOCKED_REVIEW_COMPLETED

    duplicate = await apply_paused_search_review_action(
        actor=_actor(WorkspaceMembershipRole.MANAGER),
        workspace_id=WORKSPACE_ID,
        review_id=REVIEW_ID,
        action=PausedSearchReviewAction.APPROVE,
        reason="Duplicate command",
        review_repository=review_repository,
        occurrence_repository=occurrence_repository,
        lead_repository=cast(LeadReadLeadRepository, _LeadRepository(_lead())),
        message_repository=message_repository,
        idempotency_key="approve-review-1",
        now=NOW + timedelta(minutes=1),
    )
    assert duplicate.status is PausedSearchOperationsStatus.ALREADY_RESOLVED


async def test_policy_resolution_requires_action_payload_for_migration() -> None:
    review = replace(_review(), kind=PausedSearchReviewKind.POLICY)
    result = await apply_paused_search_review_action(
        actor=_actor(WorkspaceMembershipRole.MANAGER),
        workspace_id=WORKSPACE_ID,
        review_id=REVIEW_ID,
        action=PausedSearchReviewAction.RESOLVE,
        resolution_action="migrate",
        reason="Move to the approved replacement track",
        review_repository=cast(PausedSearchReviewRepository, _ReviewRepository(review)),
        occurrence_repository=cast(
            PausedSearchOccurrenceOperationsRepository, _OccurrenceRepository(_occurrence())
        ),
        lead_repository=cast(LeadReadLeadRepository, _LeadRepository(_lead())),
        idempotency_key="policy-migrate-1",
        now=NOW,
    )

    assert result.status is PausedSearchOperationsStatus.INVALID


async def test_message_review_edit_creates_immutable_version_and_is_idempotent() -> None:
    review_repository = cast(PausedSearchReviewRepository, _ReviewRepository(_review()))
    messages = _MessageRepository(_message())
    message_repository = cast(OutboundMessageRepository, messages)
    events = _ExternalEventRepository()

    result = await edit_paused_search_message_review(
        actor=_actor(WorkspaceMembershipRole.MANAGER),
        workspace_id=WORKSPACE_ID,
        review_id=REVIEW_ID,
        body="Operator-edited draft",
        subject=None,
        reason="Clarified the wording",
        idempotency_key="edit-review-1",
        review_repository=review_repository,
        message_repository=message_repository,
        lead_repository=cast(LeadReadLeadRepository, _LeadRepository(_lead())),
        external_event_repository=events,
        now=NOW,
    )
    duplicate = await edit_paused_search_message_review(
        actor=_actor(WorkspaceMembershipRole.MANAGER),
        workspace_id=WORKSPACE_ID,
        review_id=REVIEW_ID,
        body="Operator-edited draft",
        subject=None,
        reason="Clarified the wording",
        idempotency_key="edit-review-1",
        review_repository=review_repository,
        message_repository=message_repository,
        lead_repository=cast(LeadReadLeadRepository, _LeadRepository(_lead())),
        external_event_repository=events,
        now=NOW,
    )

    assert result.status is PausedSearchOperationsStatus.OK
    assert result.message is not None
    assert result.message.message_version == 2
    assert result.message.body == "Operator-edited draft"
    assert duplicate.message == result.message
    assert messages.messages[MESSAGE_ID].status is OutboundMessageStatus.CANCELLED
    assert len(messages.messages) == 2
    assert len(events.events) == 1


def _actor(role: WorkspaceMembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=UUID("00000000-0000-0000-0000-000000000009"),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-lead-1",
        facts_derived_at=NOW,
        source_payload_version="1",
        assigned_agent_user_id=ACTOR_ID,
        effective_owner_user_id=ACTOR_ID,
        mapped_custom_fields={"display_name": "Taylor Lead"},
    )


def _occurrence(
    *, status: RecurringOccurrenceStatus = RecurringOccurrenceStatus.PLANNED
) -> RecurringOccurrence:
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
        due_at=NOW + timedelta(hours=1),
        status=status,
        idempotency_key="occurrence-1",
        created_at=NOW,
    )


def _review(
    *, status: PausedSearchReviewStatus = PausedSearchReviewStatus.PENDING
) -> PausedSearchReview:
    return PausedSearchReview(
        review_id=REVIEW_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        occurrence_id=OCCURRENCE_ID,
        kind=PausedSearchReviewKind.MESSAGE,
        status=status,
        reason="Message requires human review",
        requested_at=NOW,
        outbound_message_id=MESSAGE_ID,
        outbound_message_version=1,
    )


def _message() -> OutboundMessage:
    return OutboundMessage(
        message_id=MESSAGE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        cadence_step_id=str(STEP_ID),
        channel=ContactChannel.SMS,
        status=OutboundMessageStatus.PENDING,
        idempotency_key="message-v1",
        body="Original draft",
        created_at=NOW,
        updated_at=NOW,
    )


class _LeadRepository:
    def __init__(self, lead: CanonicalLeadRecord) -> None:
        self.lead = lead

    async def get_by_id(self, workspace_id: UUID, lead_id: UUID) -> CanonicalLeadRecord | None:
        if workspace_id != self.lead.workspace_id or lead_id != self.lead.lead_id:
            return None
        return self.lead

    async def list_for_workspace(
        self, workspace_id: UUID, *, limit: int = 100
    ) -> tuple[CanonicalLeadRecord, ...]:
        return (self.lead,) if workspace_id == self.lead.workspace_id else ()


class _OccurrenceRepository:
    def __init__(self, occurrence: RecurringOccurrence) -> None:
        self.occurrence = occurrence

    async def list_for_workspace(
        self,
        workspace_id: UUID,
        *,
        lead_id: UUID | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> tuple[RecurringOccurrence, ...]:
        return (self.occurrence,) if workspace_id == self.occurrence.workspace_id else ()

    async def get_by_id(
        self, workspace_id: UUID, occurrence_id: UUID
    ) -> RecurringOccurrence | None:
        return self.occurrence if occurrence_id == self.occurrence.occurrence_id else None

    async def update_status(
        self,
        *,
        status: str,
        now: datetime,
        failure_reason: str | None,
        **kwargs: object,
    ) -> RecurringOccurrence:
        self.occurrence = replace(
            self.occurrence,
            status=RecurringOccurrenceStatus(status),
            closed_at=now,
            failure_reason=failure_reason,
        )
        return self.occurrence


class _ReviewRepository:
    def __init__(self, review: PausedSearchReview) -> None:
        self.review = review

    async def list_for_workspace(
        self,
        workspace_id: UUID,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> tuple[PausedSearchReview, ...]:
        return (self.review,) if workspace_id == self.review.workspace_id else ()

    async def get_by_id(
        self, workspace_id: UUID, review_id: UUID
    ) -> PausedSearchReview | None:
        return self.review if review_id == self.review.review_id else None

    async def get_by_id_for_update(
        self, workspace_id: UUID, review_id: UUID
    ) -> PausedSearchReview | None:
        return await self.get_by_id(workspace_id, review_id)

    async def get_by_occurrence(
        self, workspace_id: UUID, occurrence_id: UUID, kind: str
    ) -> PausedSearchReview | None:
        if (
            workspace_id == self.review.workspace_id
            and occurrence_id == self.review.occurrence_id
            and kind == self.review.kind.value
        ):
            return self.review
        return None

    async def create_or_get(self, review: PausedSearchReview) -> PausedSearchReview:
        self.review = review
        return review

    async def save(self, review: PausedSearchReview) -> PausedSearchReview:
        self.review = review
        return review


class _MessageRepository:
    def __init__(self, message: OutboundMessage) -> None:
        self.messages = {message.message_id: message}

    async def get_by_id(self, workspace_id: UUID, message_id: UUID) -> OutboundMessage | None:
        message = self.messages.get(message_id)
        return message if message and message.workspace_id == workspace_id else None

    async def save(self, message: OutboundMessage) -> OutboundMessage:
        self.messages[message.message_id] = message
        return message


class _ExternalEventRepository:
    def __init__(self) -> None:
        self.events: list[ExternalEvent] = []

    async def get_by_provider_event_id(
        self, workspace_id: UUID, provider_name: str, provider_event_id: str
    ) -> ExternalEvent | None:
        return next(
            (
                event
                for event in self.events
                if event.workspace_id == workspace_id
                and event.provider == provider_name
                and event.provider_event_id == provider_event_id
            ),
            None,
        )

    async def save(self, event: ExternalEvent) -> ExternalEvent:
        self.events.append(event)
        return event


class _WorkflowRepository:
    async def get_latest_for_lead(
        self, workspace_id: UUID, lead_id: UUID
    ) -> LeadWorkflow | None:
        if workspace_id != WORKSPACE_ID or lead_id != LEAD_ID:
            return None
        return LeadWorkflow(
            workflow_id=WORKFLOW_ID,
            temporal_workflow_id="lead-workflow-1",
            workspace_id=WORKSPACE_ID,
            campaign_enrollment_id=UUID("00000000-0000-0000-0000-000000000012"),
            campaign_id=CAMPAIGN_ID,
            lead_id=LEAD_ID,
            state=WorkflowState.WAITING_FOR_RESPONSE,
            last_transition_at=NOW,
            state_version=1,
            created_at=NOW,
            updated_at=NOW,
        )


class _SignalOutboxRepository:
    def __init__(self) -> None:
        self.entries: list[TemporalSignalOutboxEntry] = []

    async def append(self, entry: TemporalSignalOutboxEntry) -> TemporalSignalOutboxEntry:
        self.entries.append(entry)
        return entry