import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.services.llm.lead_state_classification import (
    LeadStateClassificationResult,
    LeadStateClassificationStatus,
)
from app.application.use_cases.apply_lead_state_classification import (
    ApplyLeadStateClassificationStatus,
    apply_lead_state_classification,
)
from app.application.use_cases.route_ai_nurture_lead import AiNurtureRoute, route_ai_nurture_lead
from app.core.config import get_settings
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.leads import (
    ActivityReliability,
    CanonicalLeadRecord,
    CRMProvider,
    LeadClassificationAppliedStatus,
    LeadClassificationArtifact,
    LeadStateClassificationOutcome,
    LeadType,
    PausedSearchAction,
    PausedSearchReasonCode,
    PausedSearchSource,
    lead_paused_search_profile,
)
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresCrmConversationEventRepository,
)
from app.infrastructure.persistence.postgres.lead_classification_artifact_repository import (
    PostgresLeadClassificationArtifactRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import WorkspaceModel
from app.infrastructure.persistence.postgres.workspace_llm_config_repository import (
    PostgresWorkspaceLLMConfigRepository,
)
from app.infrastructure.providers import build_llm_client

NOW = datetime(2026, 7, 31, 15, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("30000000-0000-0000-0000-000000000001")
OTHER_WORKSPACE_ID = UUID("30000000-0000-0000-0000-000000000002")
LEAD_ID = UUID("30000000-0000-0000-0000-000000000003")


class _UnexpectedLLMClient:
    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        raise AssertionError(f"unexpected LLM request: {request.prompt_version}")


class _FailingArtifactRepository:
    async def get_by_id(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> LeadClassificationArtifact | None:
        _ = (workspace_id, artifact_id)
        return None

    async def save(self, artifact: LeadClassificationArtifact) -> LeadClassificationArtifact:
        _ = artifact
        raise RuntimeError("simulated artifact persistence failure")

    async def list_for_lead(
        self,
        workspace_id: UUID,
        lead_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[LeadClassificationArtifact, ...]:
        _ = (workspace_id, lead_id, limit)
        return ()


@pytest.mark.live_llm
async def test_live_classification_persists_paused_search_state_in_postgres(
    postgres_session: AsyncSession,
) -> None:
    settings = get_settings()
    if settings.openrouter_api_key is None or not settings.openrouter_api_key.get_secret_value():
        pytest.fail("OPENROUTER_API_KEY is required when --run-live-llm is supplied")
    await _seed_workspace_and_lead(postgres_session)
    lead_repository = PostgresLeadRepository(postgres_session)
    event_repository = PostgresCrmConversationEventRepository(postgres_session)
    artifact_repository = PostgresLeadClassificationArtifactRepository(postgres_session)
    await event_repository.save(_conversation_event())

    lead = await lead_repository.get_by_id(WORKSPACE_ID, LEAD_ID)
    assert lead is not None
    route_result = await route_ai_nurture_lead(
        workspace_id=WORKSPACE_ID,
        lead=lead,
        lead_repository=lead_repository,
        paused_search_history_repository=lead_repository,
        artifact_repository=artifact_repository,
        crm_conversation_event_repository=event_repository,
        workspace_llm_config_repository=PostgresWorkspaceLLMConfigRepository(postgres_session),
        llm_client=build_llm_client(settings),
        now=NOW,
        default_openrouter_model=settings.openrouter_model,
        dormant_threshold_days=60,
    )
    await postgres_session.flush()
    postgres_session.expire_all()

    classification = route_result.classification_result
    assert classification is not None
    assert classification.status == LeadStateClassificationStatus.CLASSIFIED
    assert classification.pause_reason_code == PausedSearchReasonCode.WAITING_FOR_RATES
    assert route_result.route == AiNurtureRoute.PAUSED_SEARCH

    stored_lead = await lead_repository.get_by_id(WORKSPACE_ID, LEAD_ID)
    stored_events = await event_repository.list_for_lead(WORKSPACE_ID, LEAD_ID)
    stored_artifacts = await artifact_repository.list_for_lead(WORKSPACE_ID, LEAD_ID)
    stored_history = await lead_repository.list_for_lead(WORKSPACE_ID, LEAD_ID)
    assert stored_lead is not None
    stored_profile = lead_paused_search_profile(stored_lead)
    assert stored_profile is not None
    assert stored_profile.pause_reason_code == PausedSearchReasonCode.WAITING_FOR_RATES
    assert stored_profile.paused_search_source == PausedSearchSource.AI_CONVERSATION_CLASSIFICATION
    assert len(stored_events) == 1
    assert stored_events[0].direction == CrmConversationEventDirection.INBOUND
    assert stored_events[0].content == _conversation_event().content
    assert len(stored_artifacts) == 1
    assert stored_artifacts[0].raw_llm_response_text == classification.raw_llm_response_text
    assert stored_artifacts[0].parsed_llm_response == classification.parsed_llm_response
    assert stored_artifacts[0].applied_status == LeadClassificationAppliedStatus.APPLIED
    assert len(stored_history) == 1
    assert stored_history[0].action == PausedSearchAction.SET
    assert await lead_repository.get_by_id(OTHER_WORKSPACE_ID, LEAD_ID) is None
    assert await artifact_repository.list_for_lead(OTHER_WORKSPACE_ID, LEAD_ID) == ()
    assert await lead_repository.list_for_lead(OTHER_WORKSPACE_ID, LEAD_ID) == ()

    repeat_result = await apply_lead_state_classification(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        actor=None,
        lead_repository=lead_repository,
        paused_search_history_repository=lead_repository,
        artifact_repository=artifact_repository,
        crm_conversation_event_repository=event_repository,
        workspace_llm_config_repository=PostgresWorkspaceLLMConfigRepository(postgres_session),
        llm_client=_UnexpectedLLMClient(),
        now=NOW,
        precomputed_classification_result=classification,
    )
    assert repeat_result.status == ApplyLeadStateClassificationStatus.UNCHANGED
    postgres_session.expire_all()
    repeated_lead = await lead_repository.get_by_id(WORKSPACE_ID, LEAD_ID)
    assert repeated_lead is not None
    assert lead_paused_search_profile(repeated_lead) == stored_profile
    assert len(await lead_repository.list_for_lead(WORKSPACE_ID, LEAD_ID)) == 1
    assert len(await artifact_repository.list_for_lead(WORKSPACE_ID, LEAD_ID)) == 2

    print(
        json.dumps(
            {
                "route": route_result.route.value,
                "pause_reason_code": stored_profile.pause_reason_code.value,
                "artifact_rows": 2,
                "history_rows": 1,
                "repeat_status": repeat_result.status.value,
            },
            indent=2,
        )
    )


async def test_classification_savepoint_rollback_removes_partial_postgres_writes(
    postgres_session: AsyncSession,
) -> None:
    await _seed_workspace_and_lead(postgres_session)
    lead_repository = PostgresLeadRepository(postgres_session)
    artifact_repository = PostgresLeadClassificationArtifactRepository(postgres_session)

    with pytest.raises(RuntimeError, match="simulated artifact persistence failure"):
        async with postgres_session.begin_nested():
            await apply_lead_state_classification(
                workspace_id=WORKSPACE_ID,
                lead_id=LEAD_ID,
                actor=None,
                lead_repository=lead_repository,
                paused_search_history_repository=lead_repository,
                artifact_repository=_FailingArtifactRepository(),
                crm_conversation_event_repository=PostgresCrmConversationEventRepository(
                    postgres_session
                ),
                workspace_llm_config_repository=PostgresWorkspaceLLMConfigRepository(
                    postgres_session
                ),
                llm_client=_UnexpectedLLMClient(),
                now=NOW,
                precomputed_classification_result=_classification_result(),
            )

    postgres_session.expire_all()
    stored_lead = await lead_repository.get_by_id(WORKSPACE_ID, LEAD_ID)
    assert stored_lead is not None
    assert lead_paused_search_profile(stored_lead) is None
    assert await lead_repository.list_for_lead(WORKSPACE_ID, LEAD_ID) == ()
    assert await artifact_repository.list_for_lead(WORKSPACE_ID, LEAD_ID) == ()


async def _seed_workspace_and_lead(session: AsyncSession) -> None:
    session.add(
        WorkspaceModel(
            workspace_id=WORKSPACE_ID,
            name="Live Classification Test Workspace",
            status="active",
            default_timezone="UTC",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()
    await PostgresLeadRepository(session).upsert(_lead())


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="live-postgres-waiting-for-rates",
        facts_derived_at=NOW,
        source_payload_version="live-postgres-test:v1",
        lead_type=LeadType.BUYER,
        lead_source="synthetic_live_test",
        lead_stage="long_term_nurture",
        activity_reliability=ActivityReliability.RELIABLE,
        has_email=True,
        primary_email="synthetic-postgres-lead@example.com",
    )


def _conversation_event() -> CrmConversationEvent:
    occurred_at = NOW - timedelta(hours=2)
    return CrmConversationEvent(
        crm_conversation_event_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        crm_activity_id="live-postgres-waiting-for-rates",
        activity_type="email",
        occurred_at=occurred_at,
        created_at=occurred_at,
        updated_at=occurred_at,
        direction=CrmConversationEventDirection.INBOUND,
        content=(
            "We still want to buy, but rates are too high. Please check back with us this fall."
        ),
    )


def _classification_result() -> LeadStateClassificationResult:
    return LeadStateClassificationResult(
        status=LeadStateClassificationStatus.CLASSIFIED,
        prompt_version="rollback-test:v1",
        model="test-model",
        latency_ms=1,
        usage_tokens=1,
        outcome=LeadStateClassificationOutcome.PAUSED_SEARCH,
        pause_reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
        confidence=0.9,
        evidence=("rates are too high",),
        summary="The lead is waiting for rates to improve.",
        raw_llm_response_text='{"outcome":"paused_search"}',
        parsed_llm_response={"outcome": "paused_search"},
    )
