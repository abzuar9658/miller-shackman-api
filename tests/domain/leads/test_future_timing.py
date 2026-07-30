from datetime import UTC, datetime
from uuid import uuid4

from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.leads.future_timing import detect_future_timing_from_crm_events

NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)
WORKSPACE_ID = uuid4()
LEAD_ID = uuid4()


def _event(content: str) -> CrmConversationEvent:
    return CrmConversationEvent(
        crm_conversation_event_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider="follow_up_boss",
        crm_activity_id=str(uuid4()),
        activity_type="note",
        occurred_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        direction=CrmConversationEventDirection.INTERNAL,
        content=content,
    )


def test_detects_month_year_in_future() -> None:
    result = detect_future_timing_from_crm_events(
        crm_events=(_event("Looks needs a house but in January 2027."),),
        now=NOW,
    )

    assert result.detected is True
    assert result.reengagement_not_before == datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert result.reengagement_window_label == "January 2027"
    assert result.evidence is not None


def test_detects_year_month_in_future() -> None:
    result = detect_future_timing_from_crm_events(
        crm_events=(_event("Looks needs a house but in 2027 January."),),
        now=NOW,
    )

    assert result.detected is True
    assert result.reengagement_not_before == datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert result.reengagement_window_label == "January 2027"


def test_ignores_past_dates() -> None:
    result = detect_future_timing_from_crm_events(
        crm_events=(_event("Was ready in January 2025."),),
        now=NOW,
    )

    assert result.detected is False


def test_ignores_dates_without_month() -> None:
    result = detect_future_timing_from_crm_events(
        crm_events=(_event("Maybe next year."),),
        now=NOW,
    )

    assert result.detected is False


def test_ignores_empty_events() -> None:
    result = detect_future_timing_from_crm_events(
        crm_events=(),
        now=NOW,
    )

    assert result.detected is False
