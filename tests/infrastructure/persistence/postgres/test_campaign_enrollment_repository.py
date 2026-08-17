from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.enrollment import (
    CampaignEnrollment,
    CampaignEnrollmentSource,
    CampaignEnrollmentStatus,
)
from app.infrastructure.persistence.postgres.campaign_enrollment_repository import (
    PostgresCampaignEnrollmentRepository,
)
from app.infrastructure.persistence.postgres.workflow_models import CampaignEnrollmentModel

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000002")
CAMPAIGN_VERSION_ID = UUID("00000000-0000-0000-0000-000000000003")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000004")
ENROLLMENT_ID = UUID("00000000-0000-0000-0000-000000000005")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000006")


class _FakeScalarSequence:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return list(self._values)


class _FakeResult:
    def __init__(self, scalar_value: object | None = None) -> None:
        self._scalar_value = scalar_value

    def scalar_one_or_none(self) -> object | None:
        return self._scalar_value

    def scalar_one(self) -> object:
        assert self._scalar_value is not None
        return self._scalar_value


class _FakeSession:
    def __init__(self, result: _FakeResult) -> None:
        self._result = result
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _FakeResult:
        self.statements.append(statement)
        return self._result


def _run(coro: object) -> object:
    import asyncio

    return asyncio.run(coro)  # type: ignore[arg-type]


async def test_get_by_lead_and_campaign_returns_only_active_enrollments() -> None:
    session = _FakeSession(_FakeResult(scalar_value=_model()))

    result = await PostgresCampaignEnrollmentRepository(
        cast(AsyncSession, session)
    ).get_by_lead_and_campaign(WORKSPACE_ID, LEAD_ID, CAMPAIGN_ID)

    assert result == _enrollment()
    statement = str(session.statements[0])
    assert "campaign_enrollments.workspace_id" in statement
    assert "campaign_enrollments.lead_id" in statement
    assert "campaign_enrollments.campaign_id" in statement
    assert "campaign_enrollments.status IN" in statement
    assert "ORDER BY campaign_enrollments.created_at DESC" in statement
    assert "LIMIT" in statement


def test_get_by_lead_and_campaign_filters_exactly_the_non_terminal_statuses() -> None:
    from sqlalchemy.dialects import postgresql

    session = _FakeSession(_FakeResult(scalar_value=None))

    _run(
        PostgresCampaignEnrollmentRepository(
            cast(AsyncSession, session)
        ).get_by_lead_and_campaign(WORKSPACE_ID, LEAD_ID, CAMPAIGN_ID)
    )

    statement = session.statements[0]
    compiled = str(
        statement.compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    )
    for status in ("candidate", "queued", "active", "paused", "handoff"):
        assert f"'{status}'" in compiled
    for status in ("completed", "suppressed", "closed"):
        assert f"'{status}'" not in compiled


async def test_get_latest_by_lead_and_campaign_includes_terminal_enrollments() -> None:
    session = _FakeSession(_FakeResult(scalar_value=_model()))

    result = await PostgresCampaignEnrollmentRepository(
        cast(AsyncSession, session)
    ).get_latest_by_lead_and_campaign(WORKSPACE_ID, LEAD_ID, CAMPAIGN_ID)

    assert result == _enrollment()
    statement = str(session.statements[0])
    assert "campaign_enrollments.status IN" not in statement
    assert "ORDER BY campaign_enrollments.created_at DESC" in statement
    assert "LIMIT" in statement


async def test_save_uses_unique_constraint_upsert() -> None:
    session = _FakeSession(_FakeResult(scalar_value=_model()))

    saved = await PostgresCampaignEnrollmentRepository(cast(AsyncSession, session)).save(
        _enrollment()
    )

    assert saved == _enrollment()
    statement = str(session.statements[0])
    assert "INSERT INTO campaign_enrollments" in statement
    assert "ON CONFLICT" in statement
    assert "workspace_id" in statement
    assert "campaign_id" in statement
    assert "lead_id" in statement


def _model() -> CampaignEnrollmentModel:
    return CampaignEnrollmentModel(
        campaign_enrollment_id=ENROLLMENT_ID,
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        lead_id=LEAD_ID,
        source=CampaignEnrollmentSource.MANUAL_ADMIN.value,
        status=CampaignEnrollmentStatus.QUEUED.value,
        eligible_at=NOW,
        enrolled_at=NOW,
        started_at=None,
        ended_at=None,
        created_by_user_id=ACTOR_ID,
        reason_codes=[CampaignEnrollmentSource.MANUAL_ADMIN.value],
        created_at=NOW,
        updated_at=NOW,
    )


def _enrollment() -> CampaignEnrollment:
    return CampaignEnrollment(
        campaign_enrollment_id=ENROLLMENT_ID,
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        lead_id=LEAD_ID,
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        status=CampaignEnrollmentStatus.QUEUED,
        eligible_at=NOW,
        enrolled_at=NOW,
        started_at=None,
        ended_at=None,
        created_by_user_id=ACTOR_ID,
        reason_codes=(CampaignEnrollmentSource.MANUAL_ADMIN.value,),
        created_at=NOW,
        updated_at=NOW,
    )
