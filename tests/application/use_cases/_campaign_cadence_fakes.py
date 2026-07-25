import json
from uuid import UUID

from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.ports.messaging import EmailMessage, SMSMessage
from app.domain.campaigns.execution import CampaignExecutionConfig, CampaignVersionStatus
from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.campaigns.rejected_draft_review import RejectedDraftReview
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import WorkspaceContactPolicy
from app.domain.conversations import CrmConversationEvent
from app.domain.identity import Workspace
from app.domain.leads import CanonicalLeadRecord, CRMProvider
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
    def __init__(self, lead: CanonicalLeadRecord | None) -> None:
        self.lead = lead
        self.saved: list[CanonicalLeadRecord] = []
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
            if workflow.workspace_id == workspace_id
            and workflow.state == WorkflowState.PAUSED
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
