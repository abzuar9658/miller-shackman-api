from uuid import UUID

from app.application.ports.lead_activity import (
    LeadActivityItem,
    LeadActivityKind,
    LeadActivitySummary,
)
from app.application.ports.lead_read import LeadReadConversationSummary
from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.campaigns.rejected_draft_review import RejectedDraftReview
from app.domain.conversations import CrmConversationEvent, Handoff, InboundMessage
from app.domain.identity import User, WorkspaceMembershipRole
from app.domain.leads import CanonicalLeadRecord
from app.domain.workflows import LeadWorkflow, WorkflowState, WorkflowTransition


class FakeLeadRepository:
    def __init__(self, leads: tuple[CanonicalLeadRecord, ...]) -> None:
        self._leads = {(lead.workspace_id, lead.lead_id): lead for lead in leads}

    async def get_by_id(
        self,
        workspace_id: UUID,
        lead_id: UUID,
    ) -> CanonicalLeadRecord | None:
        return self._leads.get((workspace_id, lead_id))

    async def list_for_workspace(
        self,
        workspace_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[CanonicalLeadRecord, ...]:
        return tuple(
            lead for (wid, _), lead in self._leads.items() if wid == workspace_id
        )[:limit]

    async def get_by_primary_phone(
        self,
        workspace_id: UUID,
        phone_number: str,
    ) -> CanonicalLeadRecord | None:
        normalized = _normalized_phone(phone_number)
        if normalized is None:
            return None
        for (wid, _), lead in self._leads.items():
            if wid != workspace_id or lead.primary_phone is None:
                continue
            if _normalized_phone(lead.primary_phone) == normalized:
                return lead
        return None

    async def get_by_primary_email(
        self,
        workspace_id: UUID,
        email_address: str,
    ) -> CanonicalLeadRecord | None:
        normalized = _normalized_email(email_address)
        if normalized is None:
            return None
        for (wid, _), lead in self._leads.items():
            if wid != workspace_id or lead.primary_email is None:
                continue
            if _normalized_email(lead.primary_email) == normalized:
                return lead
        return None


class FakeLeadWorkflowRepository:
    def __init__(self, workflows: tuple[LeadWorkflow, ...]) -> None:
        self._latest = {
            (workflow.workspace_id, workflow.lead_id): workflow for workflow in workflows
        }

    async def get_latest_for_lead(
        self,
        workspace_id: UUID,
        lead_id: UUID,
    ) -> LeadWorkflow | None:
        return self._latest.get((workspace_id, lead_id))

    async def get_latest_for_lead_for_update(
        self,
        workspace_id: UUID,
        lead_id: UUID,
    ) -> LeadWorkflow | None:
        return await self.get_latest_for_lead(workspace_id, lead_id)

    async def list_latest_for_workspace(
        self,
        workspace_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[LeadWorkflow, ...]:
        return tuple(
            wf for (wid, _), wf in self._latest.items() if wid == workspace_id
        )[:limit]

    async def list_paused_for_workspace(
        self,
        workspace_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[LeadWorkflow, ...]:
        return tuple(
            wf
            for (wid, _), wf in self._latest.items()
            if wid == workspace_id and wf.state == WorkflowState.PAUSED
        )[:limit]

    async def save(self, workflow: LeadWorkflow) -> LeadWorkflow:
        self._latest[(workflow.workspace_id, workflow.lead_id)] = workflow
        return workflow


class FakeWorkflowTransitionRepository:
    def __init__(self, transitions: tuple[WorkflowTransition, ...]) -> None:
        self._items = list(transitions)

    async def list_for_workflow(
        self,
        workspace_id: UUID,
        workflow_id: UUID,
        limit: int = 100,
    ) -> tuple[WorkflowTransition, ...]:
        return tuple(
            item
            for item in self._items
            if item.workspace_id == workspace_id and item.workflow_id == workflow_id
        )[:limit]

    async def append(self, transition: WorkflowTransition) -> WorkflowTransition:
        self._items.append(transition)
        return transition


class FakeInboundMessageRepository:
    def __init__(self, messages: tuple[InboundMessage, ...]) -> None:
        self._messages = messages

    async def list_lead_summaries(
        self,
        workspace_id: UUID,
        lead_ids: tuple[UUID, ...],
    ) -> tuple[LeadReadConversationSummary, ...]:
        summaries: list[LeadReadConversationSummary] = []
        for lead_id in lead_ids:
            messages = sorted(
                (
                    item
                    for item in self._messages
                    if item.workspace_id == workspace_id and item.lead_id == lead_id
                ),
                key=lambda item: (item.received_at, item.inbound_message_id),
                reverse=True,
            )
            if not messages:
                continue
            latest = messages[0]
            summaries.append(
                LeadReadConversationSummary(
                    lead_id=lead_id,
                    inbound_message_count=len(messages),
                    latest_inbound_at=latest.received_at,
                    latest_inbound_preview=_preview_inbound_text(latest.body),
                )
            )
        return tuple(summaries)

    async def list_for_lead(
        self,
        workspace_id: UUID,
        lead_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[InboundMessage, ...]:
        return tuple(
            item
            for item in self._messages
            if item.workspace_id == workspace_id and item.lead_id == lead_id
        )[:limit]


class FakeLeadActivityRepository:
    def __init__(self, items: tuple[LeadActivityItem, ...]) -> None:
        self._items = items

    async def list_summaries(
        self,
        workspace_id: UUID,
        lead_ids: tuple[UUID, ...],
    ) -> tuple[LeadActivitySummary, ...]:
        summaries: list[LeadActivitySummary] = []
        for lead_id in lead_ids:
            items = sorted(
                (
                    item
                    for item in self._items
                    if item.lead_id == lead_id
                    and item.lead_id in lead_ids
                    and _workspace_matches(item, workspace_id)
                ),
                key=lambda item: (item.occurred_at, item.activity_id),
                reverse=True,
            )
            if not items:
                continue
            latest = items[0]
            summaries.append(
                LeadActivitySummary(
                    lead_id=lead_id,
                    inbound_message_count=_count_kind(items, LeadActivityKind.INBOUND_MESSAGE),
                    outbound_message_count=_count_kind(items, LeadActivityKind.OUTBOUND_MESSAGE),
                    crm_event_count=_count_kind(items, LeadActivityKind.CRM_CONVERSATION_EVENT),
                    handoff_count=_count_kind(items, LeadActivityKind.HANDOFF),
                    latest_activity_at=latest.occurred_at,
                    latest_activity_preview=latest.preview,
                    latest_activity_kind=latest.kind,
                )
            )
        return tuple(summaries)

    async def list_for_lead(
        self,
        workspace_id: UUID,
        lead_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[LeadActivityItem, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self._items
                    if item.lead_id == lead_id and _workspace_matches(item, workspace_id)
                ),
                key=lambda item: (item.occurred_at, item.activity_id),
                reverse=True,
            )[:limit]
        )


class FakeOutboundMessageRepository:
    def __init__(self, messages: tuple[OutboundMessage, ...]) -> None:
        self._messages = messages

    async def list_for_lead(
        self,
        workspace_id: UUID,
        lead_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[OutboundMessage, ...]:
        return tuple(
            item
            for item in self._messages
            if item.workspace_id == workspace_id and item.lead_id == lead_id
        )[:limit]


class FakeRejectedDraftReviewRepository:
    def __init__(self, reviews: tuple[RejectedDraftReview, ...]) -> None:
        self._reviews = {review.review_id: review for review in reviews}

    async def get_by_id(
        self,
        workspace_id: UUID,
        review_id: UUID,
    ) -> RejectedDraftReview | None:
        review = self._reviews.get(review_id)
        if review is None or review.workspace_id != workspace_id:
            return None
        return review

    async def get_by_id_for_update(
        self,
        workspace_id: UUID,
        review_id: UUID,
    ) -> RejectedDraftReview | None:
        return await self.get_by_id(workspace_id, review_id)

    async def list_for_lead(
        self,
        workspace_id: UUID,
        lead_id: UUID,
        *,
        limit: int = 20,
    ) -> tuple[RejectedDraftReview, ...]:
        return tuple(
            item
            for item in self._reviews.values()
            if item.workspace_id == workspace_id and item.lead_id == lead_id
        )[:limit]

    async def save(self, review: RejectedDraftReview) -> RejectedDraftReview:
        self._reviews[review.review_id] = review
        return review


class FakeHandoffRepository:
    def __init__(self, handoffs: tuple[Handoff, ...]) -> None:
        self._handoffs = handoffs

    async def list_handoffs(
        self,
        workspace_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[Handoff, ...]:
        return tuple(
            item for item in self._handoffs if item.workspace_id == workspace_id
        )[:limit]

    async def list_for_lead(
        self,
        workspace_id: UUID,
        lead_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[Handoff, ...]:
        return tuple(
            item
            for item in self._handoffs
            if item.workspace_id == workspace_id and item.lead_id == lead_id
        )[:limit]


class FakeCrmConversationEventRepository:
    def __init__(self, events: tuple[CrmConversationEvent, ...]) -> None:
        self._events = events

    async def list_for_lead(
        self,
        workspace_id: UUID,
        lead_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[CrmConversationEvent, ...]:
        return tuple(
            item
            for item in self._events
            if item.workspace_id == workspace_id and item.lead_id == lead_id
        )[:limit]

    async def save(self, event: CrmConversationEvent) -> CrmConversationEvent:
        self._events = tuple(
            item
            for item in self._events
            if not (
                item.workspace_id == event.workspace_id
                and item.crm_provider == event.crm_provider
                and item.crm_activity_id == event.crm_activity_id
            )
        ) + (event,)
        return event


class FakeUserRepository:
    def __init__(self, users: dict[UUID, User]) -> None:
        self._users = users

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)

    async def get_by_email_normalized(self, email_normalized: str) -> User | None:
        return next(
            (user for user in self._users.values() if user.email_normalized == email_normalized),
            None,
        )

    async def get_active_by_workspace_email_normalized(
        self,
        workspace_id: UUID,
        email_normalized: str,
        *,
        allowed_roles: tuple[WorkspaceMembershipRole, ...],
    ) -> User | None:
        _ = (workspace_id, allowed_roles)
        return await self.get_by_email_normalized(email_normalized)

    async def save(self, user: User) -> User:
        self._users[user.user_id] = user
        return user


def _preview_inbound_text(body: str, max_length: int = 120) -> str:
    normalized = " ".join(body.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 1].rstrip()}…"


def _count_kind(
    items: tuple[LeadActivityItem, ...] | list[LeadActivityItem],
    kind: LeadActivityKind,
) -> int:
    return sum(1 for item in items if item.kind == kind)


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


def _workspace_matches(item: LeadActivityItem, workspace_id: UUID) -> bool:
    # LeadActivityItem intentionally carries lead-owned context, not workspace_id.
    # Test fixtures only contain one workspace, so this keeps the fake protocol-compatible.
    return workspace_id is not None