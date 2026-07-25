from app.application.services.llm.reply_classification import (
    InboundReplyIntent,
    InboundReplyRuleEvidence,
    ReplyClassificationResult,
    ReplyClassificationStatus,
)
from app.application.use_cases.evaluate_inbound_action import (
    InboundAction,
    InboundActionReasonCode,
    evaluate_inbound_action,
)
from app.domain.conversations import HandoffReasonCode


def test_rejected_classification_requires_review() -> None:
    decision = evaluate_inbound_action(
        ReplyClassificationResult(
            status=ReplyClassificationStatus.REJECTED,
            prompt_version="test:v1",
        )
    )

    assert decision.action == InboundAction.PAUSE_FOR_REVIEW
    assert decision.reason_code == InboundActionReasonCode.CLASSIFICATION_REJECTED


def test_opt_out_suppresses_outreach() -> None:
    decision = evaluate_inbound_action(
        ReplyClassificationResult(
            status=ReplyClassificationStatus.CLASSIFIED,
            prompt_version="test:v1",
            intent=InboundReplyIntent.OPT_OUT,
            opt_out_detected=True,
            summary_text="Lead opted out.",
        )
    )

    assert decision.action == InboundAction.SUPPRESS
    assert decision.reason_code == InboundActionReasonCode.OPT_OUT_DETECTED


def test_human_request_evidence_controls_human_handoff() -> None:
    decision = evaluate_inbound_action(
        ReplyClassificationResult(
            status=ReplyClassificationStatus.CLASSIFIED,
            prompt_version="test:v1",
            intent=InboundReplyIntent.GENERAL_REPLY,
            evidence=InboundReplyRuleEvidence(asks_for_human=True),
            summary_text="Lead asked about financing.",
        )
    )

    assert decision.action == InboundAction.HUMAN_HANDOFF
    assert decision.reason_code == InboundActionReasonCode.HUMAN_REQUESTED
    assert decision.handoff_reason == HandoffReasonCode.HUMAN_REQUESTED


def test_unclear_intent_requires_review() -> None:
    decision = evaluate_inbound_action(
        ReplyClassificationResult(
            status=ReplyClassificationStatus.CLASSIFIED,
            prompt_version="test:v1",
            intent=InboundReplyIntent.UNCLEAR,
            summary_text="Lead replied ambiguously.",
        )
    )

    assert decision.action == InboundAction.PAUSE_FOR_REVIEW
    assert decision.reason_code == InboundActionReasonCode.UNCLEAR_INTENT


def test_general_reply_is_marked_for_future_ai_continuation() -> None:
    decision = evaluate_inbound_action(
        ReplyClassificationResult(
            status=ReplyClassificationStatus.CLASSIFIED,
            prompt_version="test:v1",
            intent=InboundReplyIntent.GENERAL_REPLY,
            summary_text="Lead replied generally.",
        )
    )

    assert decision.action == InboundAction.CONTINUE_AI
    assert decision.reason_code == InboundActionReasonCode.GENERAL_REPLY


def test_not_interested_stops_automation_without_suppression() -> None:
    decision = evaluate_inbound_action(
        ReplyClassificationResult(
            status=ReplyClassificationStatus.CLASSIFIED,
            prompt_version="test:v1",
            intent=InboundReplyIntent.NOT_INTERESTED,
            summary_text="Lead said they are not interested right now.",
        )
    )

    assert decision.action == InboundAction.COMPLETE_AUTOMATION
    assert decision.reason_code == InboundActionReasonCode.NOT_INTERESTED


def test_property_or_advice_evidence_forces_handoff_even_when_intent_is_general_reply() -> None:
    decision = evaluate_inbound_action(
        ReplyClassificationResult(
            status=ReplyClassificationStatus.CLASSIFIED,
            prompt_version="test:v1",
            intent=InboundReplyIntent.GENERAL_REPLY,
            evidence=InboundReplyRuleEvidence(asks_property_or_advice=True),
            summary_text="Lead asked about a condo and financing.",
        )
    )

    assert decision.action == InboundAction.HUMAN_HANDOFF
    assert decision.reason_code == InboundActionReasonCode.SPECIFIC_PROPERTY_OR_ADVICE
    assert decision.handoff_reason == HandoffReasonCode.SPECIFIC_PROPERTY_OR_ADVICE


def test_human_request_takes_precedence_over_unclear_intent() -> None:
    decision = evaluate_inbound_action(
        ReplyClassificationResult(
            status=ReplyClassificationStatus.CLASSIFIED,
            prompt_version="test:v1",
            intent=InboundReplyIntent.UNCLEAR,
            evidence=InboundReplyRuleEvidence(asks_for_human=True),
            summary_text="Lead asked for a callback in a vague message.",
        )
    )

    assert decision.action == InboundAction.HUMAN_HANDOFF
    assert decision.reason_code == InboundActionReasonCode.HUMAN_REQUESTED


def test_property_or_advice_takes_precedence_over_high_interest() -> None:
    decision = evaluate_inbound_action(
        ReplyClassificationResult(
            status=ReplyClassificationStatus.CLASSIFIED,
            prompt_version="test:v1",
            intent=InboundReplyIntent.HIGH_INTEREST,
            evidence=InboundReplyRuleEvidence(
                shows_buying_interest=True,
                asks_property_or_advice=True,
            ),
            summary_text="Lead wants details on a listing and financing.",
        )
    )

    assert decision.action == InboundAction.HUMAN_HANDOFF
    assert decision.reason_code == InboundActionReasonCode.SPECIFIC_PROPERTY_OR_ADVICE