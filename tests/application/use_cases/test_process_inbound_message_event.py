import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, time
from typing import TypedDict
from uuid import UUID

from app.application.ports.crm import CanonicalLead, CRMActivity, CRMAgent
from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.services.llm.reply_classification import InboundReplyIntent
from app.application.use_cases.complete_inbound_message_crm_sync import (
    CompleteInboundMessageCRMSyncStatus,
)
from app.application.use_cases.continue_ai_conversation_after_inbound import ContinueAIStatus
from app.application.use_cases.evaluate_inbound_action import InboundAction, InboundActionReasonCode
from app.application.use_cases.process_inbound_message_event import (
    InboundMessageEvent,
    ProcessInboundMessageEventReasonCode,
    ProcessInboundMessageEventStatus,
    process_inbound_message_event,
)
from app.domain.campaigns.execution import (
    CampaignCadenceStep,
    CampaignExecutionConfig,
    CampaignVersionStatus,
)
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance import SmsComplianceState, WorkspaceContactPolicy
from app.domain.compliance.contactability import ContactChannel
from app.domain.conversations import (
    Conversation,
    ConversationStatus,
    ConversationSummary,
    Handoff,
    InboundMessage,
    WorkspaceHandoffConfig,
)
from app.domain.crm_sync import ExternalEvent, ExternalEventStatus
from app.domain.events import DomainEvent, DomainEventType
from app.domain.identity import Workspace, WorkspaceStatus
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.llm import WorkspaceLLMConfig
from app.domain.outbound_drafting import WorkspaceOutboundDraftingConfig
from app.domain.workflows import LeadWorkflow, WorkflowState
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCampaignExecutionRepository,
    FakeEmailProvider,
    FakeLeadWorkflowRepository,
    FakeOutboundMessageRepository,
    FakeSMSProvider,
    FakeWorkflowTransitionRepository,
    FakeWorkspaceContactPolicyRepository,
    FakeWorkspaceLLMConfigRepository,
    FakeWorkspaceOperationalControlRepository,
    FakeWorkspaceOutboundDraftingConfigRepository,
    FakeWorkspaceRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeTemporalSignalOutboxRepository,
)
from tests.application.use_cases.test_complete_handoff import (
    FakeHandoffCompletionRepository,
    FakeNotificationProvider,
)

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
EXTERNAL_EVENT_ID = UUID("00000000-0000-0000-0000-000000000003")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000004")
INBOUND_MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000005")
SUMMARY_ID = UUID("00000000-0000-0000-0000-000000000006")
HANDOFF_ID = UUID("00000000-0000-0000-0000-000000000007")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000008")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000009")
ENROLLMENT_ID = UUID("00000000-0000-0000-0000-000000000010")


class FakeLeadRepository:
    def __init__(self, lead: CanonicalLeadRecord | None) -> None:
        self.lead = lead

    async def get_by_id(
        self, workspace_id: WorkspaceId, lead_id: LeadId
    ) -> CanonicalLeadRecord | None:
        return self.lead

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        return self.lead

    async def get_by_crm_id(
        self,
        workspace_id: WorkspaceId,
        crm_provider: CRMProvider,
        crm_lead_id: str,
    ) -> CanonicalLeadRecord | None:
        if (
            self.lead is not None
            and self.lead.workspace_id == workspace_id
            and self.lead.crm_provider == crm_provider
            and self.lead.crm_lead_id == crm_lead_id
        ):
            return self.lead
        return None

    async def get_by_primary_phone(
        self,
        workspace_id: WorkspaceId,
        phone_number: str,
    ) -> CanonicalLeadRecord | None:
        if (
            self.lead is None
            or self.lead.workspace_id != workspace_id
            or self.lead.primary_phone is None
        ):
            return None
        requested = _normalized_phone(phone_number)
        stored = _normalized_phone(self.lead.primary_phone)
        if requested is None or stored is None:
            return None
        candidates = {requested}
        if len(requested) == 11 and requested.startswith("1"):
            candidates.add(requested[1:])
        elif len(requested) == 10:
            candidates.add(f"1{requested}")
        if stored in candidates:
            return self.lead
        return None

    async def get_by_primary_email(
        self,
        workspace_id: WorkspaceId,
        email_address: str,
    ) -> CanonicalLeadRecord | None:
        if (
            self.lead is None
            or self.lead.workspace_id != workspace_id
            or self.lead.primary_email is None
        ):
            return None
        requested = email_address.strip().lower()
        stored = self.lead.primary_email.strip().lower()
        if not requested or not stored:
            return None
        if requested == stored:
            return self.lead
        return None

    async def upsert(self, record: CanonicalLeadRecord) -> CanonicalLeadRecord:
        self.lead = record
        return record


class FakeExternalEventRepository:
    def __init__(self) -> None:
        self.events: dict[tuple[WorkspaceId, str, str], ExternalEvent] = {}

    async def get_by_provider_event_id(
        self,
        workspace_id: WorkspaceId,
        provider: str,
        provider_event_id: str,
    ) -> ExternalEvent | None:
        return self.events.get((workspace_id, provider, provider_event_id))

    async def save(self, event: ExternalEvent) -> ExternalEvent:
        self.events[(event.workspace_id, event.provider, event.provider_event_id)] = event
        return event


class FakeConversationRepository:
    def __init__(self) -> None:
        self.by_id: dict[UUID, Conversation] = {}

    async def get_latest_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> Conversation | None:
        conversations = [
            conversation
            for conversation in self.by_id.values()
            if conversation.workspace_id == workspace_id and conversation.lead_id == lead_id
        ]
        return (
            max(conversations, key=lambda conversation: conversation.updated_at)
            if conversations
            else None
        )

    async def save(self, conversation: Conversation) -> Conversation:
        self.by_id[conversation.conversation_id] = conversation
        return conversation


class FakeInboundMessageRepository:
    def __init__(self) -> None:
        self.messages: dict[tuple[WorkspaceId, str, str], InboundMessage] = {}

    async def save(self, message: InboundMessage) -> InboundMessage:
        self.messages[(message.workspace_id, message.provider, message.provider_message_id)] = (
            message
        )
        return message


class FakeConversationSummaryRepository:
    def __init__(self) -> None:
        self.saved: list[ConversationSummary] = []

    async def save(self, summary: ConversationSummary) -> ConversationSummary:
        self.saved.append(summary)
        return summary


class FakeInboundMessageCRMCompletionRepository:
    def __init__(self, record: object | None = None) -> None:
        self.record = record

    async def get_by_inbound_message_id(
        self,
        workspace_id: WorkspaceId,
        inbound_message_id: UUID,
    ) -> object | None:
        if self.record is None:
            return None
        if (
            getattr(self.record, "workspace_id", None) == workspace_id
            and getattr(self.record, "inbound_message_id", None) == inbound_message_id
        ):
            return self.record
        return None

    async def save(self, record: object) -> object:
        self.record = record
        return record


class FakeOutboundMessageCRMCompletionRepository:
    def __init__(self, record: object | None = None) -> None:
        self.record = record

    async def get_by_outbound_message_id(
        self,
        workspace_id: WorkspaceId,
        outbound_message_id: UUID,
    ) -> object | None:
        if self.record is None:
            return None
        if (
            getattr(self.record, "workspace_id", None) == workspace_id
            and getattr(self.record, "outbound_message_id", None) == outbound_message_id
        ):
            return self.record
        return None

    async def save(self, record: object) -> object:
        self.record = record
        return record


class FakeHandoffRepository:
    def __init__(self) -> None:
        self.saved: list[Handoff] = []

    async def list_handoffs(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[Handoff, ...]:
        handoffs = tuple(
            handoff for handoff in self.saved if handoff.workspace_id == workspace_id
        )
        return handoffs[:limit]

    async def get_by_id(self, workspace_id: WorkspaceId, handoff_id: UUID) -> Handoff | None:
        for handoff in self.saved:
            if handoff.workspace_id == workspace_id and handoff.handoff_id == handoff_id:
                return handoff
        return None

    async def save(self, handoff: Handoff) -> Handoff:
        self.saved.append(handoff)
        return handoff


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)




class FakeLLMClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[LLMCompletionRequest] = []

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        return LLMResult(
            text=self.text,
            model="openai/gpt-4o-mini",
            prompt_version=request.prompt_version,
            latency_ms=13,
            usage_tokens=37,
        )


class FakeWorkspaceHandoffConfigRepository:
    def __init__(self, config: WorkspaceHandoffConfig | None) -> None:
        self.config = config

    async def get_by_workspace_id(self, workspace_id: WorkspaceId) -> WorkspaceHandoffConfig | None:
        if self.config is not None and self.config.workspace_id == workspace_id:
            return self.config
        return None

    async def save(self, config: WorkspaceHandoffConfig) -> WorkspaceHandoffConfig:
        self.config = config
        return config


class FakeCRMClient:
    supports_custom_fields = True
    supports_tags = True
    supports_notes = True
    supports_webhooks = False

    def __init__(
        self,
        *,
        lead_updated_at: datetime | None = None,
        activity_timestamps: tuple[datetime, ...] = (),
        assigned_agent: CRMAgent | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.notes: list[str] = []
        self.note_subjects: list[str | None] = []
        self.tags: list[str] = []
        self.custom_field_updates: list[dict[str, str]] = []
        self._lead_updated_at = lead_updated_at
        self._activity_timestamps = activity_timestamps
        self._assigned_agent = assigned_agent

    async def validate_connection(self, workspace_id: WorkspaceId) -> bool:
        return True

    async def get_lead(self, workspace_id: WorkspaceId, crm_lead_id: str) -> CanonicalLead | None:
        self.calls.append("get_lead")
        return CanonicalLead(
            workspace_id=workspace_id,
            crm_lead_id=crm_lead_id,
            first_name="Jamie",
            last_name="Lead",
            email="lead@example.com",
            phone="+15555550123",
            updated_at=self._lead_updated_at,
        )

    async def search_leads(
        self,
        workspace_id: WorkspaceId,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[CanonicalLead]:
        return []

    async def get_recent_activity(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
        limit: int = 50,
    ) -> list[CRMActivity]:
        self.calls.append("get_recent_activity")
        return [
            CRMActivity(
                crm_activity_id=f"activity-{index}",
                activity_type="Note",
                timestamp=timestamp,
                content="recent activity",
            )
            for index, timestamp in enumerate(self._activity_timestamps, start=1)
        ]

    async def get_assigned_agent(
        self, workspace_id: WorkspaceId, crm_lead_id: str
    ) -> CRMAgent | None:
        self.calls.append("get_assigned_agent")
        return self._assigned_agent

    async def add_note(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
        content: str,
        subject: str | None = None,
    ) -> None:
        self.calls.append("add_note")
        self.notes.append(content)
        self.note_subjects.append(subject)

    async def add_tag(self, workspace_id: WorkspaceId, crm_lead_id: str, tag: str) -> None:
        self.calls.append("add_tag")
        self.tags.append(tag)

    async def remove_tag(self, workspace_id: WorkspaceId, crm_lead_id: str, tag: str) -> None:
        return None

    async def update_custom_fields(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
        fields: dict[str, str],
    ) -> None:
        self.calls.append("update_custom_fields")
        self.custom_field_updates.append(dict(fields))

    async def subscribe_to_events(self, workspace_id: WorkspaceId, webhook_url: str) -> None:
        return None

    async def fetch_resource_by_uri(
        self, workspace_id: WorkspaceId, uri: str
    ) -> dict[str, object] | None:
        return None


def _normalized_phone(phone_number: str | None) -> str | None:
    if phone_number is None:
        return None
    digits_only = "".join(character for character in phone_number if character.isdigit())
    return digits_only or None


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="long_term_nurture",
        assigned_agent_crm_id="agent-99",
        has_accountable_owner=True,
        primary_phone="+15555550123",
        has_phone=True,
        has_sms_capable_phone=True,
        phone_count=1,
    )


def _event(
    payload_redacted: Mapping[str, object] | None = None,
    body: str = "Can an agent call me today?",
    channel: ContactChannel = ContactChannel.SMS,
) -> InboundMessageEvent:
    return InboundMessageEvent(
        workspace_id=WORKSPACE_ID,
        provider=CRMProvider.FOLLOW_UP_BOSS.value,
        provider_event_id="evt-1",
        provider_message_id="msg-1",
        crm_lead_id="crm-123",
        channel=channel,
        body=body,
        received_at=NOW,
        payload_redacted=payload_redacted or {"event": "redacted"},
    )


def _workspace_handoff_config() -> WorkspaceHandoffConfig:
    return WorkspaceHandoffConfig(
        workspace_id=WORKSPACE_ID,
        fallback_recipient_email="fallback@example.com",
        crm_handoff_tag="human_handoff_required",
        crm_review_tag="needs_agent_review",
        crm_custom_fields={"handoff_status": "required"},
    )


def _workspace_handoff_config_with_snapshot_fields() -> WorkspaceHandoffConfig:
    return replace(
        _workspace_handoff_config(),
        crm_snapshot_summary_field="ai_summary",
        crm_snapshot_status_field="ai_status",
        crm_snapshot_latest_inbound_field="ai_latest_inbound",
        crm_snapshot_latest_outbound_field="ai_latest_outbound",
        crm_snapshot_last_activity_at_field="ai_last_activity_at",
    )


def _workflow() -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="workflow-123",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=WorkflowState.WAITING_FOR_RESPONSE,
        last_transition_at=NOW,
        state_version=3,
        created_at=NOW,
        updated_at=NOW,
    )


def _conversation(*, ai_interaction_count: int = 0) -> Conversation:
    return Conversation(
        conversation_id=CONVERSATION_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        status=ConversationStatus.ACTIVE_AI,
        ai_interaction_count=ai_interaction_count,
        last_message_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _classification_json(
    *,
    intent: str,
    asks_for_human: bool | None = None,
    shows_buying_interest: bool | None = None,
    shows_selling_interest: bool | None = None,
    asks_property_or_advice: bool = False,
    opt_out_detected: bool = False,
    confidence: float = 0.91,
    summary_text: str = "Lead asked for a human callback.",
) -> str:
    if asks_for_human is None:
        asks_for_human = intent == "human_requested"
    if shows_buying_interest is None:
        shows_buying_interest = intent == "high_interest"
    if shows_selling_interest is None:
        shows_selling_interest = intent == "seller_interest"
    return json.dumps(
        {
            "intent": intent,
            "confidence": confidence,
            "asks_for_human": asks_for_human,
            "shows_buying_interest": shows_buying_interest,
            "shows_selling_interest": shows_selling_interest,
            "asks_property_or_advice": asks_property_or_advice,
            "opt_out_detected": opt_out_detected,
            "summary_text": summary_text,
            "preferences": {"timeline": "today"},
        },
    )


def _draft_json(*, body: str = "Thanks for your question! Your agent will follow up.") -> str:
    return json.dumps(
        {
            "body": body,
            "subject": "Quick follow-up",
            "confidence": 0.92,
            "personalization_notes": ["Acknowledged the lead's question."],
            "safety_flags": [],
        },
    )


class _ContinueAIDependencies(TypedDict):
    lead_repository: FakeLeadRepository
    external_event_repository: FakeExternalEventRepository
    conversation_repository: FakeConversationRepository
    inbound_message_repository: FakeInboundMessageRepository
    conversation_summary_repository: FakeConversationSummaryRepository
    handoff_repository: FakeHandoffRepository
    crm_client: FakeCRMClient
    inbound_message_crm_completion_repository: FakeInboundMessageCRMCompletionRepository
    outbound_message_crm_completion_repository: FakeOutboundMessageCRMCompletionRepository
    lead_workflow_repository: FakeLeadWorkflowRepository
    workflow_transition_repository: FakeWorkflowTransitionRepository
    workspace_repository: FakeWorkspaceRepository
    workspace_contact_policy_repository: FakeWorkspaceContactPolicyRepository
    workspace_llm_config_repository: FakeWorkspaceLLMConfigRepository
    workspace_outbound_drafting_config_repository: FakeWorkspaceOutboundDraftingConfigRepository
    workspace_operational_control_repository: FakeWorkspaceOperationalControlRepository
    campaign_execution_repository: FakeCampaignExecutionRepository
    message_repository: FakeOutboundMessageRepository
    sms_provider: FakeSMSProvider
    email_provider: FakeEmailProvider


class _FakeLLMClientForContinuation:
    def __init__(self, classification_text: str, draft_text: str) -> None:
        self.classification_text = classification_text
        self.draft_text = draft_text
        self.requests: list[LLMCompletionRequest] = []

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        if "draft_outbound_real_estate_lead_follow_up" in request.prompt:
            return LLMResult(
                text=self.draft_text,
                model="openai/gpt-4o-mini",
                prompt_version=request.prompt_version,
                latency_ms=13,
                usage_tokens=37,
            )
        return LLMResult(
            text=self.classification_text,
            model="openai/gpt-4o-mini",
            prompt_version=request.prompt_version,
            latency_ms=13,
            usage_tokens=37,
        )


def _workspace() -> Workspace:
    return Workspace(
        workspace_id=WORKSPACE_ID,
        name="Test Brokerage",
        status=WorkspaceStatus.ACTIVE,
        default_timezone="America/Los_Angeles",
        created_at=NOW,
        updated_at=NOW,
    )


def _workspace_contact_policy(
    *, sms_compliance_state: SmsComplianceState = SmsComplianceState.APPROVED
) -> WorkspaceContactPolicy:
    return WorkspaceContactPolicy(
        workspace_id=WORKSPACE_ID,
        sms_compliance_state=sms_compliance_state,
        quiet_hours_enabled=False,
    )


def _campaign_execution_config(
    *, channel: ContactChannel = ContactChannel.SMS
) -> CampaignExecutionConfig:
    version_id = UUID("60000000-0000-0000-0000-000000000002")
    step_id = UUID("60000000-0000-0000-0000-000000000001")
    return CampaignExecutionConfig(
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=version_id,
        workspace_id=WORKSPACE_ID,
        campaign_name="Test Campaign",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(channel,),
        daily_start_cap=100,
        dormant_threshold_days=60,
        quiet_hours_start=time(22, 0),
        quiet_hours_end=time(10, 0),
        timezone="America/Los_Angeles",
        sms_compliance_required=True,
        preflight_digest_enabled=False,
        crm_enrollment_tag="ai-nurture",
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(
            CampaignCadenceStep(
                cadence_step_id=step_id,
                workspace_id=WORKSPACE_ID,
                campaign_version_id=version_id,
                step_order=1,
                channel=channel,
                delay_hours=24,
                message_goal="Check in and re-engage the lead.",
                template_key="initial_check_in",
                max_attempts=1,
                created_at=NOW,
            ),
        ),
        created_at=NOW,
        published_at=NOW,
    )


def _continue_ai_dependencies(
    *,
    workflow: LeadWorkflow,
    external_event_repository: FakeExternalEventRepository | None = None,
    sms_compliance_state: SmsComplianceState = SmsComplianceState.APPROVED,
    channel: ContactChannel = ContactChannel.SMS,
) -> _ContinueAIDependencies:
    crm_client = FakeCRMClient()
    return {
        "lead_repository": FakeLeadRepository(_lead()),
        "external_event_repository": external_event_repository or FakeExternalEventRepository(),
        "conversation_repository": FakeConversationRepository(),
        "inbound_message_repository": FakeInboundMessageRepository(),
        "conversation_summary_repository": FakeConversationSummaryRepository(),
        "handoff_repository": FakeHandoffRepository(),
        "crm_client": crm_client,
        "inbound_message_crm_completion_repository": FakeInboundMessageCRMCompletionRepository(),
        "outbound_message_crm_completion_repository": FakeOutboundMessageCRMCompletionRepository(),
        "lead_workflow_repository": _workflow_repository(workflow),
        "workflow_transition_repository": FakeWorkflowTransitionRepository(),
        "workspace_repository": FakeWorkspaceRepository(_workspace()),
        "workspace_contact_policy_repository": FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy(sms_compliance_state=sms_compliance_state)
        ),
        "workspace_llm_config_repository": FakeWorkspaceLLMConfigRepository(),
        "workspace_outbound_drafting_config_repository": (
            FakeWorkspaceOutboundDraftingConfigRepository(
                WorkspaceOutboundDraftingConfig(workspace_id=WORKSPACE_ID)
            )
        ),
        "workspace_operational_control_repository": FakeWorkspaceOperationalControlRepository(),
        "campaign_execution_repository": FakeCampaignExecutionRepository(
            _campaign_execution_config(channel=channel)
        ),
        "message_repository": FakeOutboundMessageRepository(),
        "sms_provider": FakeSMSProvider(),
        "email_provider": FakeEmailProvider(),
    }


def _workflow_repository(workflow: LeadWorkflow) -> FakeLeadWorkflowRepository:
    repository = FakeLeadWorkflowRepository()
    repository.workflows[workflow.workflow_id] = workflow
    repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow
    return repository


async def test_returns_duplicate_when_external_event_already_exists() -> None:
    lead_repository = FakeLeadRepository(_lead())
    external_events = FakeExternalEventRepository()
    existing = ExternalEvent(
        external_event_id=EXTERNAL_EVENT_ID,
        workspace_id=WORKSPACE_ID,
        provider=CRMProvider.FOLLOW_UP_BOSS.value,
        event_type="inbound_message.received",
        provider_event_id="evt-1",
        crm_lead_id="crm-123",
        lead_id=LEAD_ID,
        received_at=NOW,
        processed_at=NOW,
        status=ExternalEventStatus.PROCESSED,
        payload_redacted={"event": "redacted"},
        failure_reason=None,
        created_at=NOW,
        updated_at=NOW,
    )
    await external_events.save(existing)
    llm = FakeLLMClient(
        _classification_json(intent="human_requested")
    )

    result = await process_inbound_message_event(
        event=_event(),
        lead_repository=lead_repository,
        external_event_repository=external_events,
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=llm,
        now=NOW,
    )

    assert result.status == ProcessInboundMessageEventStatus.DUPLICATE
    assert result.reasons == (ProcessInboundMessageEventReasonCode.DUPLICATE_EVENT,)
    assert llm.requests == []


async def test_creates_handoff_for_human_request() -> None:
    conversations = FakeConversationRepository()
    inbound_messages = FakeInboundMessageRepository()
    summaries = FakeConversationSummaryRepository()
    handoffs = FakeHandoffRepository()
    event_bus = FakeEventBus()

    result = await process_inbound_message_event(
        event=_event(),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=conversations,
        inbound_message_repository=inbound_messages,
        conversation_summary_repository=summaries,
        handoff_repository=handoffs,
        llm_client=FakeLLMClient(
            _classification_json(
                intent="human_requested",
            ),
        ),
        now=NOW,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
        summary_id_factory=lambda: SUMMARY_ID,
        handoff_id_factory=lambda: HANDOFF_ID,
        event_bus=event_bus,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.HUMAN_HANDOFF
    assert result.inbound_action_reason == InboundActionReasonCode.HUMAN_REQUESTED
    assert result.handoff_required is True
    assert result.handoff_id == HANDOFF_ID
    assert result.conversation_id == CONVERSATION_ID
    assert result.inbound_message_id == INBOUND_MESSAGE_ID
    assert handoffs.saved[0].assigned_agent_crm_id == "agent-99"
    assert handoffs.saved[0].reason_code.value == "human_requested"
    assert summaries.saved[0].summary_id == SUMMARY_ID
    assert conversations.by_id[CONVERSATION_ID].status.value == "human_handoff"
    assert [event.event_type for event in event_bus.events] == [
        DomainEventType.MESSAGE_RECEIVED,
        DomainEventType.HANDOFF_CREATED,
    ]
    assert event_bus.events[1].payload["handoff_id"] == str(HANDOFF_ID)


async def test_creates_handoff_for_property_or_advice_question_using_structured_evidence() -> None:
    conversations = FakeConversationRepository()
    handoffs = FakeHandoffRepository()

    result = await process_inbound_message_event(
        event=_event(),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=conversations,
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=handoffs,
        llm_client=FakeLLMClient(
            _classification_json(
                intent="general_reply",
                asks_property_or_advice=True,
                summary_text="Lead asked about financing for a specific listing.",
            )
        ),
        now=NOW,
        handoff_id_factory=lambda: HANDOFF_ID,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.HUMAN_HANDOFF
    assert result.inbound_action_reason == InboundActionReasonCode.SPECIFIC_PROPERTY_OR_ADVICE
    assert result.handoff_required is True
    assert handoffs.saved[0].reason_code.value == "specific_property_or_advice"
    assert conversations.by_id[next(iter(conversations.by_id))].status.value == "human_handoff"


async def test_uses_workspace_llm_model_for_classification() -> None:
    llm = FakeLLMClient(
        _classification_json(intent="human_requested")
    )

    await process_inbound_message_event(
        event=_event(),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=llm,
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(
            WorkspaceLLMConfig(
                workspace_id=WORKSPACE_ID,
                openrouter_model="openai/gpt-4.1-mini",
            )
        ),
        default_openrouter_model="openai/gpt-4o-mini",
        now=NOW,
    )

    assert llm.requests[0].model == "openai/gpt-4.1-mini"


async def test_processes_opt_out_without_handoff() -> None:
    conversations = FakeConversationRepository()
    handoffs = FakeHandoffRepository()

    result = await process_inbound_message_event(
        event=_event(),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=conversations,
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=handoffs,
        llm_client=FakeLLMClient(
            _classification_json(
                intent="opt_out",
                opt_out_detected=True,
                summary_text="Lead opted out of automated outreach.",
            ),
        ),
        now=NOW,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.SUPPRESS
    assert result.inbound_action_reason == InboundActionReasonCode.OPT_OUT_DETECTED
    assert result.opt_out_detected is True
    assert result.handoff_id is None
    assert handoffs.saved == []
    assert conversations.by_id[CONVERSATION_ID].status.value == "paused"


async def test_returns_processed_with_classification_rejection_reason() -> None:
    result = await process_inbound_message_event(
        event=_event(),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="general_reply",
                confidence=0.2,
                summary_text="Lead replied but confidence is low.",
            ),
        ),
        now=NOW,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.PAUSE_FOR_REVIEW
    assert result.inbound_action_reason == InboundActionReasonCode.CLASSIFICATION_REJECTED
    assert result.reasons == (ProcessInboundMessageEventReasonCode.CLASSIFICATION_REJECTED,)


async def test_provider_owned_inbound_reply_syncs_back_to_crm_after_refresh() -> None:
    crm_client = FakeCRMClient(activity_timestamps=(datetime(2026, 7, 8, 12, 5, tzinfo=UTC),))
    crm_sync_repo = FakeInboundMessageCRMCompletionRepository()

    result = await process_inbound_message_event(
        event=InboundMessageEvent(
            workspace_id=WORKSPACE_ID,
            provider="twilio",
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            provider_event_id="evt-twilio-1",
            provider_message_id="SM123",
            crm_lead_id="crm-123",
            channel=ContactChannel.SMS,
            body="Please stop texting me and have an agent call.",
            received_at=NOW,
        ),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="human_requested",
                summary_text="Lead asked for a human callback.",
            ),
        ),
        crm_client=crm_client,
        inbound_message_crm_completion_repository=crm_sync_repo,
        now=NOW,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.crm_sync_status == CompleteInboundMessageCRMSyncStatus.COMPLETED
    assert crm_client.calls == ["get_lead", "get_recent_activity", "add_note"]
    assert crm_client.notes
    assert crm_client.note_subjects == ["AI INBOUND · SMS"]
    assert "CRM updates detected: yes" in crm_client.notes[0]
    assert getattr(crm_sync_repo.record, "completed_at", None) == NOW


async def test_follow_up_boss_sourced_inbound_reply_does_not_write_back_to_crm() -> None:
    crm_client = FakeCRMClient()

    result = await process_inbound_message_event(
        event=_event(),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(intent="human_requested"),
        ),
        crm_client=crm_client,
        inbound_message_crm_completion_repository=FakeInboundMessageCRMCompletionRepository(),
        now=NOW,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.crm_sync_status is None
    assert crm_client.calls == []


async def test_follow_up_boss_sourced_inbound_updates_snapshot_without_duplicate_note() -> None:
    crm_client = FakeCRMClient()

    result = await process_inbound_message_event(
        event=_event(),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="human_requested",
                summary_text="Lead asked for a human callback.",
            ),
        ),
        crm_client=crm_client,
        inbound_message_crm_completion_repository=FakeInboundMessageCRMCompletionRepository(),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            _workspace_handoff_config_with_snapshot_fields()
        ),
        now=NOW,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.crm_sync_status == CompleteInboundMessageCRMSyncStatus.COMPLETED
    assert crm_client.calls == ["get_lead", "get_recent_activity", "update_custom_fields"]
    assert crm_client.notes == []
    assert crm_client.custom_field_updates == [
        {
            "ai_summary": "Lead asked for a human callback.",
            "ai_status": "human_handoff_required",
            "ai_latest_inbound": "Can an agent call me today?",
            "ai_last_activity_at": NOW.isoformat(),
        }
    ]


async def test_follow_up_boss_sourced_unclear_inbound_applies_review_tag_in_crm() -> None:
    crm_client = FakeCRMClient()

    result = await process_inbound_message_event(
        event=_event(),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="unclear",
                summary_text="Lead replied with an ambiguous message.",
            ),
        ),
        crm_client=crm_client,
        inbound_message_crm_completion_repository=FakeInboundMessageCRMCompletionRepository(),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            _workspace_handoff_config()
        ),
        now=NOW,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.PAUSE_FOR_REVIEW
    assert result.inbound_action_reason == InboundActionReasonCode.UNCLEAR_INTENT
    assert result.review_tag_applied is True
    assert crm_client.calls == ["get_lead", "get_recent_activity", "add_tag"]
    assert crm_client.tags == ["needs_agent_review"]


async def test_unclear_inbound_sends_review_notification_to_assigned_agent() -> None:
    crm_client = FakeCRMClient(
        assigned_agent=CRMAgent(
            crm_agent_id="agent-99", name="Ada Agent", email="agent@example.com"
        )
    )
    notification_provider = FakeNotificationProvider()

    result = await process_inbound_message_event(
        event=_event(body="Hmm not sure what I want yet"),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="unclear",
                summary_text="Lead reply is ambiguous.",
            ),
        ),
        crm_client=crm_client,
        inbound_message_crm_completion_repository=FakeInboundMessageCRMCompletionRepository(),
        notification_provider=notification_provider,
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            _workspace_handoff_config()
        ),
        now=NOW,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.PAUSE_FOR_REVIEW
    assert result.review_notification_sent is True
    assert result.review_notification_recipient == "agent@example.com"
    assert result.review_notification_failure_reason is None
    assert len(notification_provider.review_notifications) == 1
    notification = notification_provider.review_notifications[0]
    assert notification.recipient_id == "agent-99"
    assert notification.recipient_destination == "agent@example.com"
    assert notification.review_reason == InboundActionReasonCode.UNCLEAR_INTENT.value


async def test_unclear_inbound_review_notification_uses_fallback_when_no_agent() -> None:
    crm_client = FakeCRMClient()
    notification_provider = FakeNotificationProvider()

    result = await process_inbound_message_event(
        event=_event(body="Hmm not sure what I want yet"),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="unclear",
                summary_text="Lead reply is ambiguous.",
            ),
        ),
        crm_client=crm_client,
        inbound_message_crm_completion_repository=FakeInboundMessageCRMCompletionRepository(),
        notification_provider=notification_provider,
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            _workspace_handoff_config()
        ),
        now=NOW,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.PAUSE_FOR_REVIEW
    assert result.review_notification_sent is True
    assert result.review_notification_recipient == "fallback@example.com"
    assert notification_provider.review_notifications[0].recipient_id == "fallback@example.com"


async def test_unclear_inbound_records_review_notification_failure_when_no_destination() -> None:
    crm_client = FakeCRMClient()
    notification_provider = FakeNotificationProvider()

    result = await process_inbound_message_event(
        event=_event(body="Hmm not sure what I want yet"),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="unclear",
                summary_text="Lead reply is ambiguous.",
            ),
        ),
        crm_client=crm_client,
        inbound_message_crm_completion_repository=FakeInboundMessageCRMCompletionRepository(),
        notification_provider=notification_provider,
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            WorkspaceHandoffConfig(workspace_id=WORKSPACE_ID)
        ),
        now=NOW,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.PAUSE_FOR_REVIEW
    assert result.review_notification_sent is False
    assert result.review_notification_failure_reason == "missing_notification_destination"
    assert notification_provider.review_notifications == []


async def test_continue_ai_does_not_send_review_notification() -> None:
    crm_client = FakeCRMClient()
    notification_provider = FakeNotificationProvider()

    result = await process_inbound_message_event(
        event=InboundMessageEvent(
            workspace_id=WORKSPACE_ID,
            provider="twilio",
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            provider_event_id="evt-general-1",
            provider_message_id="SMGENERAL1",
            crm_lead_id="crm-123",
            channel=ContactChannel.SMS,
            body="Thanks, maybe later this month.",
            received_at=NOW,
        ),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="general_reply",
                summary_text="Lead replied generally and may want follow-up later.",
            )
        ),
        crm_client=crm_client,
        inbound_message_crm_completion_repository=FakeInboundMessageCRMCompletionRepository(),
        notification_provider=notification_provider,
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            _workspace_handoff_config()
        ),
        now=NOW,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.CONTINUE_AI
    assert result.review_notification_sent is False
    assert notification_provider.review_notifications == []


async def test_general_reply_returns_continue_ai_decision_without_review_tag() -> None:
    crm_client = FakeCRMClient()

    result = await process_inbound_message_event(
        event=InboundMessageEvent(
            workspace_id=WORKSPACE_ID,
            provider="twilio",
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            provider_event_id="evt-general-1",
            provider_message_id="SMGENERAL1",
            crm_lead_id="crm-123",
            channel=ContactChannel.SMS,
            body="Thanks, maybe later this month.",
            received_at=NOW,
        ),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="general_reply",
                summary_text="Lead replied generally and may want follow-up later.",
            )
        ),
        crm_client=crm_client,
        inbound_message_crm_completion_repository=FakeInboundMessageCRMCompletionRepository(),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            _workspace_handoff_config()
        ),
        now=NOW,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.CONTINUE_AI
    assert result.inbound_action_reason == InboundActionReasonCode.GENERAL_REPLY
    assert result.review_tag_applied is False
    assert crm_client.calls == ["get_lead", "get_recent_activity", "add_note"]


async def test_explicit_sms_opt_out_is_applied_even_when_llm_rejects() -> None:
    lead_repository = FakeLeadRepository(_lead())

    result = await process_inbound_message_event(
        event=InboundMessageEvent(
            workspace_id=WORKSPACE_ID,
            provider="twilio",
            provider_event_id="SMSTOP1",
            provider_message_id="SMSTOP1",
            crm_lead_id="crm-123",
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            channel=ContactChannel.SMS,
            body="STOP",
            received_at=NOW,
        ),
        lead_repository=lead_repository,
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="general_reply",
                confidence=0.10,
                summary_text="Lead replied.",
            )
        ),
        now=NOW,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.intent == InboundReplyIntent.OPT_OUT
    assert result.opt_out_detected is True
    assert result.reasons == ()
    assert lead_repository.lead is not None
    assert lead_repository.lead.sms_opted_out is True


async def test_explicit_email_unsubscribe_is_applied_even_when_llm_rejects() -> None:
    lead_repository = FakeLeadRepository(_lead())

    result = await process_inbound_message_event(
        event=InboundMessageEvent(
            workspace_id=WORKSPACE_ID,
            provider="sendgrid",
            provider_event_id="email-1",
            provider_message_id="email-1",
            crm_lead_id="crm-123",
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            channel=ContactChannel.EMAIL,
            body="unsubscribe",
            received_at=NOW,
        ),
        lead_repository=lead_repository,
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="general_reply",
                confidence=0.10,
                summary_text="Lead replied.",
            )
        ),
        now=NOW,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.intent == InboundReplyIntent.OPT_OUT
    assert result.opt_out_detected is True
    assert result.reasons == ()
    assert lead_repository.lead is not None
    assert lead_repository.lead.email_unsubscribed is True


async def test_enqueues_inbound_processed_temporal_signal_when_workflow_exists() -> None:
    temporal_signal_outbox_repository = FakeTemporalSignalOutboxRepository()
    lead_workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow()
    lead_workflow_repository.workflows[workflow.workflow_id] = workflow
    lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)] = workflow

    await process_inbound_message_event(
        event=_event(),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(intent="human_requested")
        ),
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            _workspace_handoff_config()
        ),
        now=NOW,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
        handoff_id_factory=lambda: HANDOFF_ID,
    )


async def test_continue_ai_sends_outbound_sms_and_returns_to_waiting_for_response() -> None:
    workflow = _workflow()
    dependencies = _continue_ai_dependencies(workflow=workflow)
    conversation_repository = dependencies["conversation_repository"]
    crm_client = dependencies["crm_client"]
    lead_workflow_repository = dependencies["lead_workflow_repository"]
    workflow_transition_repository = dependencies["workflow_transition_repository"]
    sms_provider = dependencies["sms_provider"]
    email_provider = dependencies["email_provider"]

    result = await process_inbound_message_event(
        event=_event(body="How much are your services?"),
        llm_client=_FakeLLMClientForContinuation(
            classification_text=_classification_json(
                intent="general_reply",
                summary_text="Lead asked about service pricing.",
            ),
            draft_text=_draft_json(),
        ),
        now=NOW,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
        **dependencies,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.CONTINUE_AI
    assert result.continue_ai_status == ContinueAIStatus.SENT
    assert result.continue_ai_outbound_message_id is not None
    assert result.continue_ai_provider_message_id == "SM123"
    assert len(sms_provider.messages) == 1
    assert len(email_provider.messages) == 0
    assert len(workflow_transition_repository.transitions) == 2
    final_workflow = lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    final_conversation = conversation_repository.by_id[CONVERSATION_ID]
    assert final_workflow.state == WorkflowState.WAITING_FOR_RESPONSE
    assert final_conversation.ai_interaction_count == 1
    assert final_conversation.status == ConversationStatus.ACTIVE_AI
    assert len(crm_client.notes) == 1
    assert crm_client.note_subjects == ["AI OUTBOUND · SMS"]
    assert "AI OUTBOUND · SMS" in crm_client.notes[0]


async def test_continue_ai_sends_outbound_email_and_returns_to_waiting_for_response() -> None:
    workflow = _workflow()
    dependencies = _continue_ai_dependencies(workflow=workflow, channel=ContactChannel.EMAIL)
    conversation_repository = dependencies["conversation_repository"]
    lead_workflow_repository = dependencies["lead_workflow_repository"]
    workflow_transition_repository = dependencies["workflow_transition_repository"]
    sms_provider = dependencies["sms_provider"]
    email_provider = dependencies["email_provider"]

    lead = _lead()
    lead = replace(
        lead,
        primary_email="lead@example.com",
        has_email=True,
        email_count=1,
    )
    dependencies["lead_repository"] = FakeLeadRepository(lead)

    result = await process_inbound_message_event(
        event=_event(
            body="How much are your services?",
            channel=ContactChannel.EMAIL,
        ),
        llm_client=_FakeLLMClientForContinuation(
            classification_text=_classification_json(
                intent="general_reply",
                summary_text="Lead asked about service pricing.",
            ),
            draft_text=_draft_json(),
        ),
        now=NOW,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
        **dependencies,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.CONTINUE_AI
    assert result.continue_ai_status == ContinueAIStatus.SENT
    assert result.continue_ai_outbound_message_id is not None
    assert result.continue_ai_provider_message_id == "msg-123"
    assert len(sms_provider.messages) == 0
    assert len(email_provider.messages) == 1
    assert len(workflow_transition_repository.transitions) == 2
    final_workflow = lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    final_conversation = conversation_repository.by_id[CONVERSATION_ID]
    assert final_workflow.state == WorkflowState.WAITING_FOR_RESPONSE
    assert final_conversation.ai_interaction_count == 1
    assert final_conversation.status == ConversationStatus.ACTIVE_AI


async def test_continue_ai_pauses_when_turn_cap_is_reached() -> None:
    workflow = _workflow()
    dependencies = _continue_ai_dependencies(workflow=workflow)
    conversation_repository = dependencies["conversation_repository"]
    lead_workflow_repository = dependencies["lead_workflow_repository"]
    workflow_transition_repository = dependencies["workflow_transition_repository"]
    sms_provider = dependencies["sms_provider"]
    email_provider = dependencies["email_provider"]
    await conversation_repository.save(_conversation(ai_interaction_count=5))

    result = await process_inbound_message_event(
        event=_event(body="How much are your services?"),
        llm_client=_FakeLLMClientForContinuation(
            classification_text=_classification_json(
                intent="general_reply",
                summary_text="Lead asked about service pricing.",
            ),
            draft_text=_draft_json(),
        ),
        now=NOW,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
        **dependencies,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.CONTINUE_AI
    assert result.continue_ai_status == ContinueAIStatus.BLOCKED
    assert result.continue_ai_pause_reason == "ai_continuation_turn_cap_reached"
    assert len(sms_provider.messages) == 0
    assert len(email_provider.messages) == 0
    assert len(workflow_transition_repository.transitions) == 1
    final_workflow = lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    final_conversation = conversation_repository.by_id[CONVERSATION_ID]
    assert final_workflow.state == WorkflowState.PAUSED
    assert final_conversation.ai_interaction_count == 5
    assert final_conversation.status == ConversationStatus.PAUSED


async def test_continue_ai_blocks_when_sms_compliance_is_not_approved() -> None:
    workflow = _workflow()
    dependencies = _continue_ai_dependencies(
        workflow=workflow, sms_compliance_state=SmsComplianceState.NOT_APPROVED
    )
    conversation_repository = dependencies["conversation_repository"]
    lead_workflow_repository = dependencies["lead_workflow_repository"]
    workflow_transition_repository = dependencies["workflow_transition_repository"]
    sms_provider = dependencies["sms_provider"]
    email_provider = dependencies["email_provider"]

    result = await process_inbound_message_event(
        event=_event(body="How much are your services?"),
        llm_client=_FakeLLMClientForContinuation(
            classification_text=_classification_json(
                intent="general_reply",
                summary_text="Lead asked about service pricing.",
            ),
            draft_text=_draft_json(),
        ),
        now=NOW,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
        **dependencies,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.CONTINUE_AI
    assert result.continue_ai_status == ContinueAIStatus.BLOCKED
    assert result.continue_ai_pause_reason == "ai_continuation_planning_blocked"
    assert len(sms_provider.messages) == 0
    assert len(email_provider.messages) == 0
    assert len(workflow_transition_repository.transitions) == 2
    final_workflow = lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    final_conversation = conversation_repository.by_id[CONVERSATION_ID]
    assert final_workflow.state == WorkflowState.PAUSED
    assert final_conversation.ai_interaction_count == 0
    assert final_conversation.status == ConversationStatus.PAUSED


async def test_continue_ai_falls_back_to_paused_when_dependencies_missing() -> None:
    lead_workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow()
    lead_workflow_repository.workflows[workflow.workflow_id] = workflow
    lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)] = workflow
    workflow_transition_repository = FakeWorkflowTransitionRepository()

    result = await process_inbound_message_event(
        event=_event(body="How much are your services?"),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="general_reply",
                summary_text="Lead asked about service pricing.",
            )
        ),
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=NOW,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.CONTINUE_AI
    assert result.continue_ai_status is None
    final_workflow = lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert final_workflow.state == WorkflowState.PAUSED


async def test_duplicate_inbound_event_does_not_send_duplicate_continuation() -> None:
    workflow = _workflow()
    external_events = FakeExternalEventRepository()
    existing = ExternalEvent(
        external_event_id=EXTERNAL_EVENT_ID,
        workspace_id=WORKSPACE_ID,
        provider=CRMProvider.FOLLOW_UP_BOSS.value,
        event_type=DomainEventType.MESSAGE_RECEIVED,
        provider_event_id="evt-1",
        crm_lead_id="crm-123",
        lead_id=None,
        received_at=NOW,
        processed_at=NOW,
        status=ExternalEventStatus.PROCESSED,
        payload_redacted={"event": "redacted"},
        failure_reason=None,
        created_at=NOW,
        updated_at=NOW,
    )
    await external_events.save(existing)

    dependencies = _continue_ai_dependencies(
        workflow=workflow, external_event_repository=external_events
    )
    lead_workflow_repository = dependencies["lead_workflow_repository"]
    sms_provider = dependencies["sms_provider"]

    result = await process_inbound_message_event(
        event=_event(body="How much are your services?"),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="general_reply",
                summary_text="Lead asked about service pricing.",
            )
        ),
        now=NOW,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
        **dependencies,
    )

    assert result.status == ProcessInboundMessageEventStatus.DUPLICATE
    assert result.continue_ai_status is None
    assert len(sms_provider.messages) == 0
    final_workflow = lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert final_workflow.state == WorkflowState.WAITING_FOR_RESPONSE



async def test_processing_audit_persisted_for_continue_ai_success() -> None:
    workflow = _workflow()
    external_events = FakeExternalEventRepository()
    dependencies = _continue_ai_dependencies(
        workflow=workflow, external_event_repository=external_events
    )

    result = await process_inbound_message_event(
        event=_event(body="How much are your services?"),
        llm_client=_FakeLLMClientForContinuation(
            classification_text=_classification_json(
                intent="general_reply",
                summary_text="Lead asked about service pricing.",
            ),
            draft_text=_draft_json(),
        ),
        now=NOW,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
        **dependencies,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    saved_event = external_events.events[(WORKSPACE_ID, CRMProvider.FOLLOW_UP_BOSS.value, "evt-1")]
    audit = saved_event.payload_redacted["processing_audit"]
    assert audit["classifier"]["intent"] == "general_reply"
    assert audit["classifier"]["preferences"] == {"timeline": "today"}
    assert audit["classifier"]["classification_reasons"] == []
    assert audit["decision"]["inbound_action"] == "continue_ai"
    assert audit["decision"]["decision_reason"] == "general_reply"
    assert audit["decision"]["handoff_required"] is False
    assert audit["continuation"]["continue_ai_status"] == "sent"
    assert audit["continuation"]["ai_interaction_count_increment"] == 1
    assert audit["continuation"]["outbound_message_id"] is not None
    assert audit["continuation"]["provider_message_id"] == "SM123"
    assert audit["workflow"]["workflow_id"] == str(WORKFLOW_ID)
    assert audit["workflow"]["to_state"] == "waiting_for_response"
    assert audit["workflow"]["workflow_transition_status"] == "updated"
    assert audit["crm"]["review_tag"] is None
    assert audit["crm"]["review_tag_applied"] is False
    assert audit["review_notification"]["sent"] is False
    assert audit["handoff"]["handoff_id"] is None
    assert audit["signal_queued"] is False


async def test_processing_audit_persisted_for_continue_ai_blocked_at_turn_cap() -> None:
    workflow = _workflow()
    external_events = FakeExternalEventRepository()
    dependencies = _continue_ai_dependencies(
        workflow=workflow, external_event_repository=external_events
    )
    conversation_repository = dependencies["conversation_repository"]
    await conversation_repository.save(_conversation(ai_interaction_count=5))

    result = await process_inbound_message_event(
        event=_event(body="How much are your services?"),
        llm_client=_FakeLLMClientForContinuation(
            classification_text=_classification_json(
                intent="general_reply",
                summary_text="Lead asked about service pricing.",
            ),
            draft_text=_draft_json(),
        ),
        now=NOW,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
        **dependencies,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.continue_ai_status == ContinueAIStatus.BLOCKED
    saved_event = external_events.events[(WORKSPACE_ID, CRMProvider.FOLLOW_UP_BOSS.value, "evt-1")]
    audit = saved_event.payload_redacted["processing_audit"]
    assert audit["classifier"]["intent"] == "general_reply"
    assert audit["decision"]["inbound_action"] == "continue_ai"
    assert audit["continuation"]["continue_ai_status"] == "blocked"
    assert audit["continuation"]["ai_interaction_count_increment"] == 0
    assert audit["continuation"]["pause_reason"] == "ai_continuation_turn_cap_reached"
    assert audit["continuation"]["send_block_reasons"] == ["turn_cap_reached"]
    assert audit["workflow"]["to_state"] == "paused"
    assert audit["workflow"]["workflow_transition_status"] == "updated"


async def test_processing_audit_persisted_for_pause_for_review() -> None:
    external_events = FakeExternalEventRepository()
    crm_client = FakeCRMClient(
        assigned_agent=CRMAgent(crm_agent_id="agent-99", email="agent@example.com", name="Agent")
    )
    workspace_handoff_config = _workspace_handoff_config()
    lead_workflow_repository = _workflow_repository(_workflow())
    workflow_transition_repository = FakeWorkflowTransitionRepository()

    result = await process_inbound_message_event(
        event=_event(body="I don't know what I want."),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=external_events,
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="unclear",
                summary_text="Lead is unclear about their needs.",
            ),
        ),
        crm_client=crm_client,
        notification_provider=FakeNotificationProvider(),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            workspace_handoff_config
        ),
        inbound_message_crm_completion_repository=FakeInboundMessageCRMCompletionRepository(),
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=NOW,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.PAUSE_FOR_REVIEW
    saved_event = external_events.events[(WORKSPACE_ID, CRMProvider.FOLLOW_UP_BOSS.value, "evt-1")]
    audit = saved_event.payload_redacted["processing_audit"]
    assert audit["classifier"]["intent"] == "unclear"
    assert audit["decision"]["inbound_action"] == "pause_for_review"
    assert audit["decision"]["decision_reason"] == "unclear_intent"
    assert audit["decision"]["handoff_required"] is False
    assert audit["continuation"]["continue_ai_status"] is None
    assert audit["workflow"]["to_state"] == "paused"
    assert audit["workflow"]["workflow_transition_status"] == "updated"
    assert audit["crm"]["review_tag"] == "needs_agent_review"
    assert audit["crm"]["review_tag_applied"] is True
    assert audit["review_notification"]["sent"] is True
    assert audit["review_notification"]["recipient"] == "agent@example.com"
    assert audit["handoff"]["handoff_id"] is None


async def test_processing_audit_persisted_for_handoff_with_completion() -> None:
    external_events = FakeExternalEventRepository()
    workspace_handoff_config = _workspace_handoff_config()
    crm_client = FakeCRMClient(
        assigned_agent=CRMAgent(crm_agent_id="agent-99", email="agent@example.com", name="Agent")
    )
    handoff_repository = FakeHandoffRepository()
    handoff_completion_repository = FakeHandoffCompletionRepository()
    notification_provider = FakeNotificationProvider()
    lead_workflow_repository = _workflow_repository(_workflow())
    workflow_transition_repository = FakeWorkflowTransitionRepository()

    result = await process_inbound_message_event(
        event=_event(),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=external_events,
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=handoff_repository,
        llm_client=FakeLLMClient(_classification_json(intent="human_requested")),
        crm_client=crm_client,
        notification_provider=notification_provider,
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            workspace_handoff_config
        ),
        handoff_completion_repository=handoff_completion_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=NOW,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
        handoff_id_factory=lambda: HANDOFF_ID,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.HUMAN_HANDOFF
    assert result.handoff_id == HANDOFF_ID
    saved_event = external_events.events[(WORKSPACE_ID, CRMProvider.FOLLOW_UP_BOSS.value, "evt-1")]
    audit = saved_event.payload_redacted["processing_audit"]
    assert audit["classifier"]["intent"] == "human_requested"
    assert audit["classifier"]["evidence"]["asks_for_human"] is True
    assert audit["decision"]["inbound_action"] == "human_handoff"
    assert audit["decision"]["decision_reason"] == "human_requested"
    assert audit["decision"]["handoff_reason"] == "human_requested"
    assert audit["decision"]["handoff_required"] is True
    assert audit["continuation"]["continue_ai_status"] is None
    assert audit["workflow"]["to_state"] == "human_handoff"
    assert audit["workflow"]["workflow_transition_status"] == "updated"
    assert audit["handoff"]["handoff_id"] == str(HANDOFF_ID)
    assert audit["handoff"]["completion_status"] == "completed"
    assert audit["review_notification"]["sent"] is False


async def test_processing_audit_persisted_for_classification_rejected() -> None:
    external_events = FakeExternalEventRepository()

    result = await process_inbound_message_event(
        event=_event(),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=external_events,
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="general_reply",
                confidence=0.2,
                summary_text="Lead replied but confidence is low.",
            ),
        ),
        now=NOW,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.inbound_action == InboundAction.PAUSE_FOR_REVIEW
    assert result.inbound_action_reason == InboundActionReasonCode.CLASSIFICATION_REJECTED
    saved_event = external_events.events[(WORKSPACE_ID, CRMProvider.FOLLOW_UP_BOSS.value, "evt-1")]
    audit = saved_event.payload_redacted["processing_audit"]
    assert audit["classifier"]["status"] == "rejected"
    assert audit["classifier"]["intent"] is None
    assert audit["classifier"]["confidence"] == 0.2
    assert audit["classifier"]["classification_reasons"] == ["low_confidence"]
    assert audit["decision"]["inbound_action"] == "pause_for_review"
    assert audit["decision"]["decision_reason"] == "classification_rejected"
    assert audit["continuation"]["continue_ai_status"] is None
    assert audit["workflow"]["workflow_transition_status"] == "no_workflow"
    assert audit["workflow"]["to_state"] is None
