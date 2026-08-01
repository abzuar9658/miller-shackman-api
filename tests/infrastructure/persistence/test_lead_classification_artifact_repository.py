from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.leads import (
    LeadClassificationAppliedStatus,
    LeadClassificationArtifact,
    LeadStateClassificationOutcome,
    PausedSearchReasonCode,
)
from app.infrastructure.persistence.postgres.lead_classification_artifact_repository import (
    PostgresLeadClassificationArtifactRepository,
)
from app.infrastructure.persistence.postgres.models import LeadClassificationArtifactModel

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
ARTIFACT_ID = UUID("00000000-0000-0000-0000-000000000003")


class _FakeResult:
    def __init__(self, *, scalar_value: object | None = None) -> None:
        self._scalar_value = scalar_value

    def scalar_one_or_none(self) -> object | None:
        return self._scalar_value


class _FakeSession:
    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = results
        self.statements: list[object] = []
        self.added: list[object] = []
        self.flushed = False

    async def execute(self, statement: object) -> _FakeResult:
        self.statements.append(statement)
        return self._results.pop(0)

    def add(self, model: object) -> None:
        self.added.append(model)

    async def flush(self) -> None:
        self.flushed = True


def test_get_by_id_maps_llm_trace_fields() -> None:
    session = _FakeSession([_FakeResult(scalar_value=_artifact_model())])

    result = _run(
        PostgresLeadClassificationArtifactRepository(cast(AsyncSession, session)).get_by_id(
            WORKSPACE_ID,
            ARTIFACT_ID,
        )
    )

    assert result == _artifact()
    assert "lead_classification_artifacts" in str(session.statements[0])


def test_save_maps_llm_trace_fields_to_model() -> None:
    session = _FakeSession([])

    result = _run(
        PostgresLeadClassificationArtifactRepository(cast(AsyncSession, session)).save(_artifact())
    )

    assert result == _artifact()
    assert session.flushed is True
    saved = cast(LeadClassificationArtifactModel, session.added[0])
    assert saved.prompt_text == "Prompt text for paused-search classification."
    assert saved.input_context["conversation_summary"] == "Lead asked to wait for lower rates."
    assert saved.raw_llm_response_text == '{"outcome":"paused_search"}'
    assert saved.parsed_llm_response["outcome"] == "paused_search"


def _artifact_model() -> LeadClassificationArtifactModel:
    return LeadClassificationArtifactModel(
        artifact_id=ARTIFACT_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        source="ai_conversation_classification",
        outcome="paused_search",
        pause_reason_code="waiting_for_rates",
        reengagement_not_before=NOW,
        reengagement_window_label="after summer",
        confidence=0.91,
        evidence=["Lead asked to wait for lower rates."],
        summary="Pause until rates settle.",
        model="openai/gpt-4o-mini",
        prompt_version="lead_state_classification:v1",
        latency_ms=420,
        usage_tokens=123,
        prompt_text="Prompt text for paused-search classification.",
        input_context={"conversation_summary": "Lead asked to wait for lower rates."},
        raw_llm_response_text='{"outcome":"paused_search"}',
        parsed_llm_response={"outcome": "paused_search", "confidence": 0.91},
        applied_status="applied",
        applied_at=NOW,
        created_at=NOW,
    )


def _artifact() -> LeadClassificationArtifact:
    return LeadClassificationArtifact(
        artifact_id=ARTIFACT_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        source="ai_conversation_classification",
        outcome=LeadStateClassificationOutcome.PAUSED_SEARCH,
        pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
        reengagement_not_before=NOW,
        reengagement_window_label="after summer",
        confidence=0.91,
        evidence=("Lead asked to wait for lower rates.",),
        summary="Pause until rates settle.",
        model="openai/gpt-4o-mini",
        prompt_version="lead_state_classification:v1",
        latency_ms=420,
        usage_tokens=123,
        applied_status=LeadClassificationAppliedStatus.APPLIED,
        applied_at=NOW,
        created_at=NOW,
        prompt_text="Prompt text for paused-search classification.",
        input_context={"conversation_summary": "Lead asked to wait for lower rates."},
        raw_llm_response_text='{"outcome":"paused_search"}',
        parsed_llm_response={"outcome": "paused_search", "confidence": 0.91},
    )


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)
