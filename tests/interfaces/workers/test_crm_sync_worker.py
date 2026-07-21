import json
from uuid import UUID

import pytest

from app.core.config import Settings
from app.domain.crm_sync import CRMSyncLeadSort
from app.domain.events import DomainEventType
from app.interfaces.workers import crm_sync_worker


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        _ = (exc_type, exc, tb)

    async def commit(self) -> None:
        self.committed = True


async def test_run_once_passes_recent_limit_options_to_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    captured: dict[str, object] = {}
    temporal_starter = object()

    async def fake_enable_postgres_service_access(_: object) -> None:
        return None

    async def fake_execute_queued_follow_up_boss_crm_sync(**kwargs: object) -> None:
        captured.update(kwargs)

    async def fake_build_temporal_workflow_starter(_: object) -> object:
        return temporal_starter

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
        "execute_queued_follow_up_boss_crm_sync",
        fake_execute_queued_follow_up_boss_crm_sync,
    )

    await crm_sync_worker.run_once(
        json.dumps(
            {
                "workspace_id": "11111111-1111-1111-1111-111111111111",
                "event_type": DomainEventType.CRM_SYNC_REQUESTED.value,
                "payload": {
                    "sync_job_id": "22222222-2222-2222-2222-222222222222",
                    "max_leads": 50,
                    "latest_by": "updated",
                },
            }
        ).encode("utf-8"),
        settings=Settings(),
    )

    assert captured["workspace_id"] == UUID("11111111-1111-1111-1111-111111111111")
    assert captured["sync_job_id"] == UUID("22222222-2222-2222-2222-222222222222")
    assert captured["max_leads"] == 50
    assert captured["latest_by"] == CRMSyncLeadSort.UPDATED
    assert captured["lead_snapshot_source"] == "crm-client"
    assert captured["crm_activity_source"] == "crm-client"
    assert captured["crm_conversation_event_repository"] == "conversation-repository"
    assert captured["campaign_execution_repository"] == "campaign-execution-repository"
    assert captured["workspace_contact_policy_repository"] == "contact-policy-repository"
    assert captured["campaign_enrollment_repository"] == "campaign-enrollment-repository"
    assert captured["lead_workflow_repository"] == "lead-workflow-repository"
    assert captured["workflow_transition_repository"] == "workflow-transition-repository"
    assert captured["temporal_workflow_starter"] is temporal_starter
    assert captured["event_bus"] == "event-bus"
    assert captured["workspace_operational_control_repository"] == "operational-control-repository"
    assert callable(captured["commit"])
    assert session.committed is True