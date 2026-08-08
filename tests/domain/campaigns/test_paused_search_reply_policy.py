from datetime import UTC, datetime, timedelta

import pytest

from app.domain.campaigns import (
    PausedSearchReplyContext,
    PausedSearchReplyDecision,
    PausedSearchReplyPolicy,
    decide_paused_search_reply,
    has_valid_explicit_new_timing,
)


@pytest.mark.parametrize(
    ("policy", "expected"),
    (
        (PausedSearchReplyPolicy.CONTINUE, PausedSearchReplyDecision.CONTINUE),
        (PausedSearchReplyPolicy.RESTART_AFTER_DELAY, PausedSearchReplyDecision.RESTART),
        (PausedSearchReplyPolicy.REANCHOR_TO_NEW_TIMING, PausedSearchReplyDecision.REANCHOR),
        (PausedSearchReplyPolicy.REVIEW_OR_REMIND, PausedSearchReplyDecision.REVIEW),
        (PausedSearchReplyPolicy.END, PausedSearchReplyDecision.END),
    ),
)
def test_same_track_reply_uses_published_policy(
    policy: PausedSearchReplyPolicy,
    expected: PausedSearchReplyDecision,
) -> None:
    assert (
        decide_paused_search_reply(
            policy,
            PausedSearchReplyContext(
                same_paused_search_track=True,
                explicit_new_timing=True,
            ),
        )
        is expected
    )


def test_reanchor_requires_explicit_new_timing() -> None:
    assert (
        decide_paused_search_reply(
            PausedSearchReplyPolicy.REANCHOR_TO_NEW_TIMING,
            PausedSearchReplyContext(same_paused_search_track=True),
        )
        is PausedSearchReplyDecision.REVIEW
    )


def test_changed_track_ends_current_track() -> None:
    assert (
        decide_paused_search_reply(
            PausedSearchReplyPolicy.CONTINUE,
            PausedSearchReplyContext(same_paused_search_track=False),
        )
        is PausedSearchReplyDecision.END
    )


def test_hard_stop_always_wins_over_same_track_continuation() -> None:
    assert (
        decide_paused_search_reply(
            PausedSearchReplyPolicy.RESTART_AFTER_DELAY,
            PausedSearchReplyContext(same_paused_search_track=True, hard_stop=True),
        )
        is PausedSearchReplyDecision.HANDOFF
    )


@pytest.mark.parametrize(
    "timing",
    (
        None,
        datetime(2026, 7, 8, 12, 0, tzinfo=UTC),
        datetime(2026, 7, 7, 12, 0, tzinfo=UTC),
    ),
)
def test_explicit_new_timing_must_be_strictly_in_the_future(
    timing: datetime | None,
) -> None:
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    assert not has_valid_explicit_new_timing(timing=timing, now=now)


def test_explicit_new_timing_accepts_a_future_timezone_aware_boundary() -> None:
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    assert has_valid_explicit_new_timing(
        timing=now + timedelta(days=1),
        now=now,
    )