from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.leads import (
    AssignmentResolutionStatus,
    CanonicalLeadRecord,
    CRMProvider,
    LeadClassificationReason,
    LeadPausedSearchHistoryEntry,
    LeadPausedSearchProfile,
    LeadType,
    PausedSearchAction,
    PausedSearchReasonCode,
    PausedSearchSource,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import (
    LeadModel,
    LeadPausedSearchHistoryModel,
    UserModel,
    WorkspaceModel,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111101")
OTHER_WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111102")
USER_ID = UUID("11111111-1111-1111-1111-111111111103")
LEAD_ID = UUID("11111111-1111-1111-1111-111111111104")
OTHER_LEAD_ID = UUID("11111111-1111-1111-1111-111111111105")


def test_upsert_includes_paused_search_fields() -> None:
    session = _FakeSession(_FakeResult(scalar_value=_lead_model()))

    saved = _run(PostgresLeadRepository(cast(AsyncSession, session)).upsert(_lead()))

    assert saved.pause_reason_code == PausedSearchReasonCode.WAITING_FOR_RATES
    statement = str(session.statements[0])
    assert "paused_search_active" in statement
    assert "pause_reason_code" in statement


def test_append_history_returns_saved_entry() -> None:
    session = _FakeSession(_FakeResult(scalar_value=_history_model()))

    saved = _run(PostgresLeadRepository(cast(AsyncSession, session)).append(_history_entry()))

    assert saved == _history_entry()
    assert "INSERT INTO lead_paused_search_history" in str(session.statements[0])


@pytest.mark.asyncio
async def test_list_history_filters_by_workspace_and_lead(postgres_session: AsyncSession) -> None:
    await _seed_workspace_and_user(postgres_session)
    repository = PostgresLeadRepository(postgres_session)
    await repository.upsert(_lead())
    await repository.upsert(_other_lead())
    await repository.append(_history_entry())
    await repository.append(_other_history_entry())
    await postgres_session.commit()

    items = await repository.list_for_lead(WORKSPACE_ID, LEAD_ID)

    assert len(items) == 1
    assert items[0].lead_id == LEAD_ID
    assert items[0].workspace_id == WORKSPACE_ID


async def _seed_workspace_and_user(postgres_session: AsyncSession) -> None:
    postgres_session.add_all(
        [
            WorkspaceModel(
                workspace_id=WORKSPACE_ID,
                name="Test Workspace",
                status="active",
                default_timezone="UTC",
                created_at=NOW,
                updated_at=NOW,
            ),
            WorkspaceModel(
                workspace_id=OTHER_WORKSPACE_ID,
                name="Other Workspace",
                status="active",
                default_timezone="UTC",
                created_at=NOW,
                updated_at=NOW,
            ),
            UserModel(
                user_id=USER_ID,
                email="agent@example.com",
                email_normalized="agent@example.com",
                full_name="Jordan Agent",
                status="active",
                created_at=NOW,
                updated_at=NOW,
            ),
        ]
    )
    await postgres_session.flush()


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        assignment_resolution_status=AssignmentResolutionStatus.UNRESOLVED,
        lead_type=LeadType.UNKNOWN,
        classification_reason=LeadClassificationReason.CRM_TYPE_MISSING,
        mapped_custom_fields={"display_name": "Jordan Buyer"},
        paused_search_active=True,
        pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
        pause_reason_note="Waiting until rates improve.",
        reengagement_not_before=NOW,
        reengagement_window_label="spring check-in",
        paused_search_source=PausedSearchSource.OPERATOR,
        paused_search_recorded_at=NOW,
        paused_search_recorded_by_user_id=USER_ID,
        paused_search_last_confirmed_at=NOW,
    )


def _other_lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=OTHER_WORKSPACE_ID,
        lead_id=OTHER_LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-2",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        mapped_custom_fields={"display_name": "Casey Seller"},
    )


def _history_entry() -> LeadPausedSearchHistoryEntry:
    return LeadPausedSearchHistoryEntry(
        history_id=UUID("11111111-1111-1111-1111-111111111106"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        action=PausedSearchAction.SET,
        previous_profile=None,
        current_profile=LeadPausedSearchProfile(
            paused_search_active=True,
            pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
            pause_reason_note="Waiting until rates improve.",
            reengagement_not_before=NOW,
            reengagement_window_label="spring check-in",
            paused_search_source=PausedSearchSource.OPERATOR,
            paused_search_recorded_at=NOW,
            paused_search_recorded_by_user_id=USER_ID,
            paused_search_last_confirmed_at=NOW,
        ),
        actor_user_id=USER_ID,
        created_at=NOW,
    )


def _other_history_entry() -> LeadPausedSearchHistoryEntry:
    return LeadPausedSearchHistoryEntry(
        history_id=UUID("11111111-1111-1111-1111-111111111107"),
        workspace_id=OTHER_WORKSPACE_ID,
        lead_id=OTHER_LEAD_ID,
        action=PausedSearchAction.SET,
        previous_profile=None,
        current_profile=None,
        actor_user_id=USER_ID,
        created_at=NOW,
    )


def _lead_model() -> LeadModel:
    return LeadModel(
        lead_id=LEAD_ID,
        workspace_id=WORKSPACE_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        crm_lead_id="crm-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        assignment_resolution_status=AssignmentResolutionStatus.UNRESOLVED.value,
        lead_type=LeadType.UNKNOWN.value,
        classification_reason=LeadClassificationReason.CRM_TYPE_MISSING.value,
        tags=[],
        mapped_custom_fields={"display_name": "Jordan Buyer"},
        has_email=False,
        has_phone=False,
        has_sms_capable_phone=False,
        email_count=0,
        phone_count=0,
        sms_permission_status="unknown",
        email_permission_status="unknown",
        sms_opted_out=False,
        email_unsubscribed=False,
        do_not_contact=False,
        suppression_types=[],
        permission_evidence={},
        contacted_count=0,
        activity_reliability="unknown",
        assigned_agent_name_present=False,
        has_accountable_owner=False,
        latest_property_context_present=False,
        paused_search_active=True,
        pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES.value,
        pause_reason_note="Waiting until rates improve.",
        reengagement_not_before=NOW,
        reengagement_window_label="spring check-in",
        paused_search_source=PausedSearchSource.OPERATOR.value,
        paused_search_recorded_at=NOW,
        paused_search_recorded_by_user_id=USER_ID,
        paused_search_last_confirmed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _history_model() -> LeadPausedSearchHistoryModel:
    return LeadPausedSearchHistoryModel(
        history_id=UUID("11111111-1111-1111-1111-111111111106"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        action=PausedSearchAction.SET.value,
        previous_active=False,
        current_active=True,
        current_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES.value,
        current_reason_note="Waiting until rates improve.",
        current_reengagement_not_before=NOW,
        current_reengagement_window_label="spring check-in",
        current_source=PausedSearchSource.OPERATOR.value,
        current_recorded_at=NOW,
        current_recorded_by_user_id=USER_ID,
        current_last_confirmed_at=NOW,
        actor_user_id=USER_ID,
        created_at=NOW,
    )


class _FakeResult:
    def __init__(self, *, scalar_value: Any) -> None:
        self._scalar_value = scalar_value

    def scalar_one(self) -> Any:
        return self._scalar_value


class _FakeSession:
    def __init__(self, result: _FakeResult) -> None:
        self._result = result
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _FakeResult:
        self.statements.append(statement)
        return self._result


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)