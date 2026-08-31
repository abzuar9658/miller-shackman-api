import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.services.llm.outbound_message_drafting import (
    ApprovedListingRelevanceBrief,
    ApprovedOutboundConversationItem,
    ApprovedOutboundLeadContext,
    ApprovedOutboundListingContext,
    ApprovedOutboundListingMatch,
    OutboundMessageDraftReasonCode,
    OutboundMessageDraftStatus,
    build_listing_relevance_brief,
    draft_outbound_message,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.llm import LLMProviderKind, LLMTaskKind
from app.domain.outbound_drafting import (
    OutboundJourneyChange,
    OutboundJourneyKind,
    WorkspaceOutboundDraftingConfig,
)

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


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
            latency_ms=25,
            usage_tokens=42,
        )


def _lead(*, display_name: str | None = None) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=uuid4(),
        lead_id=uuid4(),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="long_term_nurture",
        mapped_custom_fields=({"display_name": display_name} if display_name else {}),
    )


def _draft_json(
    *,
    body: str = "are you still thinking about making a move this year?",
    subject: str | None = None,
    confidence: float = 0.91,
    safety_flags: tuple[str, ...] = (),
    lead_first_name: str | None = None,
) -> str:
    return json.dumps(
        {
            "body": body,
            "subject": subject,
            "confidence": confidence,
            "personalization_notes": ["Used safe lead stage context."],
            "safety_flags": list(safety_flags),
            "lead_first_name": lead_first_name,
        },
    )


async def test_drafts_sms_with_versioned_prompt_and_approved_context() -> None:
    llm = FakeLLMClient(_draft_json())

    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Alex Agent",
        lead_context=ApprovedOutboundLeadContext(
            conversation_summary="Lead was previously browsing buyer resources.",
            conversation_memory_summary=(
                "Conversation memory: Lead previously discussed Riverdale and a 2 bed budget."
            ),
            latest_lead_request="Asked about homes near Austin.",
            extracted_preferences={"location": "Austin"},
            recent_conversation_items=(
                ApprovedOutboundConversationItem(
                    occurred_at=NOW.isoformat(),
                    title="Inbound message",
                    content="We are still looking in Riverdale and want 2 beds.",
                    direction="inbound",
                    channel="sms",
                    actor_name="lead",
                ),
            ),
            recent_outbound_messages=(
                "Just checking whether Riverdale is still the right area for you.",
            ),
        ),
        journey_kind=OutboundJourneyKind.DORMANT,
        message_purpose=(
            "Ask whether the lead's lease-end timing changed and whether a future "
            "reconnection would be useful."
        ),
        llm_client=llm,
    )

    assert result.status == OutboundMessageDraftStatus.DRAFTED
    assert result.body == "Hi there,\n\nare you still thinking about making a move this year?"
    assert result.model == "openai/gpt-4o-mini"
    assert result.usage_tokens == 42
    assert llm.requests[0].prompt_version == "outbound_message_draft:v18:r1"
    assert "Austin" in llm.requests[0].prompt
    assert "Journey: dormant" in llm.requests[0].prompt
    assert "lease-end timing changed" in llm.requests[0].prompt
    assert "## Writing Objective" in llm.requests[0].prompt
    assert "Do not invent listings" in llm.requests[0].prompt
    # v15: single-source prose prompt — no JSON payload duplication
    assert "# Structured Request Payload" not in llm.requests[0].prompt
    assert "# Writing Instructions" in llm.requests[0].prompt
    assert "primary behavior brief" in llm.requests[0].prompt
    assert "Lead type:" in llm.requests[0].prompt
    assert "Lead source: website" in llm.requests[0].prompt
    assert "Lead stage: long_term_nurture" in llm.requests[0].prompt
    assert "For dormant outreach, treat the lead as quiet for an unknown reason" in (
        llm.requests[0].prompt
    )
    assert (
        "generate ONLY the natural-language message content that should be inserted into or "
        "appended to the final template as the message body" in llm.requests[0].prompt
    )
    assert (
        "Otherwise, the application will append your generated body after the template."
        in llm.requests[0].prompt
    )
    assert (
        "You write follow-up messages for a real estate brokerage in the voice of a "
        "busy, friendly human agent." in llm.requests[0].prompt
    )
    assert "Conversation summary:" in llm.requests[0].prompt
    assert "## Recent Conversation" in llm.requests[0].prompt
    assert "## Recent Outbound Messages" in llm.requests[0].prompt
    assert "Avoid repeating the same greeting" in llm.requests[0].prompt
    assert llm.requests[0].task is LLMTaskKind.DRAFTING
    assert llm.requests[0].provider is None


async def test_threads_provider_through_draft_request() -> None:
    llm = FakeLLMClient(_draft_json())

    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=llm,
        provider=LLMProviderKind.BEDROCK,
    )

    assert result.status == OutboundMessageDraftStatus.DRAFTED
    assert llm.requests[0].provider is LLMProviderKind.BEDROCK
    assert llm.requests[0].task is LLMTaskKind.DRAFTING


async def test_journey_change_section_added_when_previous_journey_differs() -> None:
    llm = FakeLLMClient(_draft_json())

    await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.EMAIL,
        campaign_goal="Re-open a helpful conversation without pressure.",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        lead_context=ApprovedOutboundLeadContext(),
        journey_kind=OutboundJourneyKind.DORMANT,
        journey_change=OutboundJourneyChange(
            previous_journey_kind=OutboundJourneyKind.PAUSED_SEARCH,
        ),
        llm_client=llm,
    )

    prompt = llm.requests[0].prompt
    assert "## Journey Change" in prompt
    assert "previously on a paused-search journey" in prompt
    assert "moved to a dormant journey" in prompt
    assert "Do not reuse, paraphrase, or reference the framing" in prompt


async def test_journey_change_section_added_when_paused_search_track_changed() -> None:
    llm = FakeLLMClient(_draft_json())

    await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.EMAIL,
        campaign_goal="Check in on paused timing.",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        lead_context=ApprovedOutboundLeadContext(),
        journey_kind=OutboundJourneyKind.PAUSED_SEARCH,
        journey_change=OutboundJourneyChange(
            previous_journey_kind=OutboundJourneyKind.PAUSED_SEARCH,
            track_changed=True,
        ),
        llm_client=llm,
    )

    prompt = llm.requests[0].prompt
    assert "## Journey Change" in prompt
    assert "previously on a different paused-search track" in prompt
    assert "moved to a new paused-search track" in prompt


async def test_no_journey_change_section_without_journey_change() -> None:
    llm = FakeLLMClient(_draft_json())

    await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.EMAIL,
        campaign_goal="Re-open a helpful conversation without pressure.",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        lead_context=ApprovedOutboundLeadContext(),
        journey_kind=OutboundJourneyKind.DORMANT,
        llm_client=llm,
    )

    assert "## Journey Change" not in llm.requests[0].prompt


async def test_no_journey_change_section_when_previous_journey_matches() -> None:
    llm = FakeLLMClient(_draft_json())

    await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.EMAIL,
        campaign_goal="Re-open a helpful conversation without pressure.",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        lead_context=ApprovedOutboundLeadContext(),
        journey_kind=OutboundJourneyKind.DORMANT,
        journey_change=OutboundJourneyChange(
            previous_journey_kind=OutboundJourneyKind.DORMANT,
        ),
        llm_client=llm,
    )

    assert "## Journey Change" not in llm.requests[0].prompt


async def test_uses_admin_configured_top_level_prompt_text() -> None:
    llm = FakeLLMClient(_draft_json())

    await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Taylor Agent",
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=llm,
        drafting_config=WorkspaceOutboundDraftingConfig(
            workspace_id=_lead().workspace_id,
            prompt_text=(
                "You are the brokerage's nurture drafting assistant. Write a safe re-engagement "
                "message and tee up the assigned agent when appropriate."
            ),
        ),
    )

    assert (
        "You are the brokerage's nurture drafting assistant. Write a safe re-engagement "
        "message and tee up the assigned agent when appropriate." in llm.requests[0].prompt
    )
    assert (
        "You write follow-up messages for a real estate brokerage in the voice of a "
        "busy, friendly human agent." not in llm.requests[0].prompt
    )


def test_builds_safe_listing_relevance_brief_from_listing_context() -> None:
    brief = build_listing_relevance_brief(
        ApprovedOutboundListingContext(
            source_name="StreetEasy",
            search_summary="sale in Bronx up to $750,000 with 2+ beds",
            result_count=2,
            matches=(
                ApprovedOutboundListingMatch(
                    neighborhood="Throgs Neck",
                    property_type="single-family_house",
                ),
                ApprovedOutboundListingMatch(
                    neighborhood="Riverdale",
                    property_type="co-op",
                ),
            ),
        )
    )

    assert brief == ApprovedListingRelevanceBrief(
        search_basis="Bronx with 2+ beds",
        match_count=2,
        matching_areas=("Throgs Neck", "Riverdale"),
        matching_property_types=("single family house", "co op"),
        budget_alignment_note="the lead's stated budget",
        safe_talking_point=(
            "2 current StreetEasy matches line up with Bronx with 2+ beds and "
            "the lead's stated budget."
        ),
        safe_cta="Ask whether they want their assigned agent to send a few current options.",
        listing_context_source=None,
    )


async def test_includes_safe_listing_relevance_brief_in_prompt_when_present() -> None:
    llm = FakeLLMClient(_draft_json())

    await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Alex Agent",
        lead_context=ApprovedOutboundLeadContext(
            extracted_preferences={"location": "Bronx"},
            listing_context=ApprovedOutboundListingContext(
                source_name="StreetEasy",
                search_summary="sale in Bronx up to $750,000",
                result_count=1,
                matches=(
                    ApprovedOutboundListingMatch(
                        title="Single-family house in Throgs Neck",
                        address_text="2738 Miles Avenue, Bronx, NY 10465",
                        neighborhood="Throgs Neck",
                        price_text="$650,000",
                        beds_text="4 bd",
                        baths_text="1 ba",
                        source_url="https://streeteasy.com/building/2738-miles-avenue-bronx/1",
                        scraped_at=NOW.isoformat(),
                    ),
                ),
            ),
        ),
        llm_client=llm,
    )

    # v12 uses structured sections instead of JSON field names
    assert "# Approved Listing Context" in llm.requests[0].prompt
    assert "## Listing Relevance" in llm.requests[0].prompt
    assert "## Listing Message Guidance" in llm.requests[0].prompt
    assert "Bronx" in llm.requests[0].prompt
    assert "Throgs Neck" in llm.requests[0].prompt
    assert "StreetEasy" in llm.requests[0].prompt
    assert "Budget alignment:" in llm.requests[0].prompt
    assert "Use this factual basis once in general terms" in llm.requests[0].prompt
    assert "Ask whether they want their assigned agent to send a few current options." in (
        llm.requests[0].prompt
    )
    # Safety: should not include exact addresses or prices
    assert "2738 Miles Avenue" not in llm.requests[0].prompt
    assert "$650,000" not in llm.requests[0].prompt


async def test_prompt_forbids_implying_availability_when_no_listing_context() -> None:
    llm = FakeLLMClient(_draft_json())

    await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Alex Agent",
        lead_context=ApprovedOutboundLeadContext(
            latest_lead_request="Looking for 2 bedroom apartments in Queens under $2k/month.",
        ),
        llm_client=llm,
    )

    prompt = llm.requests[0].prompt
    # v12 shows a "No Listing Context Available" section when no listing context exists
    assert "# No Listing Context Available" in prompt
    assert "MUST NOT imply that listings, properties, or options are currently available" in prompt
    assert "great options available right now" in prompt


async def test_rejects_invalid_json_response() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Alex Agent",
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=FakeLLMClient("not json"),
    )

    assert result.status == OutboundMessageDraftStatus.REJECTED
    assert result.reasons == (OutboundMessageDraftReasonCode.INVALID_LLM_RESPONSE,)
    assert result.body is None


async def test_accepts_markdown_fenced_json_response() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Alex Agent",
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=FakeLLMClient(f"```json\n{_draft_json()}\n```"),
    )

    assert result.status == OutboundMessageDraftStatus.DRAFTED
    assert result.body is not None


async def test_accepts_common_llm_schema_variants() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.EMAIL,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Alex Agent",
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=FakeLLMClient(
            json.dumps(
                {
                    "body": "Checking in to see if you still want to continue the conversation.",
                    "subject": "Quick follow-up",
                    "confidence": "high",
                    "personalization_notes": (
                        "Lead is interested in a specific property and looking to buy soon."
                    ),
                    "safety_flags": [],
                }
            )
        ),
    )

    assert result.status == OutboundMessageDraftStatus.DRAFTED
    assert result.confidence == 0.9
    assert result.personalization_notes == (
        "Lead is interested in a specific property and looking to buy soon.",
    )


async def test_rejects_markdown_fenced_json_when_schema_is_invalid() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Alex Agent",
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=FakeLLMClient(
            "```json\n{\n"
            '  "body": "Checking in.",\n'
            '  "subject": null,\n'
            '  "confidence": 0.91,\n'
            '  "personalization_notes": ["Used safe lead stage context."],\n'
            '  "safety_flags": true\n'
            "}\n```"
        ),
    )

    assert result.status == OutboundMessageDraftStatus.REJECTED
    assert result.reasons == (OutboundMessageDraftReasonCode.INVALID_LLM_RESPONSE,)
    assert result.raw_llm_response_text is not None


async def test_rejects_invalid_confidence_string_outside_known_aliases() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Alex Agent",
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=FakeLLMClient(
            json.dumps(
                {
                    "body": "Checking in.",
                    "subject": None,
                    "confidence": "very high",
                    "personalization_notes": ["Used safe lead stage context."],
                    "safety_flags": [],
                }
            )
        ),
    )

    assert result.status == OutboundMessageDraftStatus.REJECTED
    assert result.reasons == (OutboundMessageDraftReasonCode.INVALID_LLM_RESPONSE,)


async def test_coerces_dict_shaped_list_fields_from_llm() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Alex Agent",
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=FakeLLMClient(
            json.dumps(
                {
                    "body": "Checking in to see if you still want to continue the conversation.",
                    "subject": None,
                    "confidence": 0.91,
                    "personalization_notes": {},
                    "safety_flags": {},
                }
            )
        ),
    )

    assert result.status == OutboundMessageDraftStatus.DRAFTED
    assert result.personalization_notes == ()
    assert result.safety_flags == ()


async def test_dict_shaped_safety_flags_with_entries_still_reject() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Alex Agent",
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=FakeLLMClient(
            json.dumps(
                {
                    "body": "Checking in.",
                    "subject": None,
                    "confidence": 0.91,
                    "personalization_notes": [],
                    "safety_flags": {"specific_property_request": True},
                }
            )
        ),
    )

    assert result.status == OutboundMessageDraftStatus.REJECTED
    assert result.reasons == (OutboundMessageDraftReasonCode.SAFETY_FLAGS_PRESENT,)


async def test_rejects_safety_flags_but_keeps_reviewable_body() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Alex Agent",
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=FakeLLMClient(_draft_json(safety_flags=("specific_property_request",))),
    )

    assert result.status == OutboundMessageDraftStatus.REJECTED
    assert result.reasons == (OutboundMessageDraftReasonCode.SAFETY_FLAGS_PRESENT,)
    assert result.body == "Hi there,\n\nare you still thinking about making a move this year?"


async def test_rejects_email_without_subject() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.EMAIL,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Alex Agent",
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=FakeLLMClient(_draft_json()),
    )

    assert result.status == OutboundMessageDraftStatus.REJECTED
    assert result.reasons == (OutboundMessageDraftReasonCode.MISSING_EMAIL_SUBJECT,)


async def test_allows_hardcoded_template_without_agent_placeholder() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=FakeLLMClient(_draft_json()),
        drafting_config=WorkspaceOutboundDraftingConfig(
            workspace_id=_lead().workspace_id,
            sms_prompt_text="Keep the SMS concise.",
            sms_template="Hi there",
            email_prompt_text="Keep the email concise.",
            email_template="Regards,\nMiller Schackman",
            email_subject_template="{{message_subject}} | Miller Schackman",
            enabled_extraction_fields=("location",),
        ),
    )

    assert result.status == OutboundMessageDraftStatus.DRAFTED
    assert result.reasons == ()
    assert result.body == "Hi there\n\nare you still thinking about making a move this year?"


async def test_substitutes_agent_placeholder_when_message_body_placeholder_is_missing() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Taylor Agent",
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=FakeLLMClient(_draft_json()),
        drafting_config=WorkspaceOutboundDraftingConfig(
            workspace_id=_lead().workspace_id,
            sms_prompt_text="Keep the SMS concise.",
            sms_template="Hi {{agent_name}}",
            email_prompt_text="Keep the email concise.",
            email_template="Regards,\n{{brokerage_name}}",
            email_subject_template="{{message_subject}} | {{brokerage_name}}",
            enabled_extraction_fields=("location",),
        ),
    )

    assert result.status == OutboundMessageDraftStatus.DRAFTED
    assert result.body == "Hi Taylor Agent\n\nare you still thinking about making a move this year?"


async def test_strips_duplicate_email_wrapper_from_generated_body() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.EMAIL,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Alex Agent",
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=FakeLLMClient(
            _draft_json(
                body=(
                    "Hi there,\n\n"
                    "I wanted to check whether Queens is still the right area for you.\n\n"
                    "Best,\n"
                    "Miller Schackman"
                ),
                subject="Quick follow-up",
            )
        ),
        drafting_config=WorkspaceOutboundDraftingConfig(
            workspace_id=_lead().workspace_id,
            email_template=(
                "Hello {{lead_first_name}},\n\n{{message_body}}\n\nBest,\n"
                "{{brokerage_name}}"
            ),
            email_subject_template="{{message_subject}} | {{brokerage_name}}",
        ),
    )

    assert result.status == OutboundMessageDraftStatus.DRAFTED
    assert result.body == (
        "Hello there,\n\n"
        "I wanted to check whether Queens is still the right area for you.\n\n"
        "Best,\n"
        "Miller Schackman"
    )


async def test_strips_greeting_variant_from_generated_email_body() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.EMAIL,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Alex Agent",
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=FakeLLMClient(
            _draft_json(
                body=(
                    "Hello,\n\n"
                    "I wanted to check whether Queens is still the right area for you."
                ),
                subject="Quick follow-up",
            )
        ),
    )

    assert result.status == OutboundMessageDraftStatus.DRAFTED
    assert result.body == (
        "Hi there,\n\n"
        "I wanted to check whether Queens is still the right area for you.\n\n"
        "Best,\n"
        "Miller Schackman"
    )


async def test_strips_duplicate_prefix_when_template_appends_message_body() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Taylor Agent",
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=FakeLLMClient(
            _draft_json(body="Hi Taylor Agent\n\nAre you still looking in Queens?")
        ),
        drafting_config=WorkspaceOutboundDraftingConfig(
            workspace_id=_lead().workspace_id,
            sms_prompt_text="Keep the SMS concise.",
            sms_template="Hi {{agent_name}}",
            email_prompt_text="Keep the email concise.",
            email_template="Regards,\n{{brokerage_name}}",
            email_subject_template="{{message_subject}} | {{brokerage_name}}",
            enabled_extraction_fields=("location",),
        ),
    )

    assert result.status == OutboundMessageDraftStatus.DRAFTED
    assert result.body == "Hi Taylor Agent\n\nAre you still looking in Queens?"


async def test_strips_inline_duplicate_sms_greeting() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name="Alex Agent",
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=FakeLLMClient(
            _draft_json(
                body=(
                    "Hi there! I wanted to check in and see if you're still interested "
                    "in finding a 2-bedroom apartment in Queens under $2k/month.\n"
                    "Would you like me to have your assigned agent send over a few current options?"
                )
            )
        ),
        drafting_config=WorkspaceOutboundDraftingConfig(
            workspace_id=_lead().workspace_id,
            sms_template="Hi there,\n\n{{message_body}}",
        ),
    )

    assert result.status == OutboundMessageDraftStatus.DRAFTED
    assert result.body == (
        "Hi there,\n\n"
        "I wanted to check in and see if you're still interested in finding a "
        "2-bedroom apartment in Queens under $2k/month.\n"
        "Would you like me to have your assigned agent send over a few current options?"
    )


async def test_requests_name_extraction_when_crm_name_missing() -> None:
    llm = FakeLLMClient(_draft_json())

    await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=llm,
    )

    prompt = llm.requests[0].prompt
    assert "The CRM record has no usable name for this lead." in prompt
    assert "lead_first_name (string or null)" in prompt


def _greeting_config(workspace_id: UUID) -> WorkspaceOutboundDraftingConfig:
    return WorkspaceOutboundDraftingConfig(
        workspace_id=workspace_id,
        sms_template="Hi {{lead_first_name}},\n\n{{message_body}}",
    )


async def test_does_not_request_name_extraction_when_crm_name_present() -> None:
    llm = FakeLLMClient(_draft_json())
    lead = _lead(display_name="Jordan Sample")

    result = await draft_outbound_message(
        lead=lead,
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=llm,
        drafting_config=_greeting_config(lead.workspace_id),
    )

    prompt = llm.requests[0].prompt
    assert "The CRM record has no usable name for this lead." not in prompt
    assert "Return only JSON" in prompt
    assert ", lead_first_name (string or null)" not in prompt
    assert result.body is not None
    assert result.body.startswith("Hi Jordan,")


async def test_uses_extracted_name_when_it_appears_in_approved_context() -> None:
    lead = _lead()
    result = await draft_outbound_message(
        lead=lead,
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        lead_context=ApprovedOutboundLeadContext(
            latest_lead_request=(
                "My name is Punej and i am looking for 2 bedroom apartments in Queens."
            ),
        ),
        llm_client=FakeLLMClient(_draft_json(lead_first_name="Punej")),
        drafting_config=_greeting_config(lead.workspace_id),
    )

    assert result.status == OutboundMessageDraftStatus.DRAFTED
    assert result.body is not None
    assert result.body.startswith("Hi Punej,")


async def test_uses_extracted_name_found_in_recent_conversation_items() -> None:
    lead = _lead()
    result = await draft_outbound_message(
        lead=lead,
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        lead_context=ApprovedOutboundLeadContext(
            recent_conversation_items=(
                ApprovedOutboundConversationItem(
                    occurred_at=NOW.isoformat(),
                    title="Inbound message",
                    content="Hi, this is marcus. Still looking in Riverdale.",
                    direction="inbound",
                ),
            ),
        ),
        llm_client=FakeLLMClient(_draft_json(lead_first_name="marcus")),
        drafting_config=_greeting_config(lead.workspace_id),
    )

    assert result.status == OutboundMessageDraftStatus.DRAFTED
    assert result.body is not None
    assert result.body.startswith("Hi Marcus,")


async def test_discards_extracted_name_not_present_in_context() -> None:
    lead = _lead()
    result = await draft_outbound_message(
        lead=lead,
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        lead_context=ApprovedOutboundLeadContext(
            latest_lead_request="Looking for 2 bedroom apartments in Queens.",
        ),
        llm_client=FakeLLMClient(_draft_json(lead_first_name="Punej")),
        drafting_config=_greeting_config(lead.workspace_id),
    )

    assert result.status == OutboundMessageDraftStatus.DRAFTED
    assert result.body is not None
    assert result.body.startswith("Hi there,")


async def test_discards_extracted_name_that_is_not_name_shaped() -> None:
    lead = _lead()
    result = await draft_outbound_message(
        lead=lead,
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        lead_context=ApprovedOutboundLeadContext(
            latest_lead_request="Reach me at punej@example.com about Queens apartments.",
        ),
        llm_client=FakeLLMClient(_draft_json(lead_first_name="punej@example.com")),
        drafting_config=_greeting_config(lead.workspace_id),
    )

    assert result.status == OutboundMessageDraftStatus.DRAFTED
    assert result.body is not None
    assert result.body.startswith("Hi there,")


async def test_crm_name_takes_precedence_over_extracted_name() -> None:
    lead = _lead(display_name="Jordan Sample")
    result = await draft_outbound_message(
        lead=lead,
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        lead_context=ApprovedOutboundLeadContext(
            latest_lead_request="My name is Punej.",
        ),
        llm_client=FakeLLMClient(_draft_json(lead_first_name="Punej")),
        drafting_config=_greeting_config(lead.workspace_id),
    )

    assert result.status == OutboundMessageDraftStatus.DRAFTED
    assert result.body is not None
    assert result.body.startswith("Hi Jordan,")
