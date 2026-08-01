from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from app.application.ports.crm_webhook import FollowUpBossWebhookEventBundle
from app.domain.conversations import CrmConversationEventDirection
from app.infrastructure.crm.follow_up_boss import webhook_event_mappers

NOW = datetime(2026, 7, 27, 18, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
LEAD_ID = UUID("33333333-3333-3333-3333-333333333333")


class _FakeCRMClient:
    async def fetch_resource_by_uri(
        self,
        workspace_id: UUID,
        uri: str,
    ) -> dict[str, object]:
        assert workspace_id == WORKSPACE_ID
        assert uri == "https://api.followupboss.com/v1/textMessages/42"
        return {
            "textMessages": [
                {
                    "id": 42,
                    "personId": 12456,
                    "isIncoming": True,
                    "message": "  I am still interested in the home.  ",
                    "created": "2026-07-27T17:30:00Z",
                }
            ]
        }


class _FakeConversationEventRepository:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def save(self, event: Any) -> Any:
        self.events.append(event)
        return event


@pytest.mark.asyncio
async def test_inbound_text_webhook_is_persisted_in_unified_timeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_process(*, event: Any, **kwargs: Any) -> SimpleNamespace:
        _ = (event, kwargs)
        return SimpleNamespace(lead_id=LEAD_ID)

    monkeypatch.setattr(
        webhook_event_mappers,
        "process_crm_human_activity_event",
        fake_process,
    )
    conversation_repository = _FakeConversationEventRepository()
    bundle = cast(
        FollowUpBossWebhookEventBundle,
        SimpleNamespace(
            crm_client=_FakeCRMClient(),
            crm_conversation_event_repository=conversation_repository,
            lead_repository=object(),
            external_event_repository=object(),
            lead_workflow_repository=object(),
            workflow_transition_repository=object(),
            paused_search_occurrence_repository=None,
            temporal_signal_outbox_repository=object(),
        ),
    )

    processed, ignored = await webhook_event_mappers.handle_text_messages_created(
        WORKSPACE_ID,
        "evt-text-1",
        NOW,
        "https://api.followupboss.com/v1/textMessages/42",
        bundle,
    )

    assert (processed, ignored) == (1, 0)
    assert len(conversation_repository.events) == 1
    event = conversation_repository.events[0]
    assert event.crm_activity_id == "text_message:42"
    assert event.direction == CrmConversationEventDirection.INBOUND
    assert event.content == "I am still interested in the home."
    assert event.occurred_at == datetime(2026, 7, 27, 17, 30, tzinfo=UTC)
