from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.campaigns.paused_search_tracks import PausedSearchReplyPolicy


class PausedSearchReplyDecision(StrEnum):
    CONTINUE = "continue"
    RESTART = "restart"
    REANCHOR = "reanchor"
    REVIEW = "review"
    END = "end"
    HANDOFF = "handoff"


@dataclass(frozen=True)
class PausedSearchReplyContext:
    same_paused_search_track: bool
    explicit_new_timing: bool = False
    hard_stop: bool = False


def has_valid_explicit_new_timing(*, timing: datetime | None, now: datetime) -> bool:
    """Accept only a timezone-aware timing boundary strictly in the future."""
    return timing is not None and timing.tzinfo is not None and timing > now


def decide_paused_search_reply(
    policy: PausedSearchReplyPolicy,
    context: PausedSearchReplyContext,
) -> PausedSearchReplyDecision:
    """Resolve reply continuation without allowing AI output to bypass safety rules."""

    if context.hard_stop:
        return PausedSearchReplyDecision.HANDOFF
    if not context.same_paused_search_track:
        return PausedSearchReplyDecision.END
    if policy is PausedSearchReplyPolicy.CONTINUE:
        return PausedSearchReplyDecision.CONTINUE
    if policy is PausedSearchReplyPolicy.RESTART_AFTER_DELAY:
        return PausedSearchReplyDecision.RESTART
    if policy is PausedSearchReplyPolicy.REANCHOR_TO_NEW_TIMING:
        return (
            PausedSearchReplyDecision.REANCHOR
            if context.explicit_new_timing
            else PausedSearchReplyDecision.REVIEW
        )
    if policy is PausedSearchReplyPolicy.REVIEW_OR_REMIND:
        return PausedSearchReplyDecision.REVIEW
    return PausedSearchReplyDecision.END