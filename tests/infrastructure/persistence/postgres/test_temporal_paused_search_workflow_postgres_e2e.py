from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.application.ports.messaging import EmailMessage
from app.core.config import Settings
from app.domain.campaigns import PausedSearchFallbackTimingPolicy
from app.domain.common.ids import WorkspaceId
from app.domain.leads import CanonicalLeadRecord
from app.domain.outbound_drafting import DormantStepTemplateProfile
from app.domain.workspace_automation import WorkspaceOperationalControl
from app.infrastructure.messaging.sink import SinkEmailProvider
from app.infrastructure.persistence.postgres.workspace_operational_control_repository import (
    PostgresWorkspaceOperationalControlRepository,
)
from app.infrastructure.workflows.temporal import activities as temporal_activities
from app.infrastructure.workflows.temporal.lead_nurture import (
    LeadNurtureExecutionMode,
    LeadNurtureWorkflow,
    LeadNurtureWorkflowInput,
)
from tests.application.use_cases._campaign_cadence_fakes import FakeLLMClient, FakeSMSProvider
from tests.application.use_cases.test_plan_next_outbound_message import FakeListingSearchClient
from tests.infrastructure.persistence.postgres.test_business_flow_harness import (
    FakeCRMClient,
)
from tests.infrastructure.persistence.postgres.test_paused_search_timing_postgres_e2e import (
    CAMPAIGN_VERSION_ID,
    LEAD_ID,
    MAINTENANCE_STEP_ID,
    NOW,
    REACTIVATION_STEP_ID,
    TRACK_VERSION_ID,
    WORKFLOW_ID,
    WORKSPACE_ID,
    _seed,
)


class DeterministicCRMClient(FakeCRMClient):
    def __init__(self, lead: CanonicalLeadRecord) -> None:
        super().__init__()
        self._lead = lead

    async def get_lead_snapshot(
        self,
        *,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
        mapped_custom_field_keys: tuple[str, ...] = (),
    ) -> CanonicalLeadRecord | None:
        del mapped_custom_field_keys
        if workspace_id != WORKSPACE_ID or crm_lead_id != "timing-lead":
            return None
        return self._lead


class DeterministicSinkEmailProvider(SinkEmailProvider):
    async def send(self, message: EmailMessage) -> str:
        self.messages.append(message)
        return f"test-email-{len(self.messages)}"


async def test_temporal_paused_search_recurring_uses_postgres_and_reactivates(
    postgres_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await _seed(postgres_session, reengagement_not_before=NOW + timedelta(days=120))
    lead = replace(
        scenario.lead,
        primary_email="paused-search@example.com",
        has_email=True,
        email_count=1,
    )
    await scenario.lead_repository.upsert(lead)
    steps = await scenario.track_repository.get_steps(WORKSPACE_ID, TRACK_VERSION_ID)
    await scenario.track_repository.replace_steps(
        WORKSPACE_ID,
        TRACK_VERSION_ID,
        tuple(replace(step, template_profile=DormantStepTemplateProfile()) for step in steps),
    )
    await PostgresWorkspaceOperationalControlRepository(postgres_session).save(
        WorkspaceOperationalControl(
            workspace_id=WORKSPACE_ID,
            recurring_paused_search_enabled=True,
        )
    )
    email_provider = _install_activity_dependencies(monkeypatch, postgres_session, lead)

    env = await WorkflowEnvironment.start_time_skipping()
    async with env:
        await _advance_environment_to_seed_time(env)
        task_queue = f"paused-search-postgres-{uuid4()}"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[LeadNurtureWorkflow],
            activities=[
                temporal_activities.schedule_next_paused_search_occurrence_activity,
                temporal_activities.execute_paused_search_occurrence_activity,
            ],
        ):
            handle = await env.client.start_workflow(
                LeadNurtureWorkflow.run,
                LeadNurtureWorkflowInput(
                    workspace_id=WORKSPACE_ID,
                    lead_id=LEAD_ID,
                    campaign_version_id=CAMPAIGN_VERSION_ID,
                    workflow_id=WORKFLOW_ID,
                    execution_mode=LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING,
                    paused_search_track_version_id=TRACK_VERSION_ID,
                ),
                id=f"paused-search-postgres-{uuid4()}",
                task_queue=task_queue,
            )

            await env.sleep(timedelta(seconds=1))
            assert len(email_provider.messages) == 1
            first_occurrences = await scenario.occurrence_repository.list_for_workspace(
                WORKSPACE_ID, lead_id=LEAD_ID
            )
            assert len(first_occurrences) == 2
            first_sent = [
                occurrence
                for occurrence in first_occurrences
                if occurrence.status.value == "sent"
            ]
            assert len(first_sent) == 1
            assert first_sent[0].phase.value == "maintenance"

            await env.sleep(timedelta(days=30, seconds=1))
            assert len(email_provider.messages) == 2
            second_snapshot = await handle.query("snapshot")
            assert second_snapshot is not None
            assert second_snapshot["current_step_id"] == str(MAINTENANCE_STEP_ID)
            assert second_snapshot["last_activity_status"] == "scheduled"
            assert second_snapshot["occurrence_id"] is not None

            await env.sleep(timedelta(days=30, seconds=1))
            boundary_snapshot = await handle.query("snapshot")
            assert boundary_snapshot is not None
            assert len(email_provider.messages) == 3
            assert (
                boundary_snapshot["execution_mode"]
                == "paused_search_recurring"
            )
            assert boundary_snapshot["current_step_id"] == str(REACTIVATION_STEP_ID)
            assert boundary_snapshot["last_activity_status"] == "scheduled"
            assert boundary_snapshot["occurrence_id"] is None
            assert all(
                occurrence.phase.value == "maintenance"
                and occurrence.status.value == "sent"
                for occurrence in await scenario.occurrence_repository.list_for_workspace(
                    WORKSPACE_ID, lead_id=LEAD_ID
                )
            )

            await env.sleep(timedelta(days=30, seconds=1))
            snapshot = await handle.query("snapshot")
            assert snapshot is not None
            await handle.signal("close")
            result = await handle.result()

    occurrences = await scenario.occurrence_repository.list_for_workspace(
        WORKSPACE_ID, lead_id=LEAD_ID
    )
    maintenance_boundary = NOW + timedelta(days=90)
    maintenance = [
        occurrence
        for occurrence in occurrences
        if occurrence.step_id == MAINTENANCE_STEP_ID
    ]
    maintenance.sort(key=lambda occurrence: occurrence.due_at)
    reactivation = [
        occurrence
        for occurrence in occurrences
        if occurrence.step_id == REACTIVATION_STEP_ID
    ]
    assert len(maintenance) == 3
    assert all(occurrence.status.value == "sent" for occurrence in maintenance)
    assert all(occurrence.due_at < maintenance_boundary for occurrence in maintenance)
    assert [
        maintenance[index].due_at - maintenance[index - 1].due_at for index in (1, 2)
    ] == [timedelta(days=30), timedelta(days=30)]
    assert len(reactivation) == 1
    assert reactivation[0].status.value == "sent"
    assert reactivation[0].due_at >= maintenance_boundary
    assert len(email_provider.messages) == 4
    assert snapshot["execution_mode"] == "paused_search_recurring"
    assert snapshot["last_activity_status"] == "sent"
    assert snapshot["provider_message_id"] == "test-email-4"
    assert snapshot["current_step_id"] == str(REACTIVATION_STEP_ID)
    assert snapshot["occurrence_id"] == str(reactivation[0].occurrence_id)
    assert result.execution_mode is LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING
    assert result.last_activity_status == "sent"
    assert result.provider_message_id == "test-email-4"
    assert result.current_step_id == REACTIVATION_STEP_ID

    persisted_workflow = await scenario.workflow_repository.get_latest_for_lead(
        WORKSPACE_ID, LEAD_ID
    )
    assert persisted_workflow is not None
    assert persisted_workflow.state.value == "waiting_for_response"
    assert persisted_workflow.paused_search_track_step_id is None
    assert persisted_workflow.next_action_at is None


async def test_temporal_paused_search_missing_date_holds_without_sending(
    postgres_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await _seed(
        postgres_session,
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.HOLD_FOR_REVIEW,
        reengagement_not_before=None,
    )
    await PostgresWorkspaceOperationalControlRepository(postgres_session).save(
        WorkspaceOperationalControl(
            workspace_id=WORKSPACE_ID,
            recurring_paused_search_enabled=True,
        )
    )
    email_provider = _install_activity_dependencies(monkeypatch, postgres_session, scenario.lead)

    env = await WorkflowEnvironment.start_time_skipping()
    async with env:
        await _advance_environment_to_seed_time(env)
        task_queue = f"paused-search-hold-{uuid4()}"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[LeadNurtureWorkflow],
            activities=[temporal_activities.schedule_next_paused_search_occurrence_activity],
        ):
            handle = await env.client.start_workflow(
                LeadNurtureWorkflow.run,
                LeadNurtureWorkflowInput(
                    workspace_id=WORKSPACE_ID,
                    lead_id=LEAD_ID,
                    campaign_version_id=CAMPAIGN_VERSION_ID,
                    workflow_id=WORKFLOW_ID,
                    execution_mode=LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING,
                    paused_search_track_version_id=TRACK_VERSION_ID,
                ),
                id=f"paused-search-hold-{uuid4()}",
                task_queue=task_queue,
            )
            await env.sleep(timedelta(seconds=1))
            snapshot = await handle.query("snapshot")
            assert snapshot is not None
            await handle.signal("close")
            result = await handle.result()

    assert email_provider.messages == []
    assert snapshot["execution_mode"] == "paused_search_recurring"
    assert snapshot["last_activity_status"] == "hold"
    assert snapshot["skip_reason"] is not None
    assert result.execution_mode is LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING
    assert result.last_activity_status == "hold"
    assert await scenario.occurrence_repository.list_for_workspace(
        WORKSPACE_ID, lead_id=LEAD_ID
    ) == ()
    persisted_workflow = await scenario.workflow_repository.get_latest_for_lead(
        WORKSPACE_ID, LEAD_ID
    )
    assert persisted_workflow is not None
    assert persisted_workflow.next_action_at is None
    assert persisted_workflow.paused_search_track_step_id is None


async def _advance_environment_to_seed_time(env: WorkflowEnvironment) -> None:
    delay = NOW - datetime.now(UTC)
    if delay > timedelta():
        await env.sleep(delay)


def _install_activity_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    postgres_session: AsyncSession,
    lead: CanonicalLeadRecord,
) -> DeterministicSinkEmailProvider:
    email_provider = DeterministicSinkEmailProvider()
    crm_client = DeterministicCRMClient(lead)
    llm_client = FakeLLMClient()
    settings = Settings(recurring_paused_search_pilot_workspace_ids=[WORKSPACE_ID])

    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncSession]:
        yield postgres_session

    monkeypatch.setattr(temporal_activities, "async_session_factory", session_factory)
    monkeypatch.setattr(temporal_activities, "get_settings", lambda: settings)
    monkeypatch.setattr(temporal_activities, "build_crm_client", lambda _=None: crm_client)
    monkeypatch.setattr(temporal_activities, "build_llm_client", lambda _=None: llm_client)
    monkeypatch.setattr(temporal_activities, "build_email_provider", lambda _=None: email_provider)
    monkeypatch.setattr(temporal_activities, "build_sms_provider", lambda _=None: FakeSMSProvider())
    monkeypatch.setattr(
        temporal_activities,
        "build_listing_search_client",
        lambda: FakeListingSearchClient(()),
    )
    return email_provider