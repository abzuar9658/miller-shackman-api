import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from app.application.ports.lead_activity import LeadActivityItem, LeadActivityKind
from app.application.ports.listing_search import ListingSearchQuery
from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.services.llm.outbound_query_extraction import (
    OUTBOUND_QUERY_EXTRACTION_PROMPT_VERSION,
)
from app.application.use_cases.plan_next_outbound_message import (
    PlanNextOutboundMessageContext,
    plan_next_outbound_message_for_lead,
)
from app.application.use_cases.plan_outbound_message import (
    PlanOutboundMessageReasonCode,
    PlanOutboundMessageStatus,
)
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.pre_send import ProviderSendStatus, WorkflowState
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SmsComplianceState,
    WorkspaceContactPolicy,
)
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.leads import CanonicalLeadRecord, CRMProvider, PropertyEventType
from app.domain.listing_sources import (
    CanonicalListingSnapshot,
    ListingSnapshotStatus,
    ListingSource,
    ListingSourceType,
)
from app.domain.llm import WorkspaceLLMConfig
from app.domain.outbound_drafting import (
    OutboundJourneyKind,
    default_workspace_outbound_drafting_config,
)
from tests.application.use_cases._campaign_cadence_fakes import FakeCrmConversationEventRepository

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
CAMPAIGN_ID = UUID("22222222-2222-2222-2222-222222222222")
LEAD_ID = UUID("33333333-3333-3333-3333-333333333333")
MESSAGE_ID = UUID("44444444-4444-4444-4444-444444444444")


class FakeLeadRepository:
    def __init__(self, lead: CanonicalLeadRecord | None) -> None:
        self.lead = lead

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        if self.lead and self.lead.workspace_id == workspace_id and self.lead.lead_id == lead_id:
            return self.lead
        return None

    async def get_by_crm_id(
        self,
        workspace_id: WorkspaceId,
        crm_provider: CRMProvider,
        crm_lead_id: str,
    ) -> CanonicalLeadRecord | None:
        return None

    async def list_by_assigned_agent_crm_id(
        self,
        workspace_id: WorkspaceId,
        assigned_agent_crm_id: str,
    ) -> tuple[CanonicalLeadRecord, ...]:
        if (
            self.lead
            and self.lead.workspace_id == workspace_id
            and self.lead.assigned_agent_crm_id == assigned_agent_crm_id
        ):
            return (self.lead,)
        return ()

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        return await self.get_by_id(workspace_id, lead_id)

    async def get_by_primary_phone(
        self,
        workspace_id: WorkspaceId,
        phone_number: str,
    ) -> CanonicalLeadRecord | None:
        if self.lead is None or self.lead.workspace_id != workspace_id:
            return None
        if self.lead.primary_phone == phone_number:
            return self.lead
        return None

    async def get_by_primary_email(
        self,
        workspace_id: WorkspaceId,
        email_address: str,
    ) -> CanonicalLeadRecord | None:
        matches = await self.list_by_primary_email(workspace_id, email_address)
        if len(matches) == 1:
            return matches[0]
        return None

    async def list_by_primary_email(
        self,
        workspace_id: WorkspaceId,
        email_address: str,
    ) -> tuple[CanonicalLeadRecord, ...]:
        if (
            self.lead
            and self.lead.workspace_id == workspace_id
            and self.lead.primary_email is not None
            and self.lead.primary_email.strip().lower() == email_address.strip().lower()
        ):
            return (self.lead,)
        return ()

    async def upsert(self, record: CanonicalLeadRecord) -> CanonicalLeadRecord:
        self.lead = record
        return record


class FakeOutboundMessageRepository:
    def __init__(self) -> None:
        self.messages_by_idempotency_key: dict[tuple[WorkspaceId, str], OutboundMessage] = {}
        self.saved: list[OutboundMessage] = []

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        message_id: UUID,
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
        self.messages_by_idempotency_key[(message.workspace_id, message.idempotency_key)] = message
        return message

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[OutboundMessage, ...]:
        return tuple(
            message
            for message in self.messages_by_idempotency_key.values()
            if message.workspace_id == workspace_id and message.lead_id == lead_id
        )[:limit]


class FakeLLMClient:
    def __init__(self, text: str, *, extraction_text: str | None = None) -> None:
        self.text = text
        self.extraction_text = extraction_text or json.dumps(
            {
                "search_type": None,
                "address": None,
                "location": None,
                "keywords": None,
                "beds": None,
                "min_price": None,
                "max_price": None,
                "price_band": None,
                "confidence": 0.1,
                "reasons": ["Not enough detail to improve on deterministic extraction."],
            }
        )
        self.requests: list[LLMCompletionRequest] = []

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        return LLMResult(
            text=(
                self.extraction_text
                if request.prompt_version == OUTBOUND_QUERY_EXTRACTION_PROMPT_VERSION
                else self.text
            ),
            model="openai/gpt-4o-mini",
            prompt_version=request.prompt_version,
            latency_ms=13,
            usage_tokens=37,
        )


class FakeWorkspaceLLMConfigRepository:
    def __init__(self, config: WorkspaceLLMConfig | None) -> None:
        self.config = config

    async def get_by_workspace_id(self, workspace_id: WorkspaceId) -> WorkspaceLLMConfig | None:
        if self.config is not None and self.config.workspace_id == workspace_id:
            return self.config
        return None

    async def save(self, config: WorkspaceLLMConfig) -> WorkspaceLLMConfig:
        self.config = config
        return config


class FakeListingSourceRepository:
    def __init__(self, source: ListingSource) -> None:
        self.source = source

    async def get_by_id(self, workspace_id: object, source_id: object) -> ListingSource | None:
        if self.source.workspace_id == workspace_id and self.source.source_id == source_id:
            return self.source
        return None

    async def get_by_name(self, workspace_id: object, name: str) -> ListingSource | None:
        if self.source.workspace_id == workspace_id and self.source.name == name:
            return self.source
        return None

    async def list_for_workspace(self, workspace_id: object) -> tuple[ListingSource, ...]:
        if self.source.workspace_id != workspace_id:
            return ()
        return (self.source,)

    async def list_enabled(self, *, limit: int = 100) -> tuple[ListingSource, ...]:
        if not self.source.enabled:
            return ()
        return (self.source,)

    async def save(self, source: ListingSource) -> ListingSource:
        self.source = source
        return source


class FakeListingSnapshotRepository:
    def __init__(self, snapshots: tuple[CanonicalListingSnapshot, ...] = ()) -> None:
        self.snapshots = list(snapshots)

    async def get_by_id(
        self,
        workspace_id: object,
        snapshot_id: object,
    ) -> CanonicalListingSnapshot | None:
        for snapshot in self.snapshots:
            if snapshot.workspace_id == workspace_id and snapshot.snapshot_id == snapshot_id:
                return snapshot
        return None

    async def get_current_by_external_id(
        self,
        workspace_id: object,
        source_id: object,
        external_listing_id: str,
    ) -> CanonicalListingSnapshot | None:
        for snapshot in self.snapshots:
            if (
                snapshot.workspace_id == workspace_id
                and snapshot.source_id == source_id
                and snapshot.external_listing_id == external_listing_id
                and snapshot.is_current
            ):
                return snapshot
        return None

    async def list_current_for_source(
        self, workspace_id: object, source_id: object, *, limit: int = 100
    ) -> tuple[CanonicalListingSnapshot, ...]:
        filtered = [
            snapshot
            for snapshot in self.snapshots
            if snapshot.workspace_id == workspace_id and snapshot.source_id == source_id
        ]
        return tuple(filtered[:limit])

    async def save(self, snapshot: CanonicalListingSnapshot) -> CanonicalListingSnapshot:
        self.snapshots.append(snapshot)
        return snapshot

    async def mark_other_versions_not_current(
        self,
        workspace_id: object,
        source_id: object,
        external_listing_id: str,
        except_snapshot_id: object,
    ) -> None:
        _ = (workspace_id, source_id, external_listing_id, except_snapshot_id)


class FakeListingSearchClient:
    def __init__(self, snapshots: tuple[CanonicalListingSnapshot, ...]) -> None:
        self.snapshots = snapshots
        self.queries: list[ListingSearchQuery] = []

    async def search(
        self, *, source: ListingSource, query: ListingSearchQuery
    ) -> tuple[CanonicalListingSnapshot, ...]:
        _ = source
        self.queries.append(query)
        return self.snapshots


def _lead(
    *,
    has_sms_capable_phone: bool = True,
    has_email: bool = True,
    sms_permission_status: ContactPermissionStatus = ContactPermissionStatus.CONFIRMED,
    email_permission_status: ContactPermissionStatus = ContactPermissionStatus.CONFIRMED,
) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="long_term_nurture",
        mapped_custom_fields={"preferred_location": "Austin"},
        primary_email="lead@example.com" if has_email else None,
        primary_phone="+15551234567" if has_sms_capable_phone else None,
        has_sms_capable_phone=has_sms_capable_phone,
        has_email=has_email,
        sms_permission_status=sms_permission_status,
        email_permission_status=email_permission_status,
        do_not_contact=False,
        has_accountable_owner=True,
        last_meaningful_communication_at=NOW - timedelta(days=90),
        latest_property_event_type=PropertyEventType.PROPERTY_INQUIRY,
        latest_property_price_band="500k-750k",
    )


def _planning_context(
    *,
    enabled_channels: tuple[ContactChannel, ...] = (ContactChannel.SMS,),
    workflow_state: WorkflowState = WorkflowState.ACTIVE_NURTURE,
    activity_items: tuple[LeadActivityItem, ...] = (),
    extracted_preferences: dict[str, str] | None = None,
) -> PlanNextOutboundMessageContext:
    return PlanNextOutboundMessageContext(
        campaign_status=CampaignStatus.ACTIVE,
        workflow_state=workflow_state,
        enabled_channels=enabled_channels,
        workspace_contact_policy=WorkspaceContactPolicy(
            workspace_id=WORKSPACE_ID,
            sms_compliance_state=SmsComplianceState.APPROVED,
        ),
        campaign_goal="Re-engage dormant buyer leads without giving property or finance advice.",
        brokerage_name="Miller Schackman",
        cadence_step_id="step-1",
        assigned_agent_name="Alex Agent",
        journey_kind=OutboundJourneyKind.DORMANT,
        extracted_preferences=extracted_preferences or {},
        allowed_mapped_custom_field_keys=("preferred_location",),
        activity_items=activity_items,
        drafting_config=default_workspace_outbound_drafting_config(WORKSPACE_ID),
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


def _draft_json(
    *,
    body: str = "Hi — are you still thinking about making a move this year?",
    subject: str | None = None,
) -> str:
    return json.dumps(
        {
            "body": body,
            "subject": subject,
            "confidence": 0.91,
            "personalization_notes": ["Used safe canonical context."],
            "safety_flags": [],
        },
    )


def _draft_requests(llm: FakeLLMClient) -> list[LLMCompletionRequest]:
    return [
        request
        for request in llm.requests
        if request.prompt_version != OUTBOUND_QUERY_EXTRACTION_PROMPT_VERSION
    ]


def _listing_source() -> ListingSource:
    return ListingSource(
        source_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        name="StreetEasy",
        source_type=ListingSourceType.WEBSITE,
        base_url="https://streeteasy.com",
        enabled=True,
        terms_reviewed_at=NOW,
        data_use_policy="Reviewed for optional enrichment.",
        created_at=NOW,
        updated_at=NOW,
    )


def _listing_snapshot(source_id: UUID) -> CanonicalListingSnapshot:
    return CanonicalListingSnapshot(
        snapshot_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        source_id=source_id,
        external_listing_id="listing-1",
        source_url="https://streeteasy.com/building/2738-miles-avenue-bronx/1",
        source_payload_hash="hash-1",
        scraped_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        title="Single-family house in Throgs Neck",
        address_text="2738 Miles Avenue, Bronx, NY 10465",
        neighborhood="Bronx",
        price=Decimal("650000"),
        beds=Decimal("4"),
        baths=Decimal("1"),
        property_type="house",
        status=ListingSnapshotStatus.ACTIVE,
    )


async def test_plans_message_using_safe_context_assembled_from_canonical_lead() -> None:
    llm = FakeLLMClient(_draft_json())

    result = await plan_next_outbound_message_for_lead(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(extracted_preferences={"location": "Bronx"}),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=FakeOutboundMessageRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        llm_client=llm,
        now=NOW,
        message_id_factory=lambda: MESSAGE_ID,
    )

    assert result.status == PlanOutboundMessageStatus.PLANNED
    assert result.message is not None
    assert result.message.message_id == MESSAGE_ID
    assert result.message.status == OutboundMessageStatus.PENDING
    assert result.message.provider_send_status == ProviderSendStatus.NOT_ATTEMPTED
    draft_requests = _draft_requests(llm)
    assert len(draft_requests) == 1
    assert "No meaningful communication recorded for 90 days." in draft_requests[0].prompt
    assert '"journey_kind": "dormant"' in draft_requests[0].prompt
    assert "the lead inquired about a property" in draft_requests[0].prompt
    assert "Bronx" in draft_requests[0].prompt
    assert "Austin" not in draft_requests[0].prompt


async def test_uses_workspace_llm_model_for_outbound_planning() -> None:
    llm = FakeLLMClient(_draft_json())

    await plan_next_outbound_message_for_lead(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(extracted_preferences={"location": "Bronx"}),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=FakeOutboundMessageRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        llm_client=llm,
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(
            WorkspaceLLMConfig(
                workspace_id=WORKSPACE_ID,
                openrouter_model="openai/gpt-4.1-mini",
            )
        ),
        default_openrouter_model="openai/gpt-4o-mini",
        now=NOW,
        message_id_factory=lambda: MESSAGE_ID,
    )

    assert all(request.model == "openai/gpt-4.1-mini" for request in llm.requests)


async def test_prefers_recent_crm_conversation_history_when_available() -> None:
    llm = FakeLLMClient(_draft_json())

    result = await plan_next_outbound_message_for_lead(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(extracted_preferences={"location": "Bronx"}),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=FakeOutboundMessageRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(
            (
                _crm_event(
                    crm_activity_id="1",
                    content="Sent a quick check-in email last week.",
                    direction=CrmConversationEventDirection.OUTBOUND,
                ),
                _crm_event(
                    crm_activity_id="2",
                    content="We are hoping to move before school starts.",
                    direction=CrmConversationEventDirection.INBOUND,
                ),
            )
        ),
        llm_client=llm,
        now=NOW,
        message_id_factory=lambda: MESSAGE_ID,
    )

    assert result.status == PlanOutboundMessageStatus.PLANNED
    draft_requests = _draft_requests(llm)
    assert len(draft_requests) == 1
    assert "Recent CRM conversation history:" in draft_requests[0].prompt
    assert "Sent a quick check-in email last week." in draft_requests[0].prompt
    assert "We are hoping to move before school starts." in draft_requests[0].prompt
    assert "No meaningful communication recorded for 90 days." not in draft_requests[0].prompt


async def test_prefers_unified_activity_context_when_available() -> None:
    llm = FakeLLMClient(_draft_json())

    result = await plan_next_outbound_message_for_lead(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(
            activity_items=(
                LeadActivityItem(
                    activity_id=uuid4(),
                    lead_id=LEAD_ID,
                    kind=LeadActivityKind.OUTBOUND_MESSAGE,
                    occurred_at=NOW - timedelta(days=2),
                    title="Outbound outreach logged",
                    preview="Sent a safe check-in email two days ago.",
                    content=(
                        "Sent a safe check-in email two days ago asking whether Riverdale "
                        "is still the preferred area."
                    ),
                    channel="email",
                    direction="outbound",
                    status="sent",
                ),
                LeadActivityItem(
                    activity_id=uuid4(),
                    lead_id=LEAD_ID,
                    kind=LeadActivityKind.CRM_CONVERSATION_EVENT,
                    occurred_at=NOW,
                    title="CRM reply logged",
                    preview="We are hoping to move before school starts.",
                    content=(
                        "We are hoping to move before school starts and still need at least "
                        "2 bedrooms."
                    ),
                    direction="inbound",
                    status="Note",
                    actor_name="Avery Agent",
                ),
            )
        ),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=FakeOutboundMessageRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        llm_client=llm,
        now=NOW,
        message_id_factory=lambda: MESSAGE_ID,
    )

    assert result.status == PlanOutboundMessageStatus.PLANNED
    draft_requests = _draft_requests(llm)
    assert len(draft_requests) == 1
    assert "Recent meaningful activity:" in draft_requests[0].prompt
    assert "conversation_memory_summary" in draft_requests[0].prompt
    assert "recent_conversation_items" in draft_requests[0].prompt
    assert "recent_outbound_messages" in draft_requests[0].prompt
    assert (
        "Sent a safe check-in email two days ago asking whether Riverdale"
        in draft_requests[0].prompt
    )
    assert "We are hoping to move before school starts and still need at least 2 bedrooms." in (
        draft_requests[0].prompt
    )
    assert "No meaningful communication recorded for 90 days." not in draft_requests[0].prompt


async def test_enriches_prompt_with_streeteasy_listing_context_when_enabled() -> None:
    llm = FakeLLMClient(_draft_json())
    source = _listing_source()
    search_client = FakeListingSearchClient((_listing_snapshot(source.source_id),))

    result = await plan_next_outbound_message_for_lead(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(extracted_preferences={"location": "Bronx"}),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=FakeOutboundMessageRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        llm_client=llm,
        now=NOW,
        listing_source_repository=FakeListingSourceRepository(source),
        listing_snapshot_repository=FakeListingSnapshotRepository(),
        listing_search_client=search_client,
        listing_enrichment_enabled=True,
        message_id_factory=lambda: MESSAGE_ID,
    )

    assert result.status == PlanOutboundMessageStatus.PLANNED
    assert len(search_client.queries) == 1
    draft_requests = _draft_requests(llm)
    assert "approved_listing_context" in draft_requests[0].prompt
    assert "listing_relevance_brief" in draft_requests[0].prompt
    assert "StreetEasy" in draft_requests[0].prompt
    assert "2738 Miles Avenue" not in draft_requests[0].prompt
    assert "$650,000" not in draft_requests[0].prompt


async def test_listing_enrichment_uses_preferences_extracted_from_activity_history() -> None:
    llm = FakeLLMClient(_draft_json())
    source = _listing_source()
    search_client = FakeListingSearchClient((_listing_snapshot(source.source_id),))

    result = await plan_next_outbound_message_for_lead(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(
            activity_items=(
                LeadActivityItem(
                    activity_id=uuid4(),
                    lead_id=LEAD_ID,
                    kind=LeadActivityKind.INBOUND_MESSAGE,
                    occurred_at=NOW,
                    title="Lead replied",
                    preview="Riverdale or Spuyten Duyvil still works.",
                    content=(
                        "We still want Riverdale or Spuyten Duyvil and need at least 2 "
                        "bedrooms under 600k. A co-op is okay."
                    ),
                    channel="sms",
                    direction="inbound",
                    actor_name="lead",
                ),
            ),
        ),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=FakeOutboundMessageRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        llm_client=llm,
        now=NOW,
        listing_source_repository=FakeListingSourceRepository(source),
        listing_snapshot_repository=FakeListingSnapshotRepository(),
        listing_search_client=search_client,
        listing_enrichment_enabled=True,
        message_id_factory=lambda: MESSAGE_ID,
    )

    assert result.status == PlanOutboundMessageStatus.PLANNED
    assert len(search_client.queries) == 1
    assert search_client.queries[0].locations == ("Riverdale", "Spuyten Duyvil")
    assert search_client.queries[0].min_beds == Decimal("2")
    assert search_client.queries[0].max_price == Decimal("600000")
    assert search_client.queries[0].keywords == ("co-op",)


async def test_llm_query_extraction_updates_listing_search_type_for_production_path() -> None:
    source = _listing_source()
    search_client = FakeListingSearchClient((_listing_snapshot(source.source_id),))
    llm = FakeLLMClient(
        _draft_json(),
        extraction_text=json.dumps(
            {
                "search_type": "rent",
                "location": "Queens",
                "max_price": "2400",
                "confidence": 0.91,
                "reasons": ["Monthly budget language indicates rent."],
            }
        ),
    )

    result = await plan_next_outbound_message_for_lead(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(
            activity_items=(
                LeadActivityItem(
                    activity_id=uuid4(),
                    lead_id=LEAD_ID,
                    kind=LeadActivityKind.INBOUND_MESSAGE,
                    occurred_at=NOW,
                    title="Lead replied",
                    preview="Need something in Queens around $2,400 per month.",
                    content="Need something in Queens around $2,400 per month.",
                    channel="email",
                    direction="inbound",
                    actor_name="lead",
                ),
            ),
        ),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=FakeOutboundMessageRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        llm_client=llm,
        now=NOW,
        listing_source_repository=FakeListingSourceRepository(source),
        listing_snapshot_repository=FakeListingSnapshotRepository(),
        listing_search_client=search_client,
        listing_enrichment_enabled=True,
        message_id_factory=lambda: MESSAGE_ID,
    )

    assert result.status == PlanOutboundMessageStatus.PLANNED
    assert len(search_client.queries) == 1
    assert search_client.queries[0].search_type.value == "rent"
    assert search_client.queries[0].locations == ("Queens",)
    assert search_client.queries[0].max_price == Decimal("2400")


async def test_rejects_without_calling_llm_when_pre_send_blocks_high_level_plan() -> None:
    llm = FakeLLMClient(_draft_json())

    result = await plan_next_outbound_message_for_lead(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(workflow_state=WorkflowState.PAUSED),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=FakeOutboundMessageRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        llm_client=llm,
        now=NOW,
    )

    assert result.status == PlanOutboundMessageStatus.REJECTED
    assert result.reasons == (PlanOutboundMessageReasonCode.PRE_SEND_BLOCKED,)
    assert llm.requests == []


async def test_falls_back_to_email_when_sms_not_contactable_in_high_level_plan() -> None:
    result = await plan_next_outbound_message_for_lead(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(enabled_channels=(ContactChannel.SMS, ContactChannel.EMAIL)),
        lead_repository=FakeLeadRepository(
            _lead(
                has_sms_capable_phone=False,
                sms_permission_status=ContactPermissionStatus.UNKNOWN,
            ),
        ),
        message_repository=FakeOutboundMessageRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        llm_client=FakeLLMClient(_draft_json(subject="Checking in")),
        now=NOW,
        message_id_factory=lambda: MESSAGE_ID,
    )

    assert result.status == PlanOutboundMessageStatus.PLANNED
    assert result.selected_channel == ContactChannel.EMAIL
    assert result.message is not None
    assert result.message.subject == "Checking in | Miller Schackman"


async def test_duplicate_plan_returns_existing_message_without_calling_llm() -> None:
    messages = FakeOutboundMessageRepository()
    existing = OutboundMessage(
        message_id=MESSAGE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        cadence_step_id="step-1",
        channel=ContactChannel.SMS,
        status=OutboundMessageStatus.PENDING,
        idempotency_key=f"outbound:{WORKSPACE_ID}:{CAMPAIGN_ID}:{LEAD_ID}:step-1:sms:v1",
        body="Existing draft",
        created_at=NOW,
        updated_at=NOW,
    )
    await messages.save(existing)
    messages.saved.clear()
    llm = FakeLLMClient(_draft_json())

    result = await plan_next_outbound_message_for_lead(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=messages,
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        llm_client=llm,
        now=NOW,
    )

    assert result.status == PlanOutboundMessageStatus.DUPLICATE
    assert result.message == existing
    assert result.reasons == (PlanOutboundMessageReasonCode.DUPLICATE_PLAN,)
    assert llm.requests == []
