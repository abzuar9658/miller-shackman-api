from datetime import UTC, datetime

from app.domain.conversations import HandoffReasonCode
from app.domain.conversations.reply_routing import (
    ReplyRouteAction,
    ReplyRouteDecisionResult,
    ReplyRouteEvidence,
    ReplyRouteOption,
    decide_reply_route,
    resolve_reengagement_pull_in,
)

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _decide(
    *,
    decision: ReplyRouteOption | None,
    rejected: bool = False,
    evidence: ReplyRouteEvidence | None = None,
    proposed: datetime | None = None,
    current: datetime | None = None,
) -> ReplyRouteDecisionResult:
    return decide_reply_route(
        router_decision=decision,
        router_rejected=rejected,
        evidence=evidence or ReplyRouteEvidence(intent="general_reply"),
        proposed_reengagement_not_before=proposed,
        current_reengagement_not_before=current,
        now=NOW,
    )


def test_explicit_human_request_always_hands_off() -> None:
    result = decide_reply_route(
        router_decision=ReplyRouteOption.CONTINUE,
        router_rejected=False,
        evidence=ReplyRouteEvidence(asks_for_human=True, intent="general_reply"),
        now=NOW,
    )

    assert result.action is ReplyRouteAction.HUMAN_HANDOFF
    assert result.handoff_reason is HandoffReasonCode.HUMAN_REQUESTED


def test_router_rejection_goes_to_review() -> None:
    result = _decide(decision=None, rejected=True)

    assert result.action is ReplyRouteAction.REVIEW


def test_router_suppressed_suppresses() -> None:
    result = _decide(decision=ReplyRouteOption.SUPPRESSED)

    assert result.action is ReplyRouteAction.SUPPRESS


def test_router_handoff_with_buying_interest_hands_off() -> None:
    result = _decide(
        decision=ReplyRouteOption.HUMAN_HANDOFF,
        evidence=ReplyRouteEvidence(shows_buying_interest=True, intent="general_reply"),
    )

    assert result.action is ReplyRouteAction.HUMAN_HANDOFF
    assert result.handoff_reason is HandoffReasonCode.HIGH_INTEREST


def test_router_handoff_with_advice_evidence_uses_advice_reason() -> None:
    result = _decide(
        decision=ReplyRouteOption.HUMAN_HANDOFF,
        evidence=ReplyRouteEvidence(
            shows_buying_interest=True,
            asks_property_or_advice=True,
            intent="general_reply",
        ),
    )

    assert result.action is ReplyRouteAction.HUMAN_HANDOFF
    assert result.handoff_reason is HandoffReasonCode.SPECIFIC_PROPERTY_OR_ADVICE


def test_router_handoff_with_selling_interest_uses_seller_reason() -> None:
    result = _decide(
        decision=ReplyRouteOption.HUMAN_HANDOFF,
        evidence=ReplyRouteEvidence(shows_selling_interest=True, intent="general_reply"),
    )

    assert result.action is ReplyRouteAction.HUMAN_HANDOFF
    assert result.handoff_reason is HandoffReasonCode.SELLER_INTEREST


def test_router_handoff_without_any_evidence_continues() -> None:
    """The confused-drift guard: a handoff pick with no interest or advice
    evidence is treated as a misread and the journey continues."""
    result = _decide(
        decision=ReplyRouteOption.HUMAN_HANDOFF,
        evidence=ReplyRouteEvidence(intent="general_reply"),
    )

    assert result.action is ReplyRouteAction.CONTINUE
    assert result.handoff_reason is None
    assert result.reason == "handoff_without_interest_evidence"


def test_continue_without_timing_proposal_adjusts_nothing() -> None:
    result = _decide(decision=ReplyRouteOption.CONTINUE)

    assert result.action is ReplyRouteAction.CONTINUE
    assert result.adjusted_reengagement_not_before is None


def test_pull_in_applies_when_current_plan_is_later_than_reply() -> None:
    proposed = datetime(2026, 11, 1, 17, 0, tzinfo=UTC)
    current = datetime(2026, 12, 15, 17, 0, tzinfo=UTC)

    assert (
        resolve_reengagement_pull_in(current=current, proposed=proposed, now=NOW) == proposed
    )


def test_pull_in_never_pushes_out_when_reply_is_later() -> None:
    proposed = datetime(2026, 12, 1, 17, 0, tzinfo=UTC)
    current = datetime(2026, 11, 1, 17, 0, tzinfo=UTC)

    assert resolve_reengagement_pull_in(current=current, proposed=proposed, now=NOW) is None


def test_pull_in_sets_date_when_none_exists() -> None:
    proposed = datetime(2026, 11, 1, 17, 0, tzinfo=UTC)

    assert resolve_reengagement_pull_in(current=None, proposed=proposed, now=NOW) == proposed


def test_pull_in_rejects_past_or_naive_proposals() -> None:
    past = datetime(2026, 1, 1, 17, 0, tzinfo=UTC)
    naive = datetime(2026, 11, 1, 17, 0)

    assert resolve_reengagement_pull_in(current=None, proposed=past, now=NOW) is None
    assert resolve_reengagement_pull_in(current=None, proposed=naive, now=NOW) is None
    assert resolve_reengagement_pull_in(current=None, proposed=None, now=NOW) is None


def test_pull_in_equal_dates_keeps_current() -> None:
    same = datetime(2026, 11, 1, 17, 0, tzinfo=UTC)

    assert resolve_reengagement_pull_in(current=same, proposed=same, now=NOW) is None
