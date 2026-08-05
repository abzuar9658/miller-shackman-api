from datetime import UTC, datetime

from app.domain.conversations import (
    CrmConversationEventDirection,
    canonical_crm_event_identity,
)

NOW = datetime(2026, 8, 2, 12, 0, 0, 900000, tzinfo=UTC)


def test_identity_matches_extension_and_fub_text_shapes() -> None:
    extension = canonical_crm_event_identity(
        activity_type="text",
        occurred_at=NOW,
        content="Hello\u00a0there",
        direction="inbound",
    )
    pulled = canonical_crm_event_identity(
        activity_type="Text message",
        occurred_at=NOW.replace(microsecond=0),
        content="<span>Hello there</span>",
        direction=CrmConversationEventDirection.INBOUND,
    )

    assert extension == pulled


def test_identity_keeps_direction_and_timestamp_distinct() -> None:
    base = canonical_crm_event_identity(
        activity_type="text",
        occurred_at=NOW,
        content="Same content",
        direction="inbound",
    )

    assert base != canonical_crm_event_identity(
        activity_type="text",
        occurred_at=NOW,
        content="Same content",
        direction="outbound",
    )
    assert base != canonical_crm_event_identity(
        activity_type="text",
        occurred_at=NOW.replace(second=1),
        content="Same content",
        direction="inbound",
    )