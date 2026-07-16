from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any, TypeVar, cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresCrmConversationEventRepository,
)
from app.infrastructure.persistence.postgres.models import CrmConversationEventModel

T = TypeVar("T")

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
WORKSPACE_ID = uuid4()
LEAD_ID = uuid4()
EVENT_ID = uuid4()


class _FakeScalarSequence:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return list(self._values)


class _FakeResult:
    def __init__(
        self,
        *,
        scalar_value: object | None = None,
        scalar_values: list[object] | None = None,
    ) -> None:
        self._scalar_value = scalar_value
        self._scalar_values = scalar_values or []

    def scalar_one(self) -> object:
        assert self._scalar_value is not None
        return self._scalar_value

    def scalars(self) -> _FakeScalarSequence:
        return _FakeScalarSequence(self._scalar_values)


class _FakeSession:
    def __init__(self, result: _FakeResult) -> None:
        self._result = result
        self.statements: list[Any] = []

    async def execute(self, statement: object) -> _FakeResult:
        self.statements.append(statement)
        return self._result


def _event(crm_activity_id: str = "act-1") -> CrmConversationEvent:
    return CrmConversationEvent(
        crm_conversation_event_id=EVENT_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider="follow_up_boss",
        crm_activity_id=crm_activity_id,
        activity_type="Note",
        direction=CrmConversationEventDirection.INTERNAL,
        occurred_at=NOW,
        content="Test content",
        actor_agent_id="user-1",
        actor_name="Agent One",
        source_payload_version="follow_up_boss/v1",
        created_at=NOW,
        updated_at=NOW,
    )


def _model(crm_activity_id: str = "act-1") -> CrmConversationEventModel:
    return CrmConversationEventModel(
        crm_conversation_event_id=EVENT_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider="follow_up_boss",
        crm_activity_id=crm_activity_id,
        activity_type="Note",
        direction="internal",
        occurred_at=NOW,
        content="Test content",
        actor_agent_id="user-1",
        actor_name="Agent One",
        source_payload_version="follow_up_boss/v1",
        created_at=NOW,
        updated_at=NOW,
    )


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)


async def test_save_uses_idempotent_upsert_on_workspace_provider_activity() -> None:
    session = _FakeSession(_FakeResult(scalar_value=_model()))

    saved = await PostgresCrmConversationEventRepository(cast(AsyncSession, session)).save(_event())

    assert saved == _event()
    statement = str(session.statements[0])
    assert "INSERT INTO crm_conversation_events" in statement
    assert "ON CONFLICT (workspace_id, crm_provider, crm_activity_id) DO UPDATE" in statement


async def test_list_for_lead_queries_by_workspace_lead_and_orders_by_occurred_at() -> None:
    session = _FakeSession(_FakeResult(scalar_values=[_model()]))

    repository = PostgresCrmConversationEventRepository(cast(AsyncSession, session))
    events = await repository.list_for_lead(
        WORKSPACE_ID,
        LEAD_ID,
        limit=25,
    )

    assert len(events) == 1
    assert events[0] == _event()
    statement = str(session.statements[0])
    assert "crm_conversation_events.workspace_id" in statement
    assert "crm_conversation_events.lead_id" in statement
    assert "ORDER BY" in statement
    assert "LIMIT" in statement


async def test_save_maps_direction_enum_to_string() -> None:
    session = _FakeSession(_FakeResult(scalar_value=_model()))

    await PostgresCrmConversationEventRepository(cast(AsyncSession, session)).save(_event())

    compiled = session.statements[0].compile()
    assert compiled.params["direction"] == "internal"
