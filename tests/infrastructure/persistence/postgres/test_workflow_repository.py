from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.workflows import (
    LeadWorkflow,
    WorkflowState,
    WorkflowTransition,
    WorkflowTransitionReasonCode,
)
from app.infrastructure.persistence.postgres.models import (
    LeadWorkflowModel,
    WorkflowTransitionModel,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000002")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000003")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000004")
ENROLLMENT_ID = UUID("00000000-0000-0000-0000-000000000005")
TRANSITION_ID = UUID("00000000-0000-0000-0000-000000000006")


class _FakeScalarSequence:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return list(self._values)


class _FakeResult:
    def __init__(
        self, scalar_value: object | None = None, scalar_values: list[object] | None = None
    ) -> None:
        self._scalar_value = scalar_value
        self._scalar_values = scalar_values or []

    def scalar_one_or_none(self) -> object | None:
        return self._scalar_value

    def scalar_one(self) -> object:
        assert self._scalar_value is not None
        return self._scalar_value

    def scalars(self) -> _FakeScalarSequence:
        return _FakeScalarSequence(self._scalar_values)


class _FakeSession:
    def __init__(self, result: _FakeResult) -> None:
        self._result = result
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _FakeResult:
        self.statements.append(statement)
        return self._result


def test_get_latest_for_lead_for_update_uses_lock_and_maps_domain() -> None:
    session = _FakeSession(_FakeResult(scalar_value=_workflow_model()))

    result = _run(
        PostgresLeadWorkflowRepository(cast(AsyncSession, session)).get_latest_for_lead_for_update(
            WORKSPACE_ID,
            LEAD_ID,
        ),
    )

    assert result == _workflow()
    statement = str(session.statements[0])
    assert "lead_workflows.workspace_id" in statement
    assert "lead_workflows.lead_id" in statement
    assert "FOR UPDATE" in statement


def test_save_workflow_uses_primary_key_upsert() -> None:
    session = _FakeSession(_FakeResult(scalar_value=_workflow_model()))

    saved = _run(PostgresLeadWorkflowRepository(cast(AsyncSession, session)).save(_workflow()))

    assert saved == _workflow()
    assert "ON CONFLICT (workflow_id) DO UPDATE" in str(session.statements[0])


def test_append_transition_returns_domain_record() -> None:
    session = _FakeSession(_FakeResult(scalar_value=_transition_model()))

    saved = _run(
        PostgresWorkflowTransitionRepository(cast(AsyncSession, session)).append(_transition())
    )

    assert saved == _transition()
    statement = str(session.statements[0])
    assert "INSERT INTO workflow_transitions" in statement
    assert "ON CONFLICT" not in statement


def _workflow_model() -> LeadWorkflowModel:
    return LeadWorkflowModel(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture-test",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state="waiting_for_response",
        current_step_id=None,
        next_action_at=None,
        last_transition_at=NOW,
        pause_reason=None,
        resume_reason=None,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _workflow() -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture-test",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=WorkflowState.WAITING_FOR_RESPONSE,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _transition_model() -> WorkflowTransitionModel:
    return WorkflowTransitionModel(
        transition_id=TRANSITION_ID,
        workspace_id=WORKSPACE_ID,
        workflow_id=WORKFLOW_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        from_state="waiting_for_response",
        to_state="human_handoff",
        reason_code="human_handoff_required",
        actor_user_id=None,
        external_event_id=None,
        created_at=NOW,
        metadata_={"intent": "human_requested"},
    )


def _transition() -> WorkflowTransition:
    return WorkflowTransition(
        transition_id=TRANSITION_ID,
        workspace_id=WORKSPACE_ID,
        workflow_id=WORKFLOW_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        from_state=WorkflowState.WAITING_FOR_RESPONSE,
        to_state=WorkflowState.HUMAN_HANDOFF,
        reason_code=WorkflowTransitionReasonCode.HUMAN_HANDOFF_REQUIRED,
        created_at=NOW,
        metadata={"intent": "human_requested"},
    )


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)
