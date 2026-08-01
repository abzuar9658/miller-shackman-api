from dataclasses import dataclass
from enum import StrEnum

from app.application.services.llm.reply_classification import (
    InboundReplyIntent,
    ReplyClassificationResult,
    ReplyClassificationStatus,
)
from app.domain.conversations import HandoffReasonCode


class InboundAction(StrEnum):
    SUPPRESS = "suppress"
    HUMAN_HANDOFF = "human_handoff"
    PAUSE_FOR_REVIEW = "pause_for_review"
    COMPLETE_AUTOMATION = "complete_automation"
    CONTINUE_AI = "continue_ai"


class InboundActionReasonCode(StrEnum):
    CLASSIFICATION_REJECTED = "classification_rejected"
    OPT_OUT_DETECTED = "opt_out_detected"
    HUMAN_REQUESTED = "human_requested"
    HIGH_INTEREST = "high_interest"
    SELLER_INTEREST = "seller_interest"
    SPECIFIC_PROPERTY_OR_ADVICE = "specific_property_or_advice"
    UNCLEAR_INTENT = "unclear_intent"
    NOT_INTERESTED = "not_interested"
    GENERAL_REPLY = "general_reply"


@dataclass(frozen=True)
class InboundActionDecision:
    action: InboundAction
    reason_code: InboundActionReasonCode
    handoff_reason: HandoffReasonCode | None = None


def evaluate_inbound_action(
    classification: ReplyClassificationResult,
) -> InboundActionDecision:
    if classification.status == ReplyClassificationStatus.REJECTED:
        return InboundActionDecision(
            action=InboundAction.PAUSE_FOR_REVIEW,
            reason_code=InboundActionReasonCode.CLASSIFICATION_REJECTED,
        )

    if classification.opt_out_detected or classification.intent == InboundReplyIntent.OPT_OUT:
        return InboundActionDecision(
            action=InboundAction.SUPPRESS,
            reason_code=InboundActionReasonCode.OPT_OUT_DETECTED,
        )

    handoff_reason = _handoff_reason_from_classification(classification)
    if handoff_reason is not None:
        return InboundActionDecision(
            action=InboundAction.HUMAN_HANDOFF,
            reason_code=_handoff_reason_to_action_reason(handoff_reason),
            handoff_reason=handoff_reason,
        )

    if classification.intent == InboundReplyIntent.UNCLEAR:
        return InboundActionDecision(
            action=InboundAction.PAUSE_FOR_REVIEW,
            reason_code=InboundActionReasonCode.UNCLEAR_INTENT,
        )

    if classification.intent == InboundReplyIntent.NOT_INTERESTED:
        return InboundActionDecision(
            action=InboundAction.COMPLETE_AUTOMATION,
            reason_code=InboundActionReasonCode.NOT_INTERESTED,
        )

    return InboundActionDecision(
        action=InboundAction.CONTINUE_AI,
        reason_code=InboundActionReasonCode.GENERAL_REPLY,
    )


def _handoff_reason_to_action_reason(
    handoff_reason: HandoffReasonCode,
) -> InboundActionReasonCode:
    if handoff_reason == HandoffReasonCode.HUMAN_REQUESTED:
        return InboundActionReasonCode.HUMAN_REQUESTED
    if handoff_reason == HandoffReasonCode.HIGH_INTEREST:
        return InboundActionReasonCode.HIGH_INTEREST
    if handoff_reason == HandoffReasonCode.SELLER_INTEREST:
        return InboundActionReasonCode.SELLER_INTEREST
    return InboundActionReasonCode.SPECIFIC_PROPERTY_OR_ADVICE


def _handoff_reason_from_classification(
    classification: ReplyClassificationResult,
) -> HandoffReasonCode | None:
    if (
        classification.evidence.asks_for_human
        or classification.intent == InboundReplyIntent.HUMAN_REQUESTED
    ):
        return HandoffReasonCode.HUMAN_REQUESTED
    if classification.evidence.asks_property_or_advice:
        return HandoffReasonCode.SPECIFIC_PROPERTY_OR_ADVICE
    if (
        classification.evidence.shows_selling_interest
        or classification.intent == InboundReplyIntent.SELLER_INTEREST
    ):
        return HandoffReasonCode.SELLER_INTEREST
    if (
        classification.evidence.shows_buying_interest
        or classification.intent == InboundReplyIntent.HIGH_INTEREST
    ):
        return HandoffReasonCode.HIGH_INTEREST
    return None
