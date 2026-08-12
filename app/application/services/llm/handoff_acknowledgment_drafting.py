import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.application.ports.llm import LLMClient, LLMCompletionRequest
from app.application.services.llm.structured_json import (
    coerce_llm_confidence,
    coerce_string_tuple,
    normalize_llm_json_text,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import CanonicalLeadRecord
from app.domain.llm import LLMProviderKind, LLMTaskKind

HANDOFF_ACKNOWLEDGMENT_DRAFT_PROMPT_VERSION_PREFIX = "handoff_acknowledgment_draft:v2"
DEFAULT_LEAD_ACKNOWLEDGMENT_PROMPT_TEXT = (
    "You are the brokerage's acknowledgment drafting assistant. Draft a short, warm "
    "message that confirms receipt, acknowledges the lead's message in a natural way, "
    "and clearly says that a human agent or team member will follow up soon."
)
MIN_DRAFT_CONFIDENCE = 0.7
MAX_SMS_BODY_LENGTH = 320
MAX_EMAIL_BODY_LENGTH = 4000
PROHIBITED_MESSAGE_TERMS = (
    "guarantee",
    "legal advice",
    "tax advice",
    "investment advice",
    "mortgage approval",
    "pre-approved",
)


class HandoffAcknowledgmentDraftStatus(StrEnum):
    DRAFTED = "drafted"
    REJECTED = "rejected"


class HandoffAcknowledgmentDraftReasonCode(StrEnum):
    INVALID_LLM_RESPONSE = "invalid_llm_response"
    LOW_CONFIDENCE = "low_confidence"
    SAFETY_FLAGS_PRESENT = "safety_flags_present"
    BODY_TOO_LONG = "body_too_long"
    PROHIBITED_CONTENT = "prohibited_content"


@dataclass(frozen=True)
class HandoffAcknowledgmentDraftResult:
    status: HandoffAcknowledgmentDraftStatus
    prompt_version: str
    model: str | None = None
    latency_ms: int | None = None
    usage_tokens: int | None = None
    body: str | None = None
    subject: str | None = None
    raw_llm_response_text: str | None = None
    validation_error: str | None = None
    confidence: float | None = None
    safety_flags: tuple[str, ...] = ()
    reasons: tuple[HandoffAcknowledgmentDraftReasonCode, ...] = ()


class _LLMHandoffAcknowledgmentDraft(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_EMAIL_BODY_LENGTH)
    subject: str | None = Field(default=None, max_length=120)
    confidence: float = Field(ge=0.0, le=1.0)
    safety_flags: tuple[str, ...] = ()

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> object:
        return coerce_llm_confidence(value)

    @field_validator("safety_flags", mode="before")
    @classmethod
    def _coerce_string_collections(cls, value: object) -> object:
        return coerce_string_tuple(value)


async def draft_handoff_acknowledgment(
    *,
    lead: CanonicalLeadRecord,
    channel: ContactChannel,
    inbound_text: str,
    inbound_email_subject: str | None,
    handoff_reason_code: str,
    handoff_summary: str | None,
    recent_conversation_context: str | None,
    brokerage_name: str | None,
    assigned_agent_name: str | None,
    admin_prompt_text: str | None,
    reply_in_existing_email_thread: bool,
    llm_client: LLMClient,
    model: str | None = None,
    provider: LLMProviderKind | None = None,
    min_confidence: float = MIN_DRAFT_CONFIDENCE,
) -> HandoffAcknowledgmentDraftResult:
    resolved_prompt_text = resolve_lead_acknowledgment_prompt_text(admin_prompt_text)
    prompt_version = _prompt_version_for_text(resolved_prompt_text)
    llm_result = await llm_client.complete(
        LLMCompletionRequest(
            prompt=_build_prompt(
                lead=lead,
                channel=channel,
                inbound_text=inbound_text,
                inbound_email_subject=inbound_email_subject,
                handoff_reason_code=handoff_reason_code,
                handoff_summary=handoff_summary,
                recent_conversation_context=recent_conversation_context,
                brokerage_name=brokerage_name,
                assigned_agent_name=assigned_agent_name,
                admin_prompt_text=resolved_prompt_text,
                reply_in_existing_email_thread=reply_in_existing_email_thread,
            ),
            prompt_version=prompt_version,
            model=model,
            provider=provider,
            task=LLMTaskKind.DRAFTING,
            temperature=0.4,
            max_tokens=300,
        )
    )

    try:
        draft = _LLMHandoffAcknowledgmentDraft.model_validate_json(
            normalize_llm_json_text(llm_result.text)
        )
    except ValidationError as exc:
        return HandoffAcknowledgmentDraftResult(
            status=HandoffAcknowledgmentDraftStatus.REJECTED,
            prompt_version=llm_result.prompt_version,
            model=llm_result.model,
            latency_ms=llm_result.latency_ms,
            usage_tokens=llm_result.usage_tokens,
            raw_llm_response_text=llm_result.text,
            validation_error=str(exc),
            reasons=(HandoffAcknowledgmentDraftReasonCode.INVALID_LLM_RESPONSE,),
        )

    reasons = _blocking_reasons(
        _validation_reasons(draft, channel=channel, min_confidence=min_confidence)
    )
    status = (
        HandoffAcknowledgmentDraftStatus.REJECTED
        if reasons
        else HandoffAcknowledgmentDraftStatus.DRAFTED
    )
    return HandoffAcknowledgmentDraftResult(
        status=status,
        prompt_version=llm_result.prompt_version,
        model=llm_result.model,
        latency_ms=llm_result.latency_ms,
        usage_tokens=llm_result.usage_tokens,
        body=draft.body.strip(),
        subject=draft.subject.strip() if draft.subject else None,
        raw_llm_response_text=llm_result.text,
        confidence=draft.confidence,
        safety_flags=draft.safety_flags,
        reasons=tuple(reasons),
    )


def resolve_lead_acknowledgment_prompt_text(prompt_text: str | None) -> str:
    normalized = (prompt_text or "").strip()
    if normalized:
        return normalized
    return DEFAULT_LEAD_ACKNOWLEDGMENT_PROMPT_TEXT


def _validation_reasons(
    draft: _LLMHandoffAcknowledgmentDraft,
    *,
    channel: ContactChannel,
    min_confidence: float,
) -> list[HandoffAcknowledgmentDraftReasonCode]:
    reasons: list[HandoffAcknowledgmentDraftReasonCode] = []
    if draft.confidence < min_confidence:
        reasons.append(HandoffAcknowledgmentDraftReasonCode.LOW_CONFIDENCE)
    if draft.safety_flags:
        reasons.append(HandoffAcknowledgmentDraftReasonCode.SAFETY_FLAGS_PRESENT)
    body_limit = MAX_SMS_BODY_LENGTH if channel == ContactChannel.SMS else MAX_EMAIL_BODY_LENGTH
    if len(draft.body.strip()) > body_limit:
        reasons.append(HandoffAcknowledgmentDraftReasonCode.BODY_TOO_LONG)
    if _contains_prohibited_content(draft.body):
        reasons.append(HandoffAcknowledgmentDraftReasonCode.PROHIBITED_CONTENT)
    return reasons


def _blocking_reasons(
    reasons: list[HandoffAcknowledgmentDraftReasonCode],
) -> list[HandoffAcknowledgmentDraftReasonCode]:
    if reasons == [HandoffAcknowledgmentDraftReasonCode.LOW_CONFIDENCE]:
        return []
    return reasons


def _contains_prohibited_content(body: str) -> bool:
    normalized = body.lower()
    return any(term in normalized for term in PROHIBITED_MESSAGE_TERMS)


def _build_prompt(
    *,
    lead: CanonicalLeadRecord,
    channel: ContactChannel,
    inbound_text: str,
    inbound_email_subject: str | None,
    handoff_reason_code: str,
    handoff_summary: str | None,
    recent_conversation_context: str | None,
    brokerage_name: str | None,
    assigned_agent_name: str | None,
    admin_prompt_text: str,
    reply_in_existing_email_thread: bool,
) -> str:
    payload = {
        "task": "draft_human_handoff_acknowledgment",
        "channel": channel.value,
        "reply_mode": (
            "threaded_email_reply" if reply_in_existing_email_thread else "standalone_message"
        ),
        "admin_prompt_text": admin_prompt_text,
        "brokerage_name": brokerage_name,
        "assigned_agent_name": assigned_agent_name,
        "handoff_reason_code": handoff_reason_code,
        "handoff_summary": handoff_summary,
        "known_lead_facts": {
            "lead_source": lead.lead_source,
            "lead_stage": lead.lead_stage,
            "lead_type": lead.lead_type.value,
        },
        "latest_inbound_message": {
            "body": inbound_text,
            "email_subject": inbound_email_subject,
        },
        "recent_conversation_context": recent_conversation_context,
    }
    return (
        f"{admin_prompt_text}\n\n"
        "You are drafting a short acknowledgment for a real estate brokerage after the "
        "application has already decided a human handoff is required.\n\n"
        "Rules:\n"
        "- Acknowledge receipt in a warm, concise, professional tone.\n"
        "- Make the message feel like a real reply to this specific conversation, "
        "not a canned template.\n"
        "- Use the recent conversation context and handoff summary when they help "
        "you acknowledge what the lead is asking about.\n"
        "- Briefly reference the topic or request only when it is clearly supported "
        "by the provided context.\n"
        "- Confirm that a human agent or team member will follow up.\n"
        "- Do not answer the lead's substantive question.\n"
        "- Do not discuss listings, pricing, market conditions, financing, legal, tax, "
        "or investment advice.\n"
        "- Do not invent facts, availability, or promises about timing beyond a general "
        "follow-up expectation.\n"
        "- Keep SMS concise. Keep email concise and natural.\n"
        "- If this is a threaded email reply, the application will preserve the existing "
        "subject line.\n\n"
        "Return JSON only with this shape:\n"
        '{"body":"...","subject":"... or null","confidence":0.0,"safety_flags":[]}\n\n'
        f"Context JSON:\n{json.dumps(payload, indent=2, sort_keys=True)}"
    )


def _prompt_version_for_text(prompt_text: str) -> str:
    digest = hashlib.sha1(prompt_text.encode("utf-8")).hexdigest()[:8]
    return f"{HANDOFF_ACKNOWLEDGMENT_DRAFT_PROMPT_VERSION_PREFIX}:p{digest}"
