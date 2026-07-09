from collections.abc import Coroutine
from datetime import UTC, datetime, time
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns import CampaignStatus, CampaignVersionStatus
from app.domain.campaigns.execution import CampaignCadenceStep, CampaignExecutionConfig
from app.domain.compliance.contactability import ContactChannel
from app.infrastructure.persistence.postgres.campaign_execution_repository import (
    PostgresCampaignExecutionRepository,
)
from app.infrastructure.persistence.postgres.models import (
    CampaignCadenceStepModel,
    CampaignModel,
    CampaignVersionModel,
)

NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000002")
VERSION_ID = UUID("00000000-0000-0000-0000-000000000003")
STEP_ID = UUID("00000000-0000-0000-0000-000000000004")
CREATOR_ID = UUID("00000000-0000-0000-0000-000000000005")


class _FakeScalarSequence:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return list(self._values)


class _FakeResult:
    def __init__(
        self,
        *,
        one_value: object | None = None,
        scalar_values: list[object] | None = None,
    ) -> None:
        self._one_value = one_value
        self._scalar_values = scalar_values or []

    def one_or_none(self) -> object | None:
        return self._one_value

    def scalars(self) -> _FakeScalarSequence:
        return _FakeScalarSequence(self._scalar_values)


class _FakeSession:
    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = results
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _FakeResult:
        self.statements.append(statement)
        return self._results.pop(0)


def test_get_by_version_id_maps_campaign_execution_config() -> None:
    session = _FakeSession(
        [
            _FakeResult(one_value=(_version_model(), _campaign_model())),
            _FakeResult(scalar_values=[_step_model()]),
        ]
    )

    result = _run(
        PostgresCampaignExecutionRepository(cast(AsyncSession, session)).get_by_version_id(
            WORKSPACE_ID,
            VERSION_ID,
        )
    )

    assert result == _config()
    assert "campaign_versions" in str(session.statements[0])
    assert "campaigns" in str(session.statements[0])
    assert "campaign_cadence_steps" in str(session.statements[1])


def _campaign_model() -> CampaignModel:
    return CampaignModel(
        campaign_id=CAMPAIGN_ID,
        workspace_id=WORKSPACE_ID,
        name="Dormant Buyers",
        status="active",
        active_version_id=VERSION_ID,
        created_by_user_id=CREATOR_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _version_model() -> CampaignVersionModel:
    return CampaignVersionModel(
        campaign_version_id=VERSION_ID,
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        version_number=1,
        status="published",
        enabled_channels=[ContactChannel.EMAIL.value],
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="America/Chicago",
        sms_compliance_required=True,
        preflight_digest_enabled=False,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        created_by_user_id=CREATOR_ID,
        published_at=NOW,
        created_at=NOW,
    )


def _step_model() -> CampaignCadenceStepModel:
    return CampaignCadenceStepModel(
        cadence_step_id=STEP_ID,
        workspace_id=WORKSPACE_ID,
        campaign_version_id=VERSION_ID,
        step_order=1,
        channel=ContactChannel.EMAIL.value,
        delay_hours=24,
        message_goal="Check whether the lead is still considering a move.",
        template_key="dormant-email-1",
        max_attempts=1,
        created_at=NOW,
    )


def _step() -> CampaignCadenceStep:
    return CampaignCadenceStep(
        cadence_step_id=STEP_ID,
        workspace_id=WORKSPACE_ID,
        campaign_version_id=VERSION_ID,
        step_order=1,
        channel=ContactChannel.EMAIL,
        delay_hours=24,
        message_goal="Check whether the lead is still considering a move.",
        template_key="dormant-email-1",
        max_attempts=1,
        created_at=NOW,
    )


def _config() -> CampaignExecutionConfig:
    return CampaignExecutionConfig(
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=VERSION_ID,
        workspace_id=WORKSPACE_ID,
        campaign_name="Dormant Buyers",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(ContactChannel.EMAIL,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="America/Chicago",
        sms_compliance_required=True,
        preflight_digest_enabled=False,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(_step(),),
        created_at=NOW,
        published_at=NOW,
    )


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)
