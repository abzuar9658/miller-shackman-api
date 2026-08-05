from app.application.use_cases.apply_lead_state_classification import (
    ApplyLeadStateClassificationStatus,
    apply_lead_state_classification,
)
from app.domain.leads import LeadClassificationAppliedStatus
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCrmConversationEventRepository,
    FakeLeadClassificationArtifactRepository,
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeWorkspaceLLMConfigRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeTemporalSignalOutboxRepository,
)
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAssignmentRepository,
)
from tests.application.use_cases.test_apply_lead_state_classification import (
    LEAD_ID,
    NOW,
    WORKSPACE_ID,
    _classification_json,
    _lead,
    _StubLLMClient,
    _track_repository,
    _workflow,
    _workspace_llm_config,
)


async def test_classification_persists_assignment_and_pins_workflow_version() -> None:
    lead_repository = FakeLeadRepository(_lead())
    workflow_repository = FakeLeadWorkflowRepository()
    workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)] = _workflow()
    assignment_repository = FakePausedSearchTrackAssignmentRepository()
    track_repository = _track_repository()
    artifact_repository = FakeLeadClassificationArtifactRepository()
    client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            selected_track_key="waiting-for-rates",
            confidence=0.9,
            evidence=["Lead asked us to check back after rates improve."],
            summary="Waiting for rates.",
        )
    )

    result = await apply_lead_state_classification(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        actor=None,
        lead_repository=lead_repository,
        paused_search_history_repository=lead_repository,
        artifact_repository=artifact_repository,
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(
            _workspace_llm_config()
        ),
        llm_client=client,
        now=NOW,
        lead_workflow_repository=workflow_repository,
        paused_search_track_repository=track_repository,
        paused_search_track_assignment_repository=assignment_repository,
        temporal_signal_outbox_repository=FakeTemporalSignalOutboxRepository(),
    )

    assert result.status is ApplyLeadStateClassificationStatus.APPLIED
    assert result.artifact is not None
    assert result.artifact.applied_status is LeadClassificationAppliedStatus.APPLIED
    assert result.classification_result is not None
    assignment = await assignment_repository.get_active_for_lead(WORKSPACE_ID, LEAD_ID)
    assert assignment is not None
    assert assignment.track_version_id == result.classification_result.track_version_id
    workflow = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert workflow.paused_search_track_version_id == assignment.track_version_id