import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.application.services.llm.lead_state_classification import (
    LeadStateClassificationStatus,
)
from app.application.use_cases.route_ai_nurture_lead import (
    AiNurtureRoute,
    route_ai_nurture_lead,
)
from app.core.config import get_settings
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.leads import (
    ActivityReliability,
    CanonicalLeadRecord,
    CRMProvider,
    LeadStateClassificationOutcome,
    LeadType,
    lead_paused_search_profile,
)
from app.infrastructure.providers import build_llm_client
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCrmConversationEventRepository,
    FakeLeadClassificationArtifactRepository,
    FakeLeadRepository,
    FakeWorkspaceLLMConfigRepository,
)

NOW = datetime(2026, 7, 31, 15, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000101")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000102")


@dataclass(frozen=True)
class LiveClassificationCase:
    name: str
    message: str
    occurred_at: datetime
    expected_route: AiNurtureRoute


CASES = (
    LiveClassificationCase(
        "waiting_for_rates",
        "We still want to buy, but rates are too high. Please check back with us this fall.",
        NOW - timedelta(hours=2),
        AiNurtureRoute.PAUSED_SEARCH,
    ),
    LiveClassificationCase(
        "rented_temporarily",
        "We rented a place for the next year, so please pause our home search "
        "until our lease is closer to ending.",
        NOW - timedelta(hours=2),
        AiNurtureRoute.PAUSED_SEARCH,
    ),
    LiveClassificationCase(
        "timing_not_right",
        "We still want to buy, but the timing is not right. Please check back with us next spring.",
        NOW - timedelta(hours=2),
        AiNurtureRoute.PAUSED_SEARCH,
    ),
    LiveClassificationCase(
        "waiting_for_inventory",
        "We are pausing our search until more homes become available in our "
        "preferred neighborhood.",
        NOW - timedelta(hours=2),
        AiNurtureRoute.PAUSED_SEARCH,
    ),
    LiveClassificationCase(
        "financial_prep",
        "We need time to improve our savings and get our finances ready before we can buy.",
        NOW - timedelta(hours=2),
        AiNurtureRoute.PAUSED_SEARCH,
    ),
    LiveClassificationCase(
        "personal_life_timing",
        "A family situation has come up, so we need to pause the search until things settle down.",
        NOW - timedelta(hours=2),
        AiNurtureRoute.PAUSED_SEARCH,
    ),
    LiveClassificationCase(
        "other_known_pause",
        "We are putting the search on hold because of a specific personal plan "
        "and will let you know when that changes.",
        NOW - timedelta(hours=2),
        AiNurtureRoute.PAUSED_SEARCH,
    ),
    LiveClassificationCase(
        "active_showing_request",
        "We are ready to see homes this weekend. Can you arrange a showing for us?",
        NOW - timedelta(hours=1),
        AiNurtureRoute.HUMAN_HANDOFF,
    ),
    LiveClassificationCase(
        "opt_out",
        "Please stop contacting me and remove me from your follow-up list.",
        NOW - timedelta(hours=1),
        AiNurtureRoute.BLOCKED,
    ),
    LiveClassificationCase(
        "dormant",
        "We were interested in a home months ago, but we have not made any decisions.",
        NOW - timedelta(days=120),
        AiNurtureRoute.DORMANT,
    ),
)


@pytest.mark.live_llm
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
async def test_live_llm_paused_search_classification(
    case: LiveClassificationCase,
) -> None:
    settings = get_settings()
    if settings.openrouter_api_key is None or not settings.openrouter_api_key.get_secret_value():
        pytest.fail("OPENROUTER_API_KEY is required when --run-live-llm is supplied")

    lead = CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id=f"live-{case.name}",
        facts_derived_at=NOW,
        source_payload_version="live-test:v1",
        lead_type=LeadType.BUYER,
        lead_source="synthetic_live_test",
        lead_stage="long_term_nurture",
        activity_reliability=ActivityReliability.RELIABLE,
        has_email=True,
        primary_email="synthetic-lead@example.com",
    )
    event = CrmConversationEvent(
        crm_conversation_event_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        crm_activity_id=f"live-{case.name}",
        activity_type="email",
        occurred_at=case.occurred_at,
        created_at=case.occurred_at,
        updated_at=case.occurred_at,
        direction=CrmConversationEventDirection.INBOUND,
        content=case.message,
    )
    lead_repository = FakeLeadRepository(lead)
    event_repository = FakeCrmConversationEventRepository((event,))
    artifact_repository = FakeLeadClassificationArtifactRepository()

    route_result = await route_ai_nurture_lead(
        workspace_id=WORKSPACE_ID,
        lead=lead,
        lead_repository=lead_repository,
        paused_search_history_repository=lead_repository,
        artifact_repository=artifact_repository,
        crm_conversation_event_repository=event_repository,
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=build_llm_client(settings),
        now=NOW,
        default_openrouter_model=settings.openrouter_model,
        dormant_threshold_days=60,
    )
    classification = route_result.classification_result
    artifact = artifact_repository.saved[-1]
    stored_lead = await lead_repository.get_by_id(WORKSPACE_ID, LEAD_ID)
    assert stored_lead is not None
    stored_profile = lead_paused_search_profile(stored_lead)
    report = {
        "case": case.name,
        "expected_route": case.expected_route.value,
        "actual_route": route_result.route.value,
        "classification": asdict(classification) if classification else None,
        "artifact": asdict(artifact),
        "paused_search_profile": asdict(stored_profile) if stored_profile else None,
    }
    print(json.dumps(report, indent=2, default=str))

    assert classification is not None
    assert classification.status == LeadStateClassificationStatus.CLASSIFIED
    assert route_result.route == case.expected_route
    assert artifact.raw_llm_response_text == classification.raw_llm_response_text
    assert artifact.parsed_llm_response == classification.parsed_llm_response
    if classification.outcome == LeadStateClassificationOutcome.PAUSED_SEARCH:
        assert stored_profile is not None
        assert stored_profile.pause_reason_code == classification.pause_reason_code
    else:
        assert stored_profile is None
