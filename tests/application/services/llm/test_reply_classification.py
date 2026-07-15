import json
from datetime import UTC, datetime
from uuid import uuid4

from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.services.llm.reply_classification import (
    ReplyClassificationReasonCode,
    ReplyClassificationStatus,
    classify_inbound_reply,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


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
            latency_ms=19,
            usage_tokens=51,
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


def _classification_json(
    *,
    intent: str = "human_requested",
    confidence: float = 0.91,
    handoff_required: bool = True,
    handoff_reason: str | None = "human_requested",
    opt_out_detected: bool = False,
    summary_text: str = "Lead asked to speak with an agent.",
    preferences: dict[str, str] | None = None,
) -> str:
    return json.dumps(
        {
            "intent": intent,
            "confidence": confidence,
            "handoff_required": handoff_required,
            "handoff_reason": handoff_reason,
            "opt_out_detected": opt_out_detected,
            "summary_text": summary_text,
            "preferences": preferences or {"timeline": "soon"},
        },
    )


async def test_classifies_human_request_and_builds_versioned_prompt() -> None:
    llm = FakeLLMClient(_classification_json())

    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="Can someone call me today?",
        llm_client=llm,
    )

    assert result.status == ReplyClassificationStatus.CLASSIFIED
    assert result.handoff_required is True
    assert result.handoff_reason is not None
    assert result.summary_text == "Lead asked to speak with an agent."
    assert llm.requests[0].prompt_version == "inbound_reply_classification:v1"
    assert "Can someone call me today?" in llm.requests[0].prompt


async def test_rejects_invalid_json_response() -> None:
    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="Stop texting me.",
        llm_client=FakeLLMClient("not-json"),
    )

    assert result.status == ReplyClassificationStatus.REJECTED
    assert result.reasons == (ReplyClassificationReasonCode.INVALID_LLM_RESPONSE,)


async def test_accepts_markdown_fenced_json_response() -> None:
    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="Can someone call me today?",
        llm_client=FakeLLMClient(f"```json\n{_classification_json()}\n```"),
    )

    assert result.status == ReplyClassificationStatus.CLASSIFIED
    assert result.handoff_required is True


async def test_accepts_confidence_alias_string() -> None:
    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="Can someone call me today?",
        llm_client=FakeLLMClient(
            _classification_json(confidence="high")
        ),
    )

    assert result.status == ReplyClassificationStatus.CLASSIFIED
    assert result.confidence == 0.9


async def test_rejects_low_confidence_response() -> None:
    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="Maybe later.",
        llm_client=FakeLLMClient(
            _classification_json(
                intent="general_reply",
                confidence=0.2,
                handoff_required=False,
                handoff_reason=None,
                summary_text="Lead replied but intent is unclear.",
            ),
        ),
    )

    assert result.status == ReplyClassificationStatus.REJECTED
    assert result.reasons == (ReplyClassificationReasonCode.LOW_CONFIDENCE,)
