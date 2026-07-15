import json
from datetime import UTC, datetime
from uuid import uuid4

from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.services.llm.outbound_message_drafting import (
    ApprovedOutboundLeadContext,
    OutboundMessageDraftReasonCode,
    OutboundMessageDraftStatus,
    draft_outbound_message,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import CanonicalLeadRecord, CRMProvider

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


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=uuid4(),
        lead_id=uuid4(),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="long_term_nurture",
    )


def _draft_json(
    *,
    body: str = "Hi — are you still thinking about making a move this year?",
    subject: str | None = None,
    confidence: float = 0.91,
    safety_flags: tuple[str, ...] = (),
) -> str:
    return json.dumps(
        {
            "body": body,
            "subject": subject,
            "confidence": confidence,
            "personalization_notes": ["Used safe lead stage context."],
            "safety_flags": list(safety_flags),
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
            latest_lead_request="Asked about homes near Austin.",
            extracted_preferences={"location": "Austin"},
        ),
        llm_client=llm,
    )

    assert result.status == OutboundMessageDraftStatus.DRAFTED
    assert result.body == "Hi — are you still thinking about making a move this year?"
    assert result.model == "openai/gpt-4o-mini"
    assert result.usage_tokens == 42
    assert llm.requests[0].prompt_version == "outbound_message_draft:v1"
    assert "Austin" in llm.requests[0].prompt
    assert "Do not invent listings" in llm.requests[0].prompt


async def test_rejects_invalid_json_response() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
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
        assigned_agent_name=None,
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
        assigned_agent_name=None,
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
        assigned_agent_name=None,
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
        assigned_agent_name=None,
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


async def test_rejects_safety_flags_but_keeps_reviewable_body() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.SMS,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=FakeLLMClient(_draft_json(safety_flags=("specific_property_request",))),
    )

    assert result.status == OutboundMessageDraftStatus.REJECTED
    assert result.reasons == (OutboundMessageDraftReasonCode.SAFETY_FLAGS_PRESENT,)
    assert result.body == "Hi — are you still thinking about making a move this year?"


async def test_rejects_email_without_subject() -> None:
    result = await draft_outbound_message(
        lead=_lead(),
        channel=ContactChannel.EMAIL,
        campaign_goal="Re-engage dormant buyer leads.",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        lead_context=ApprovedOutboundLeadContext(),
        llm_client=FakeLLMClient(_draft_json()),
    )

    assert result.status == OutboundMessageDraftStatus.REJECTED
    assert result.reasons == (OutboundMessageDraftReasonCode.MISSING_EMAIL_SUBJECT,)
