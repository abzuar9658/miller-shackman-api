import asyncio
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.application.use_cases.crm_sync import (
    ExecuteQueuedCRMSyncResult,
    ExecuteQueuedCRMSyncStatus,
)
from app.core.config import Settings
from app.domain.crm_sync import CRMSyncJob, CRMSyncJobStatus, CRMSyncLeadSort, CRMSyncType
from app.domain.events import DomainEventType
from app.interfaces.workers import crm_sync_worker


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.commit_count = 0

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        _ = (exc_type, exc, tb)

    async def commit(self) -> None:
        self.committed = True
        self.commit_count += 1


@dataclass
class _FakeLogger:
    records: list[tuple[str, str, dict[str, Any]]]

    def info(self, event: str, **kwargs: Any) -> None:
        self.records.append(("info", event, kwargs))

    def exception(self, event: str, **kwargs: Any) -> None:
        self.records.append(("exception", event, kwargs))


def _completed_job() -> CRMSyncJob:
    return CRMSyncJob(
        sync_job_id=UUID("22222222-2222-2222-2222-222222222222"),
        workspace_id=UUID("11111111-1111-1111-1111-111111111111"),
        crm_provider="follow_up_boss",
        sync_type=CRMSyncType.INCREMENTAL,
        status=CRMSyncJobStatus.COMPLETED,
        started_at=NOW,
        finished_at=NOW,
        cursor_started_at=NOW,
        cursor_finished_at=NOW,
        total_seen=3,
        total_upserted=3,
        total_failed=0,
        failure_reason=None,
        last_heartbeat_at=NOW,
        created_by_user_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _running_job() -> CRMSyncJob:
    return replace(
        _completed_job(),
        status=CRMSyncJobStatus.RUNNING,
        finished_at=None,
    )


class _FakeHeartbeatRepository:
    def __init__(self, results: list[CRMSyncJob | None]) -> None:
        self._results = results
        self.calls: list[datetime] = []

    async def touch_running_heartbeat(
        self,
        workspace_id: UUID,
        sync_job_id: UUID,
        *,
        now: datetime,
    ) -> CRMSyncJob | None:
        _ = (workspace_id, sync_job_id)
        self.calls.append(now)
        if self._results:
            return self._results.pop(0)
        return None


NOW = datetime(2026, 7, 27, 18, 0, tzinfo=UTC)


async def test_run_once_passes_recent_limit_options_to_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    captured: dict[str, object] = {}
    temporal_starter = object()
    fake_logger = _FakeLogger([])

    async def fake_enable_postgres_service_access(_: object) -> None:
        return None

    async def fake_execute_queued_follow_up_boss_crm_sync(
        **kwargs: object,
    ) -> ExecuteQueuedCRMSyncResult:
        captured.update(kwargs)
        return ExecuteQueuedCRMSyncResult(
            status=ExecuteQueuedCRMSyncStatus.COMPLETED,
            job=_completed_job(),
            page_count=2,
        )

    async def fake_build_temporal_workflow_starter(_: object) -> object:
        return temporal_starter

    async def fake_run_running_sync_heartbeat_loop(**_: object) -> None:
        return None

    monkeypatch.setattr(crm_sync_worker, "async_session_factory", lambda: session)
    monkeypatch.setattr(
        crm_sync_worker,
        "enable_postgres_service_access",
        fake_enable_postgres_service_access,
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "build_temporal_workflow_starter",
        fake_build_temporal_workflow_starter,
    )
    monkeypatch.setattr(crm_sync_worker, "build_crm_client", lambda _: "crm-client")
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresCampaignExecutionRepository",
        lambda _: "campaign-execution-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresWorkspaceContactPolicyRepository",
        lambda _: "contact-policy-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresCampaignEnrollmentRepository",
        lambda _: "campaign-enrollment-repository",
    )
    monkeypatch.setattr(crm_sync_worker, "PostgresLeadRepository", lambda _: "lead-repository")
    monkeypatch.setattr(crm_sync_worker, "PostgresCRMSyncJobRepository", lambda _: "job-repository")
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresCRMSyncWindowStateRepository",
        lambda _: "window-state-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresLeadWorkflowRepository",
        lambda _: "lead-workflow-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresWorkflowTransitionRepository",
        lambda _: "workflow-transition-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresPausedSearchTrackAdminRepository",
        lambda _: "paused-search-track-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresCrmConversationEventRepository",
        lambda _: "conversation-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresOutboxEventRepository",
        lambda _: "outbox-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresTransactionalEventBus",
        lambda _: "event-bus",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresWorkspaceOperationalControlRepository",
        lambda _: "operational-control-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresHandoffRepository",
        lambda _: "handoff-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresHandoffCompletionRepository",
        lambda _: "handoff-completion-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresWorkspaceHandoffConfigRepository",
        lambda _: "workspace-handoff-config-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresCRMAgentRepository",
        lambda _: "crm-agent-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresWorkspaceAgentCRMMappingRepository",
        lambda _: "crm-agent-mapping-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresWorkspaceAgentMappingConfigRepository",
        lambda _: "crm-agent-mapping-config-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresWorkspaceMembershipRepository",
        lambda _: "workspace-membership-repository",
    )
    monkeypatch.setattr(crm_sync_worker, "PostgresUserRepository", lambda _: "user-repository")
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresTemporalSignalOutboxRepository",
        lambda _: "temporal-signal-outbox-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresOutboundMessageRepository",
        lambda _: "outbound-message-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresLeadClassificationArtifactRepository",
        lambda _: "lead-classification-artifact-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresWorkspaceLLMConfigRepository",
        lambda _: "workspace-llm-config-repository",
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "build_notification_provider",
        lambda _: "notification-provider",
    )
    monkeypatch.setattr(crm_sync_worker, "build_llm_client", lambda _: "llm-client")
    monkeypatch.setattr(
        crm_sync_worker,
        "execute_queued_follow_up_boss_crm_sync",
        fake_execute_queued_follow_up_boss_crm_sync,
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "_run_running_sync_heartbeat_loop",
        fake_run_running_sync_heartbeat_loop,
    )
    monkeypatch.setattr(crm_sync_worker, "logger", fake_logger)

    await crm_sync_worker.run_once(
        json.dumps(
            {
                "workspace_id": "11111111-1111-1111-1111-111111111111",
                "event_type": DomainEventType.CRM_SYNC_REQUESTED.value,
                "payload": {
                    "sync_job_id": "22222222-2222-2222-2222-222222222222",
                    "max_leads": 50,
                    "latest_by": "updated",
                    "resume_cursor": "cursor-2",
                    "updated_after": "2026-07-27T17:00:00+00:00",
                    "updated_before": "2026-07-27T18:00:00+00:00",
                },
            }
        ).encode("utf-8"),
        settings=Settings(),
    )

    assert captured["workspace_id"] == UUID("11111111-1111-1111-1111-111111111111")
    assert captured["sync_job_id"] == UUID("22222222-2222-2222-2222-222222222222")
    assert captured["max_leads"] == 50
    assert captured["latest_by"] == CRMSyncLeadSort.UPDATED
    assert captured["resume_cursor"] == "cursor-2"
    assert str(captured["updated_after"]) == "2026-07-27 17:00:00+00:00"
    assert str(captured["updated_before"]) == "2026-07-27 18:00:00+00:00"
    assert captured["lead_snapshot_source"] == "crm-client"
    assert captured["crm_activity_source"] == "crm-client"
    assert captured["crm_conversation_event_repository"] == "conversation-repository"
    assert captured["crm_sync_window_state_repository"] == "window-state-repository"
    assert captured["campaign_execution_repository"] == "campaign-execution-repository"
    assert captured["workspace_contact_policy_repository"] == "contact-policy-repository"
    assert captured["campaign_enrollment_repository"] == "campaign-enrollment-repository"
    assert captured["lead_workflow_repository"] == "lead-workflow-repository"
    assert captured["workflow_transition_repository"] == "workflow-transition-repository"
    assert captured["paused_search_track_repository"] == "paused-search-track-repository"
    assert captured["temporal_workflow_starter"] is temporal_starter
    assert captured["event_bus"] == "event-bus"
    assert captured["workspace_operational_control_repository"] == "operational-control-repository"
    assert captured["handoff_repository"] == "handoff-repository"
    assert captured["handoff_completion_repository"] == "handoff-completion-repository"
    assert captured["workspace_handoff_config_repository"] == "workspace-handoff-config-repository"
    assert captured["notification_provider"] == "notification-provider"
    assert captured["crm_agent_repository"] == "crm-agent-repository"
    assert captured["workspace_agent_crm_mapping_repository"] == "crm-agent-mapping-repository"
    assert (
        captured["workspace_agent_mapping_config_repository"]
        == "crm-agent-mapping-config-repository"
    )
    assert captured["workspace_membership_repository"] == "workspace-membership-repository"
    assert captured["user_repository"] == "user-repository"
    assert captured["temporal_signal_outbox_repository"] == "temporal-signal-outbox-repository"
    assert captured["outbound_message_repository"] == "outbound-message-repository"
    artifact_repo = captured["lead_classification_artifact_repository"]
    assert artifact_repo == "lead-classification-artifact-repository"
    assert captured["workspace_llm_config_repository"] == "workspace-llm-config-repository"
    assert captured["llm_client"] == "llm-client"
    assert captured["default_openrouter_model"] == Settings().openrouter_model
    assert callable(captured["commit"])
    assert callable(captured["heartbeat_now_factory"])
    assert callable(captured["lease_lost_checker"])
    assert session.committed is True
    assert [record[1] for record in fake_logger.records] == [
        "crm_sync_worker_message_received",
        "crm_sync_worker_sync_finished",
    ]
    assert fake_logger.records[1][2]["total_seen"] == 3


async def test_run_running_sync_heartbeat_loop_sets_lease_lost_after_running_job_disappears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    repository = _FakeHeartbeatRepository([_running_job(), None])
    stop_event = asyncio.Event()
    lease_lost_event = asyncio.Event()

    async def fake_enable_postgres_service_access(_: object) -> None:
        return None

    monkeypatch.setattr(crm_sync_worker, "async_session_factory", lambda: session)
    monkeypatch.setattr(
        crm_sync_worker,
        "enable_postgres_service_access",
        fake_enable_postgres_service_access,
    )
    monkeypatch.setattr(
        crm_sync_worker,
        "PostgresCRMSyncJobRepository",
        lambda _: repository,
    )

    await asyncio.wait_for(
        crm_sync_worker._run_running_sync_heartbeat_loop(
            workspace_id=UUID("11111111-1111-1111-1111-111111111111"),
            sync_job_id=UUID("22222222-2222-2222-2222-222222222222"),
            settings=Settings(crm_sync_running_heartbeat_interval_seconds=0),
            stop_event=stop_event,
            lease_lost_event=lease_lost_event,
        ),
        timeout=1,
    )

    assert lease_lost_event.is_set()
    assert session.commit_count == 2
