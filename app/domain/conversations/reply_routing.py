"""Journey-aware reply routing rules.

The LLM scores every direction a reply can take; these rules decide. Handoff is
earned only by high interest or an explicit request for a person — a confused
or vague reply always continues the current journey, never interrupts a human.
Consent and opt-out are handled upstream and never reach this layer.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.conversations.models import HandoffReasonCode


class ReplyRouteOption(StrEnum):
    """The three directions the reply router scores for every inbound reply."""

    CONTINUE = "continue"
    HUMAN_HANDOFF = "human_handoff"
    SUPPRESSED = "suppressed"


class ReplyRouteAction(StrEnum):
    """What the system actually does with the reply."""

    CONTINUE = "continue"
    HUMAN_HANDOFF = "human_handoff"
    SUPPRESS = "suppress"
    # The router's output failed validation — a system failure, not a confused
    # lead — so a human reviews the processing gap, not the lead's intent.
    REVIEW = "review"


@dataclass(frozen=True)
class ReplyRouteEvidence:
    """Deterministic evidence from the first-pass reply classifier."""

    asks_for_human: bool = False
    shows_buying_interest: bool = False
    shows_selling_interest: bool = False
    asks_property_or_advice: bool = False
    # InboundReplyIntent lives in the application layer; compared as strings here.
    intent: str | None = None


@dataclass(frozen=True)
class ReplyRouteDecisionResult:
    action: ReplyRouteAction
    reason: str
    handoff_reason: HandoffReasonCode | None = None
    # Set only when a paused-search reply stated an earlier concrete timing and
    # the pull-in rule applied; None means the current schedule stands.
    adjusted_reengagement_not_before: datetime | None = None


_HUMAN_REQUEST_INTENT = "human_requested"
_HIGH_INTEREST_INTENT = "high_interest"
_SELLER_INTEREST_INTENT = "seller_interest"


def decide_reply_route(
    *,
    router_decision: ReplyRouteOption | None,
    router_rejected: bool,
    evidence: ReplyRouteEvidence,
    proposed_reengagement_not_before: datetime | None = None,
    current_reengagement_not_before: datetime | None = None,
    now: datetime,
) -> ReplyRouteDecisionResult:
    """Resolve what a reply does to the current journey.

    An explicit request for a person always hands off. Otherwise the router's
    winning option is honored — except a handoff without any interest or advice
    evidence, which is treated as a confused read and continues the journey.
    """
    if evidence.asks_for_human or evidence.intent == _HUMAN_REQUEST_INTENT:
        return ReplyRouteDecisionResult(
            action=ReplyRouteAction.HUMAN_HANDOFF,
            reason="human_requested",
            handoff_reason=HandoffReasonCode.HUMAN_REQUESTED,
        )
    if router_rejected or router_decision is None:
        return ReplyRouteDecisionResult(
            action=ReplyRouteAction.REVIEW,
            reason="reply_route_classification_rejected",
        )
    if router_decision is ReplyRouteOption.SUPPRESSED:
        return ReplyRouteDecisionResult(
            action=ReplyRouteAction.SUPPRESS,
            reason="reply_router_suppressed",
        )
    if router_decision is ReplyRouteOption.HUMAN_HANDOFF:
        handoff_reason = _interest_handoff_reason(evidence)
        if handoff_reason is None:
            return ReplyRouteDecisionResult(
                action=ReplyRouteAction.CONTINUE,
                reason="handoff_without_interest_evidence",
            )
        return ReplyRouteDecisionResult(
            action=ReplyRouteAction.HUMAN_HANDOFF,
            reason=handoff_reason.value,
            handoff_reason=handoff_reason,
        )
    return ReplyRouteDecisionResult(
        action=ReplyRouteAction.CONTINUE,
        reason="continue_planned_path",
        adjusted_reengagement_not_before=resolve_reengagement_pull_in(
            current=current_reengagement_not_before,
            proposed=proposed_reengagement_not_before,
            now=now,
        ),
    )


def _interest_handoff_reason(evidence: ReplyRouteEvidence) -> HandoffReasonCode | None:
    if evidence.asks_property_or_advice:
        return HandoffReasonCode.SPECIFIC_PROPERTY_OR_ADVICE
    if evidence.shows_selling_interest or evidence.intent == _SELLER_INTEREST_INTENT:
        return HandoffReasonCode.SELLER_INTEREST
    if evidence.shows_buying_interest or evidence.intent == _HIGH_INTEREST_INTENT:
        return HandoffReasonCode.HIGH_INTEREST
    return None


def resolve_reengagement_pull_in(
    *,
    current: datetime | None,
    proposed: datetime | None,
    now: datetime,
) -> datetime | None:
    """Pull the re-engagement date in toward the lead's stated timing — never out.

    The date moves only when the lead stated an earlier concrete timing than the
    current plan. A lead asking to wait longer never pushes the date out; the
    reply stays in the conversation history so the next planned touch can
    acknowledge it.
    """
    if proposed is None or proposed.tzinfo is None or proposed <= now:
        return None
    if current is not None and current <= proposed:
        return None
    return proposed
