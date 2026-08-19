import json
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.ports.messaging import EmailMessage, SMSMessage
from app.domain.campaigns.execution import CampaignExecutionConfig, CampaignVersionStatus
from app.domain.campaigns.outbound_message import OutboundMessage, ProviderDeliveryStatus
from app.domain.campaigns.paused_search_occurrences import (
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.paused_search_reminders import (
    PausedSearchAgentReminder,
    PausedSearchReminderStatus,
)
from app.domain.campaigns.paused_search_reviews import PausedSearchReview
from app.domain.campaigns.rejected_draft_review import RejectedDraftReview
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import WorkspaceContactPolicy
from app.domain.conversations import CrmConversationEvent
from app.domain.identity import Workspace
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
    LeadClassificationArtifact,
    LeadPausedSearchHistoryEntry,
    LeadRoutingReview,
    LeadRoutingReviewStatus,
)
from app.domain.llm import WorkspaceLLMConfig
from app.domain.outbound_drafting import WorkspaceOutboundDraftingConfig
from app.domain.workflows import LeadWorkflow, WorkflowState, WorkflowTransition
from app.domain.workspace_automation import WorkspaceOperationalControl


class FakeCampaignExecutionRepository:
    def __init__(
        self,
        config: CampaignExecutionConfig | tuple[CampaignExecutionConfig, ...] | None,
    ) -> None:
        if config is None:
            self.configs: tuple[CampaignExecutionConfig, ...] = ()
        elif isinstance(config, tuple):
            self.configs = config
        else:
            self.configs = (config,)
        self.config = self.configs[0] if self.configs else None

    async def get_by_version_id(
        self,
        workspace_id: WorkspaceId,
        campaign_version_id: UUID,
    ) -> CampaignExecutionConfig | None:
        for config in self.configs:
            if config.workspace_id != workspace_id:
                continue
            if config.campaign_version_id == campaign_version_id:
                return config
        return None

    async def list_active_for_workspace(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[CampaignExecutionConfig, ...]:
        return tuple(
            config
            for config in self.configs
            if config.workspace_id == workspace_id
            and config.campaign_status == CampaignStatus.ACTIVE
            and config.version_status == CampaignVersionStatus.PUBLISHED
        )

    async def get_active_for_campaign(
        self,
        workspace_id: WorkspaceId,
        campaign_id: UUID,
    ) -> CampaignExecutionConfig | None:
        for config in self.configs:
            if config.workspace_id != workspace_id:
                continue
            if config.campaign_id == campaign_id:
                return config
        return None


class FakePausedSearchOccurrenceRepository:
    def __init__(self, occurrence: RecurringOccurrence | None = None) -> None:
        self.occurrence = occurrence
        self.updated: list[RecurringOccurrence] = []

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
    ) -> RecurringOccurrence | None:
        if (
            self.occurrence is not None
            and self.occurrence.workspace_id == workspace_id
            and self.occurrence.occurrence_id == occurrence_id
        ):
            return self.occurrence
        return None

    async def get_latest_for_step(
        self,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        track_version_id: UUID,
        step_id: UUID,
    ) -> RecurringOccurrence | None:
        return self.occurrence


    async def get_by_identity(
        self,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        track_version_id: UUID,
        step_id: UUID,
        occurrence_number: int,
        scheduled_for: object,
    ) -> RecurringOccurrence | None:
        return self.occurrence

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> RecurringOccurrence | None:
        if (
            self.occurrence is not None
            and self.occurrence.workspace_id == workspace_id
            and self.occurrence.idempotency_key == idempotency_key
        ):
            return self.occurrence
        return None


    async def create_or_get(self, occurrence: RecurringOccurrence) -> RecurringOccurrence:
        self.occurrence = self.occurrence or occurrence
        return self.occurrence

    async def get_by_provider_message_id_for_update(
        self,
        workspace_id: WorkspaceId,
        provider_message_id: str,
    ) -> RecurringOccurrence | None:
        if self.occurrence and self.occurrence.provider_message_id == provider_message_id:
            return self.occurrence
        return None

    async def update_status(
        self,
        *,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
        status: str,
        now: datetime,
        provider_message_id: str | None = None,
        provider_delivery_status: ProviderDeliveryStatus | None = None,
        failure_reason: str | None = None,
        fallback_used: bool | None = None,
    ) -> RecurringOccurrence | None:
        if self.occurrence is None or self.occurrence.occurrence_id != occurrence_id:
            return None
        self.occurrence = replace(
            self.occurrence,
            status=RecurringOccurrenceStatus(status),
            logical_touch_count=(
                self.occurrence.logical_touch_count
                + int(
                    status == RecurringOccurrenceStatus.SENT.value
                    and self.occurrence.status != RecurringOccurrenceStatus.SENT
                )
                if status == RecurringOccurrenceStatus.SENT.value
                else self.occurrence.logical_touch_count
            ),
            provider_message_id=provider_message_id or self.occurrence.provider_message_id,
            provider_delivery_status=(
                provider_delivery_status or self.occurrence.provider_delivery_status
            ),
            failure_reason=failure_reason or self.occurrence.failure_reason,
            fallback_used=(
                fallback_used if fallback_used is not None else self.occurrence.fallback_used
            ),
        )
        self.updated.append(self.occurrence)
        return self.occurrence

    async def cancel_open_for_workflow(
        self,
        *,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        now: datetime,
        reason: str,
    ) -> int:
        if (
            self.occurrence is None
            or self.occurrence.workspace_id != workspace_id
            or self.occurrence.workflow_id != workflow_id
            or self.occurrence.status
            not in {
                RecurringOccurrenceStatus.PLANNED,
                RecurringOccurrenceStatus.DEFERRED,
                RecurringOccurrenceStatus.REVIEW_REQUESTED,
                RecurringOccurrenceStatus.APPROVED,
            }
        ):
            return 0
        self.occurrence = replace(
            self.occurrence,
            status=RecurringOccurrenceStatus.CANCELLED,
            closed_at=now,
            failure_reason=reason,
        )
        self.updated.append(self.occurrence)
        return 1

    async def resolve_uncertain(
        self,
        *,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
        status: str,
        now: datetime,
        reason: str,
    ) -> RecurringOccurrence | None:
        if self.occurrence is None or self.occurrence.occurrence_id != occurrence_id:
            return None
        if self.occurrence.status != RecurringOccurrenceStatus.UNCERTAIN:
            return None
        self.occurrence = replace(
            self.occurrence,
            status=RecurringOccurrenceStatus(status),
            logical_touch_count=1 if status == RecurringOccurrenceStatus.SENT.value else 0,
            closed_at=now,
            failure_reason=reason,
        )
        self.updated.append(self.occurrence)
        return self.occurrence

    async def reopen_failed_for_retry(
        self,
        *,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
        scheduled_for: datetime,
        due_at: datetime,
        now: datetime,
    ) -> RecurringOccurrence | None:
        if (
            self.occurrence is None
            or self.occurrence.workspace_id != workspace_id
            or self.occurrence.occurrence_id != occurrence_id
            or self.occurrence.status != RecurringOccurrenceStatus.FAILED
        ):
            return None
        self.occurrence = replace(
            self.occurrence,
            status=RecurringOccurrenceStatus.PLANNED,
            scheduled_for=scheduled_for,
            due_at=due_at,
            closed_at=None,
            provider_message_id=None,
            provider_delivery_status=None,
        )
        self.updated.append(self.occurrence)
        return self.occurrence

    async def reschedule_open(
        self,
        *,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
        scheduled_for: datetime,
        now: datetime,
    ) -> RecurringOccurrence | None:
        if (
            self.occurrence is None
            or self.occurrence.workspace_id != workspace_id
            or self.occurrence.occurrence_id != occurrence_id
            or self.occurrence.status
            in {
                RecurringOccurrenceStatus.SENT,
                RecurringOccurrenceStatus.SKIPPED,
                RecurringOccurrenceStatus.CANCELLED,
                RecurringOccurrenceStatus.EXPIRED,
                RecurringOccurrenceStatus.FAILED,
            }
        ):
            return None
        self.occurrence = replace(
            self.occurrence,
            status=RecurringOccurrenceStatus.PLANNED,
            scheduled_for=scheduled_for,
        )
        self.updated.append(self.occurrence)
        return self.occurrence

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
    ) -> RecurringOccurrence | None:
        if (
            self.occurrence is None
            or self.occurrence.workspace_id != workspace_id
            or self.occurrence.occurrence_id != occurrence_id
        ):
            return None
        return self.occurrence


class FakePausedSearchAgentReminderRepository:
    def __init__(self) -> None:
        self.reminders: dict[str, PausedSearchAgentReminder] = {}

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> PausedSearchAgentReminder | None:
        reminder = self.reminders.get(idempotency_key)
        if reminder is None or reminder.workspace_id != workspace_id:
            return None
        return reminder

    async def create_or_get(
        self,
        reminder: PausedSearchAgentReminder,
    ) -> PausedSearchAgentReminder:
        return self.reminders.setdefault(reminder.idempotency_key, reminder)

    async def cancel_open_for_workflow(
        self,
        *,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        now: datetime,
    ) -> int:
        cancelled = 0
        for key, reminder in tuple(self.reminders.items()):
            if (
                reminder.workspace_id == workspace_id
                and reminder.workflow_id == workflow_id
                and reminder.status is PausedSearchReminderStatus.PENDING
            ):
                self.reminders[key] = replace(
                    reminder,
                    status=PausedSearchReminderStatus.CANCELLED,
                    cancelled_at=now,
                )
                cancelled += 1
        return cancelled


class FakePausedSearchReviewRepository:
    def __init__(self) -> None:
        self.reviews: dict[UUID, PausedSearchReview] = {}

    async def list_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        lead_id: UUID | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> tuple[PausedSearchReview, ...]:
        return tuple(self.reviews.values())[:limit]

    async def get_by_id(
        self, workspace_id: WorkspaceId, review_id: UUID
    ) -> PausedSearchReview | None:
        return self.reviews.get(review_id)

    async def get_by_id_for_update(
        self, workspace_id: WorkspaceId, review_id: UUID
    ) -> PausedSearchReview | None:
        return await self.get_by_id(workspace_id, review_id)

    async def get_by_occurrence(
        self, workspace_id: WorkspaceId, occurrence_id: UUID, kind: str
    ) -> PausedSearchReview | None:
        return next(
            (
                review
                for review in self.reviews.values()
                if review.workspace_id == workspace_id
                and review.occurrence_id == occurrence_id
                and review.kind.value == kind
            ),
            None,
        )

    async def create_or_get(self, review: PausedSearchReview) -> PausedSearchReview:
        existing = await self.get_by_occurrence(
            review.workspace_id,
            review.occurrence_id or UUID(int=0),
            review.kind.value,
        )
        if existing is not None:
            return existing
        self.reviews[review.review_id] = review
        return review

    async def save(self, review: PausedSearchReview) -> PausedSearchReview:
        self.reviews[review.review_id] = review
        return review


class FakeWorkspaceRepository:
    def __init__(self, workspace: Workspace | None) -> None:
        self.workspace = workspace

    async def get_by_id(self, workspace_id: WorkspaceId) -> Workspace | None:
        if self.workspace and self.workspace.workspace_id == workspace_id:
            return self.workspace
        return None

    async def save(self, workspace: Workspace) -> Workspace:
        self.workspace = workspace
        return workspace


class FakeWorkspaceContactPolicyRepository:
    def __init__(self, policy: WorkspaceContactPolicy | None) -> None:
        self.policy = policy
        self.saved: list[WorkspaceContactPolicy] = []

    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceContactPolicy | None:
        if self.policy is None:
            return None
        if self.policy.workspace_id != workspace_id:
            return None
        return self.policy

    async def save(self, policy: WorkspaceContactPolicy) -> WorkspaceContactPolicy:
        self.saved.append(policy)
        self.policy = policy
        return policy


class FakeWorkspaceLLMConfigRepository:
    def __init__(self, config: WorkspaceLLMConfig | None = None) -> None:
        self.config = config
        self.saved: list[WorkspaceLLMConfig] = []

    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceLLMConfig | None:
        if self.config is None:
            return None
        if self.config.workspace_id != workspace_id:
            return None
        return self.config

    async def save(self, config: WorkspaceLLMConfig) -> WorkspaceLLMConfig:
        self.saved.append(config)
        self.config = config
        return config


class FakeWorkspaceOperationalControlRepository:
    def __init__(self, control: WorkspaceOperationalControl | None = None) -> None:
        self.control = control
        self.saved: list[WorkspaceOperationalControl] = []

    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceOperationalControl | None:
        if self.control is None:
            return None
        if self.control.workspace_id != workspace_id:
            return None
        return self.control

    async def save(
        self,
        control: WorkspaceOperationalControl,
    ) -> WorkspaceOperationalControl:
        self.saved.append(control)
        self.control = control
        return control


class FakeWorkspaceOutboundDraftingConfigRepository:
    def __init__(self, config: WorkspaceOutboundDraftingConfig | None = None) -> None:
        self.config = config
        self.saved: list[WorkspaceOutboundDraftingConfig] = []

    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceOutboundDraftingConfig | None:
        if self.config is None:
            return None
        if self.config.workspace_id != workspace_id:
            return None
        return self.config

    async def save(
        self,
        config: WorkspaceOutboundDraftingConfig,
    ) -> WorkspaceOutboundDraftingConfig:
        self.saved.append(config)
        self.config = config
        return config


class FakeLeadRepository:
    def __init__(self, lead: CanonicalLeadRecord | None = None) -> None:
        self.lead = lead
        self.saved: list[CanonicalLeadRecord] = []
        self.history_entries: list[LeadPausedSearchHistoryEntry] = []
        self.by_id: dict[tuple[WorkspaceId, LeadId], CanonicalLeadRecord] = {}
        self.by_crm_id: dict[tuple[WorkspaceId, CRMProvider, str], CanonicalLeadRecord] = {}
        if lead is not None:
            self._store(lead)

    def _store(self, lead: CanonicalLeadRecord) -> None:
        self.lead = lead
        self.by_id[(lead.workspace_id, lead.lead_id)] = lead
        self.by_crm_id[(lead.workspace_id, lead.crm_provider, lead.crm_lead_id)] = lead

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        return self.by_id.get((workspace_id, lead_id))

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        return await self.get_by_id(workspace_id, lead_id)

    async def get_by_crm_id(
        self,
        workspace_id: WorkspaceId,
        crm_provider: CRMProvider,
        crm_lead_id: str,
    ) -> CanonicalLeadRecord | None:
        return self.by_crm_id.get((workspace_id, crm_provider, crm_lead_id))

    async def list_by_assigned_agent_crm_id(
        self,
        workspace_id: WorkspaceId,
        assigned_agent_crm_id: str,
    ) -> tuple[CanonicalLeadRecord, ...]:
        return tuple(
            lead
            for (lead_workspace_id, _), lead in self.by_id.items()
            if lead_workspace_id == workspace_id
            and lead.assigned_agent_crm_id == assigned_agent_crm_id
        )

    async def get_by_primary_phone(
        self,
        workspace_id: WorkspaceId,
        phone_number: str,
    ) -> CanonicalLeadRecord | None:
        normalized = _normalized_phone(phone_number)
        if normalized is None:
            return None
        candidates = {normalized}
        if len(normalized) == 11 and normalized.startswith("1"):
            candidates.add(normalized[1:])
        elif len(normalized) == 10:
            candidates.add(f"1{normalized}")
        matches = [
            lead
            for (lead_workspace_id, _), lead in self.by_id.items()
            if lead_workspace_id == workspace_id
            and lead.primary_phone is not None
            and _normalized_phone(lead.primary_phone) in candidates
        ]
        if len(matches) != 1:
            return None
        return matches[0]

    async def get_by_primary_email(
        self,
        workspace_id: WorkspaceId,
        email_address: str,
    ) -> CanonicalLeadRecord | None:
        matches = await self.list_by_primary_email(workspace_id, email_address)
        if len(matches) != 1:
            return None
        return matches[0]

    async def list_by_primary_email(
        self,
        workspace_id: WorkspaceId,
        email_address: str,
    ) -> tuple[CanonicalLeadRecord, ...]:
        normalized = _normalized_email(email_address)
        if normalized is None:
            return ()
        matches = [
            lead
            for (lead_workspace_id, _), lead in self.by_id.items()
            if lead_workspace_id == workspace_id
            and lead.primary_email is not None
            and _normalized_email(lead.primary_email) == normalized
        ]
        return tuple(matches)

    async def upsert(self, record: CanonicalLeadRecord) -> CanonicalLeadRecord:
        self.saved.append(record)
        self._store(record)
        return record

    async def append(self, entry: LeadPausedSearchHistoryEntry) -> LeadPausedSearchHistoryEntry:
        self.history_entries.append(entry)
        return entry

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[LeadPausedSearchHistoryEntry, ...]:
        _ = (workspace_id, limit)
        return tuple(
            entry
            for entry in self.history_entries
            if entry.workspace_id == workspace_id and entry.lead_id == lead_id
        )

    async def list_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[CanonicalLeadRecord, ...]:
        matches = tuple(
            lead
            for (lead_workspace_id, _), lead in self.by_id.items()
            if lead_workspace_id == workspace_id
        )
        return matches[:limit]


def _normalized_phone(phone_number: str | None) -> str | None:
    if phone_number is None:
        return None
    digits_only = "".join(character for character in phone_number if character.isdigit())
    return digits_only or None


def _normalized_email(email_address: str | None) -> str | None:
    if email_address is None:
        return None
    normalized = email_address.strip().lower()
    return normalized or None


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

    async def list_recent_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 5,
    ) -> tuple[LeadWorkflow, ...]:
        matching = [
            workflow
            for workflow in self.workflows.values()
            if workflow.workspace_id == workspace_id and workflow.lead_id == lead_id
        ]
        matching.sort(key=lambda workflow: workflow.last_transition_at, reverse=True)
        return tuple(matching[:limit])

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

    async def save(self, workflow: LeadWorkflow) -> LeadWorkflow:
        self.workflows[workflow.workflow_id] = workflow
        self.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow
        return workflow

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
        matches = sorted(
            (
                transition
                for transition in self.transitions.values()
                if transition.workspace_id == workspace_id and transition.workflow_id == workflow_id
            ),
            key=lambda transition: transition.created_at,
            reverse=True,
        )
        return tuple(matches[:limit])


class FakeOutboundMessageRepository:
    def __init__(self) -> None:
        self.messages_by_idempotency_key: dict[tuple[WorkspaceId, str], OutboundMessage] = {}
        self.saved: list[OutboundMessage] = []

    def _store(self, message: OutboundMessage) -> None:
        self.messages_by_idempotency_key[(message.workspace_id, message.idempotency_key)] = message

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[OutboundMessage, ...]:
        matches = tuple(
            message
            for message in self.messages_by_idempotency_key.values()
            if message.workspace_id == workspace_id and message.lead_id == lead_id
        )
        return matches[:limit]

    async def get_by_id(
        self, workspace_id: WorkspaceId, message_id: UUID
    ) -> OutboundMessage | None:
        for message in self.messages_by_idempotency_key.values():
            if message.workspace_id == workspace_id and message.message_id == message_id:
                return message
        return None

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundMessage | None:
        return self.messages_by_idempotency_key.get((workspace_id, idempotency_key))

    async def get_by_idempotency_key_for_update(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundMessage | None:
        return await self.get_by_idempotency_key(workspace_id, idempotency_key)

    async def get_by_provider_message_id_for_workspace(
        self,
        workspace_id: WorkspaceId,
        provider_name: str,
        provider_message_id: str,
    ) -> OutboundMessage | None:
        for message in self.messages_by_idempotency_key.values():
            if (
                message.workspace_id == workspace_id
                and message.provider_name == provider_name
                and message.provider_message_id == provider_message_id
            ):
                return message
        return None

    async def get_by_reply_routing_token(
        self,
        workspace_id: WorkspaceId,
        reply_routing_token: str,
    ) -> OutboundMessage | None:
        for message in self.messages_by_idempotency_key.values():
            if (
                message.workspace_id == workspace_id
                and message.reply_routing_token == reply_routing_token
            ):
                return message
        return None

    async def save(self, message: OutboundMessage) -> OutboundMessage:
        self.saved.append(message)
        self._store(message)
        return message


class FakeCrmConversationEventRepository:
    def __init__(self, events: tuple[CrmConversationEvent, ...] = ()) -> None:
        self.saved: list[CrmConversationEvent] = list(events)

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[CrmConversationEvent, ...]:
        events = tuple(
            event
            for event in self.saved
            if event.workspace_id == workspace_id and event.lead_id == lead_id
        )
        return events[:limit]

    async def save(self, event: CrmConversationEvent) -> CrmConversationEvent:
        self.saved = [
            existing
            for existing in self.saved
            if not (
                existing.workspace_id == event.workspace_id
                and existing.crm_provider == event.crm_provider
                and existing.crm_activity_id == event.crm_activity_id
            )
        ]
        self.saved.append(event)
        return event


class FakeLeadClassificationArtifactRepository:
    def __init__(self) -> None:
        self.saved: list[LeadClassificationArtifact] = []

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        artifact_id: UUID,
    ) -> LeadClassificationArtifact | None:
        for artifact in self.saved:
            if artifact.workspace_id == workspace_id and artifact.artifact_id == artifact_id:
                return artifact
        return None

    async def save(self, artifact: LeadClassificationArtifact) -> LeadClassificationArtifact:
        self.saved.append(artifact)
        return artifact

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[LeadClassificationArtifact, ...]:
        _ = (workspace_id, limit)
        return tuple(
            artifact
            for artifact in self.saved
            if artifact.workspace_id == workspace_id and artifact.lead_id == lead_id
        )


class FakeLeadRoutingReviewRepository:
    def __init__(self) -> None:
        self.saved: list[LeadRoutingReview] = []

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        review_id: UUID,
    ) -> LeadRoutingReview | None:
        for review in self.saved:
            if review.workspace_id == workspace_id and review.review_id == review_id:
                return review
        return None

    async def get_by_artifact_id(
        self,
        workspace_id: WorkspaceId,
        artifact_id: UUID,
    ) -> LeadRoutingReview | None:
        for review in self.saved:
            if review.workspace_id == workspace_id and review.artifact_id == artifact_id:
                return review
        return None

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 20,
    ) -> tuple[LeadRoutingReview, ...]:
        matches = tuple(
            review
            for review in self.saved
            if review.workspace_id == workspace_id and review.lead_id == lead_id
        )
        return matches[:limit]

    async def list_pending_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[LeadRoutingReview, ...]:
        matches = tuple(
            review
            for review in self.saved
            if review.workspace_id == workspace_id
            and review.status == LeadRoutingReviewStatus.PENDING
        )
        return matches[:limit]

    async def save(self, review: LeadRoutingReview) -> LeadRoutingReview:
        for index, existing in enumerate(self.saved):
            if existing.review_id == review.review_id:
                self.saved[index] = review
                return review
            if (
                existing.workspace_id == review.workspace_id
                and existing.artifact_id == review.artifact_id
            ):
                self.saved[index] = review
                return review
        self.saved.append(review)
        return review


class FakeRejectedDraftReviewRepository:
    def __init__(self) -> None:
        self.saved: list[RejectedDraftReview] = []

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        review_id: UUID,
    ) -> RejectedDraftReview | None:
        for review in self.saved:
            if review.workspace_id == workspace_id and review.review_id == review_id:
                return review
        return None

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        review_id: UUID,
    ) -> RejectedDraftReview | None:
        return await self.get_by_id(workspace_id, review_id)

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 20,
    ) -> tuple[RejectedDraftReview, ...]:
        matches = tuple(
            review
            for review in self.saved
            if review.workspace_id == workspace_id and review.lead_id == lead_id
        )
        return matches[:limit]

    async def save(self, review: RejectedDraftReview) -> RejectedDraftReview:
        self.saved.append(review)
        return review


class FakeLLMClient:
    def __init__(
        self,
        *,
        body: str = "just checking in.",
        subject: str | None = "Quick check-in",
        confidence: float = 0.91,
        safety_flags: tuple[str, ...] = (),
    ) -> None:
        self.requests: list[LLMCompletionRequest] = []
        self._text = json.dumps(
            {
                "body": body,
                "subject": subject,
                "confidence": confidence,
                "personalization_notes": ["Used safe canonical context."],
                "safety_flags": list(safety_flags),
            }
        )

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        return LLMResult(
            text=self._text,
            model="openai/gpt-4o-mini",
            prompt_version=request.prompt_version,
            latency_ms=13,
            usage_tokens=37,
        )


class FakeClassificationLLMClient:
    def __init__(
        self,
        *,
        outcome: str = "dormant",
        confidence: float = 0.91,
        evidence: list[str] | None = None,
        summary: str = "Lead appears dormant.",
        handoff_reason_code: str | None = None,
        reengagement_not_before: str | None = None,
        reengagement_window_label: str | None = None,
        selected_track_key: str | None = None,
        track_selection_status: str | None = None,
    ) -> None:
        self.requests: list[LLMCompletionRequest] = []
        resolved_handoff_reason_code = handoff_reason_code
        if resolved_handoff_reason_code is None and outcome == "human_handoff":
            resolved_handoff_reason_code = "human_requested"
        self._text = json.dumps(
            {
                "outcome": outcome,
                "confidence": confidence,
                "evidence": evidence or ["No recent replies."],
                "summary": summary,
                "handoff_reason_code": resolved_handoff_reason_code,
                "reengagement_not_before": reengagement_not_before,
                "reengagement_window_label": reengagement_window_label,
                "selected_track_key": selected_track_key,
                "track_selection_status": track_selection_status,
            }
        )

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        return LLMResult(
            text=self._text,
            model="openai/gpt-4o-mini",
            prompt_version=request.prompt_version,
            latency_ms=13,
            usage_tokens=37,
        )


class FakeSMSProvider:
    provider_name = "twilio"

    def __init__(self, result: str | Exception = "SM123") -> None:
        self.result = result
        self.messages: list[SMSMessage] = []

    async def send(self, message: SMSMessage) -> str:
        self.messages.append(message)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeEmailProvider:
    provider_name = "sendgrid"

    def __init__(self, result: str | Exception = "msg-123") -> None:
        self.result = result
        self.messages: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> str:
        self.messages.append(message)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result
