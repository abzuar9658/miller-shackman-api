import json
from datetime import UTC, datetime
from uuid import uuid4

from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.services.llm.handoff_acknowledgment_drafting import (
    HandoffAcknowledgmentDraftReasonCode,
    HandoffAcknowledgmentDraftStatus,
    draft_handoff_acknowledgment,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import CanonicalLeadRecord, CRMProvider

NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


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
            latency_ms=21,
            usage_tokens=33,
        )


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=uuid4(),
        lead_id=uuid4(),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="long_term_nurture",
    )


def _draft_json(
    *,
    body: str,
    subject: str | None = None,
    confidence: float = 0.91,
    safety_flags: tuple[str, ...] = (),
) -> str:
    return json.dumps(
        {
            "body": body,
            "subject": subject,
            "confidence": confidence,
            "safety_flags": list(safety_flags),
        }
    )


async def test_drafts_sms_acknowledgment_with_default_prompt_and_context() -> None:
    llm = FakeLLMClient(
        _draft_json(body="Thanks for reaching out — a team member will follow up shortly.")
    )

    result = await draft_handoff_acknowledgment(
        lead=_lead(),
        channel=ContactChannel.SMS,
        inbound_text="Can an agent call me today?",
        inbound_email_subject=None,
        handoff_reason_code="human_requested",
        handoff_summary="Lead asked for a callback today.",
        recent_conversation_context=(
            "brokerage [sms]: Thanks for reaching out about moving.\n"
            "lead [sms]: Can an agent call me today?"
        ),
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        admin_prompt_text=None,
        reply_in_existing_email_thread=False,
        llm_client=llm,
    )

    assert result.status == HandoffAcknowledgmentDraftStatus.DRAFTED
    assert result.body == "Thanks for reaching out — a team member will follow up shortly."
    assert llm.requests[0].prompt_version.startswith("handoff_acknowledgment_draft:v2:p")
    assert "Lead asked for a callback today." in llm.requests[0].prompt
    assert "brokerage [sms]: Thanks for reaching out about moving." in llm.requests[0].prompt
    assert "human_requested" in llm.requests[0].prompt
    assert "Can an agent call me today?" in llm.requests[0].prompt
    assert "Do not answer the lead's substantive question." in llm.requests[0].prompt


async def test_uses_admin_configured_acknowledgment_prompt_text() -> None:
    llm = FakeLLMClient(_draft_json(body="Thanks — our team will be in touch soon."))

    await draft_handoff_acknowledgment(
        lead=_lead(),
        channel=ContactChannel.EMAIL,
        inbound_text="Can someone tell me more about this condo?",
        inbound_email_subject="Re: Condo question",
        handoff_reason_code="specific_property_or_advice",
        handoff_summary="Lead wants to know more about a condo.",
        recent_conversation_context="lead [email]: Can someone tell me more about this condo?",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        admin_prompt_text="Keep it reassuring, brief, and never promise exact timing.",
        reply_in_existing_email_thread=True,
        llm_client=llm,
    )

    assert "Keep it reassuring, brief, and never promise exact timing." in llm.requests[0].prompt
    assert "threaded_email_reply" in llm.requests[0].prompt


async def test_rejects_acknowledgment_when_safety_flags_are_present() -> None:
    llm = FakeLLMClient(
        _draft_json(
            body="Thanks — our team will follow up.",
            confidence=0.95,
            safety_flags=("mentioned financing advice",),
        )
    )

    result = await draft_handoff_acknowledgment(
        lead=_lead(),
        channel=ContactChannel.SMS,
        inbound_text="Can you advise on the mortgage?",
        inbound_email_subject=None,
        handoff_reason_code="specific_property_or_advice",
        handoff_summary="Lead asked for mortgage advice.",
        recent_conversation_context="lead [sms]: Can you advise on the mortgage?",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        admin_prompt_text=None,
        reply_in_existing_email_thread=False,
        llm_client=llm,
    )

    assert result.status == HandoffAcknowledgmentDraftStatus.REJECTED
    assert result.reasons == (HandoffAcknowledgmentDraftReasonCode.SAFETY_FLAGS_PRESENT,)


async def test_accepts_acknowledgment_when_low_confidence_is_only_issue() -> None:
    llm = FakeLLMClient(
        _draft_json(
            body="Hi there! Thanks for your message. A member of our team will follow up soon.",
            confidence=0.0,
        )
    )

    result = await draft_handoff_acknowledgment(
        lead=_lead(),
        channel=ContactChannel.SMS,
        inbound_text="Can someone help me today?",
        inbound_email_subject=None,
        handoff_reason_code="human_requested",
        handoff_summary="Lead asked for human follow-up.",
        recent_conversation_context="lead [sms]: Can someone help me today?",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        admin_prompt_text=None,
        reply_in_existing_email_thread=False,
        llm_client=llm,
    )

    assert result.status == HandoffAcknowledgmentDraftStatus.DRAFTED
    assert result.body == (
        "Hi there! Thanks for your message. A member of our team will follow up soon."
    )
    assert result.confidence == 0.0
    assert result.reasons == ()


async def test_rejects_acknowledgment_when_low_confidence_has_other_failure() -> None:
    llm = FakeLLMClient(
        _draft_json(
            body="We guarantee our team will answer your legal advice question shortly.",
            confidence=0.0,
        )
    )

    result = await draft_handoff_acknowledgment(
        lead=_lead(),
        channel=ContactChannel.SMS,
        inbound_text="Can you help with legal paperwork?",
        inbound_email_subject=None,
        handoff_reason_code="specific_property_or_advice",
        handoff_summary="Lead asked for legal advice.",
        recent_conversation_context="lead [sms]: Can you help with legal paperwork?",
        brokerage_name="Miller Schackman",
        assigned_agent_name=None,
        admin_prompt_text=None,
        reply_in_existing_email_thread=False,
        llm_client=llm,
    )

    assert result.status == HandoffAcknowledgmentDraftStatus.REJECTED
    assert result.reasons == (
        HandoffAcknowledgmentDraftReasonCode.LOW_CONFIDENCE,
        HandoffAcknowledgmentDraftReasonCode.PROHIBITED_CONTENT,
    )